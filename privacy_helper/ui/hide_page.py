"""Hide details: paste or open text, review what was found, copy or save the safe version."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import documents
from ..core.masking import (
    KINDS,
    PATTERN_KINDS,
    SOURCE_CLUE,
    SOURCE_MANUAL,
    SOURCE_TOPIC,
    Detection,
    Detector,
    Session,
    _norm,
    apply,
    resolve_overlaps,
)
from ..core.vault import KIND_MASK, Vault
from .common import error_label, hint, page_header, primary

MAX_OPEN_MB = 50   # keeps the review screen responsive
OPEN_FILTER = "Supported files (*.txt *.md *.csv *.xlsx *.docx);;All files (*)"


class ColumnsDialog(QDialog):
    """Staff confirm what each spreadsheet column holds. Suggestions are pre-filled."""

    ROLES = [(documents.HIDE, "Hide the whole value"), (documents.SCAN, "Look for details in the text"),
             (documents.KEEP, "Keep as it is")]

    def __init__(self, table: documents.Table, file_name: str, parent=None):
        super().__init__(parent)
        self.table = table
        self.setWindowTitle(f"Columns in {file_name}")
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Which columns hold personal details?</b>"))
        lay.addWidget(hint("Suggestions are filled in from the column names and contents. Check them before "
                           "continuing. Every value in a hidden column is also hidden wherever it appears in "
                           "notes and messages."))
        grid = QTableWidget(len(table.columns), 4)
        grid.setHorizontalHeaderLabels(["Column", "Example", "What to do", "Type of detail"])
        grid.verticalHeader().hide()
        grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        grid.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.role_boxes, self.kind_boxes = [], []
        for i, col in enumerate(table.columns):
            example = next((r[i] for r in table.rows if r[i].strip()), "")
            grid.setItem(i, 0, _item(col.name))
            grid.setItem(i, 1, _item(example[:60] + ("…" if len(example) > 60 else "")))
            role = QComboBox()
            for value, label in self.ROLES:
                role.addItem(label, value)
            role.setCurrentIndex([r for r, _ in self.ROLES].index(col.role))
            kind = QComboBox()
            for value, label in KINDS.items():
                kind.addItem(label, value)
            kind.setCurrentIndex(list(KINDS).index(col.kind))
            role.currentIndexChanged.connect(lambda _, r=role, k=kind: k.setEnabled(r.currentData() == documents.HIDE))
            kind.setEnabled(col.role == documents.HIDE)
            grid.setCellWidget(i, 2, role)
            grid.setCellWidget(i, 3, kind)
            self.role_boxes.append(role)
            self.kind_boxes.append(kind)
        head = grid.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(grid, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def accept(self) -> None:
        for col, role, kind in zip(self.table.columns, self.role_boxes, self.kind_boxes, strict=True):
            col.role, col.kind = role.currentData(), kind.currentData()
        super().accept()


def _item(text: str):
    from PySide6.QtWidgets import QTableWidgetItem
    return QTableWidgetItem(text)


class HidePage(QWidget):
    session_saved = Signal()

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.source_name = ""          # file name, or empty for pasted text
        self.source_path: Path | None = None
        self.table: documents.Table | None = None
        self.known: dict[str, str] = {}     # from spreadsheet columns
        self.manual: dict[str, str] = {}    # selected by hand
        self.choices: dict[str, bool] = {}  # staff ticked/unticked: normalised text -> hide?
        self.detections: list[Detection] = []
        self.session = Session()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(page_header("Hide details",
                                  "Paste a case note or open a file. Check what was found, then copy the safe "
                                  "version, or save it as a file to upload to your AI tool."))

        bar = QHBoxLayout()
        self.open_btn = QPushButton("Open File…")
        self.paste_btn = QPushButton("Paste")
        self.clear_btn = QPushButton("Clear")
        self.source_label = hint("")
        for b in (self.open_btn, self.paste_btn, self.clear_btn):
            bar.addWidget(b)
        bar.addSpacing(8)
        bar.addWidget(self.source_label, 1)
        lay.addLayout(bar)

        # Shown for spreadsheets whose visible columns can still single someone out.
        self.risk = QWidget()
        risk_row = QHBoxLayout(self.risk)
        risk_row.setContentsMargins(0, 4, 0, 4)
        self.risk_label = error_label()
        self.columns_btn = QPushButton("Change Columns…")
        risk_row.addWidget(self.risk_label, 1)
        risk_row.addWidget(self.columns_btn)
        self.risk.hide()
        lay.addWidget(self.risk)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        self.editor = DropTextEdit()
        self.editor.setPlaceholderText("Paste text here, or drop a .txt, .docx, .csv or .xlsx file.")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.editor, "Original")
        self.tabs.addTab(self.preview, "Safe version")
        split.addWidget(self.tabs)

        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(8, 0, 0, 0)
        side_lay.addWidget(QLabel("<b>Found details</b>"))
        side_lay.addWidget(hint("Ticked items are hidden. Untick anything that is safe to share."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Detail", "Found by"])
        self.tree.setRootIsDecorated(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        side_lay.addWidget(self.tree, 1)
        self.add_btn = QPushButton("Hide Selected Text")
        self.add_btn.setToolTip("Select words in the original text that were missed, then choose what they are.")
        side_lay.addWidget(self.add_btn)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        foot = QHBoxLayout()
        self.count_label = QLabel("")
        self.save_btn = QPushButton("Save as Word File…")
        self.copy_btn = primary(QPushButton("Copy Safe Version"))
        foot.addWidget(self.count_label, 1)
        foot.addWidget(self.save_btn)
        foot.addWidget(self.copy_btn)
        lay.addLayout(foot)

        self.timer = QTimer(self, singleShot=True, interval=350)
        self.timer.timeout.connect(self.refresh)
        self.editor.textChanged.connect(self.timer.start)
        self.editor.files_dropped.connect(lambda paths: self.open_path(paths[0]))
        self.open_btn.clicked.connect(self.choose_file)
        self.paste_btn.clicked.connect(self.paste)
        self.clear_btn.clicked.connect(self.clear)
        self.add_btn.clicked.connect(self.hide_selection)
        self.columns_btn.clicked.connect(self.change_columns)
        self.tree.itemChanged.connect(self.tree_toggled)
        self.copy_btn.clicked.connect(self.copy_safe)
        self.save_btn.clicked.connect(self.save_safe)
        self.refresh()

    # ---- input -------------------------------------------------------------
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", OPEN_FILTER)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if path.is_file() and path.stat().st_size > MAX_OPEN_MB * 1024 * 1024:
            QMessageBox.information(self, "File Too Large",
                                    f"{path.name} is larger than {MAX_OPEN_MB} MB. Split it into smaller files, "
                                    "or protect it as a whole in Protect Files.")
            return
        try:
            if suffix in documents.TABLE_TYPES:
                table = documents.read_table(path)
                if ColumnsDialog(table, path.name, self).exec() != QDialog.DialogCode.Accepted:
                    return
                self.clear()
                text = self._use_table(table)
            elif suffix in documents.SUPPORTED:
                text = documents.load_any_text(path)
                self.clear()
            else:
                QMessageBox.information(self, "File Not Supported",
                                        f"{path.name} cannot be opened here. Use a .txt, .docx, .csv or .xlsx "
                                        "file. To encrypt or lock other files, use Protect Files.")
                return
        except documents.FileReadError as exc:
            QMessageBox.warning(self, "Could Not Open File", str(exc))
            return
        self.source_name, self.source_path = path.name, path
        self.source_label.setText(path.name)
        self.editor.setPlainText(text)
        self.refresh()

    def _use_table(self, table: documents.Table) -> str:
        """Hide every value in the hidden columns, warn about rows that still stand out, return the text."""
        self.table = table
        detector = Detector()
        documents.add_known_terms(table, detector)
        self.known = dict(detector.known)
        rare, columns = documents.rare_rows(table)
        if rare:
            people = f"{rare} of {len(table.rows)} rows are" if rare != 1 else f"1 of {len(table.rows)} rows is"
            self.risk_label.setText(
                f"{people} the only one, or one of very few, with their mix of {', '.join(columns)}. Someone who "
                "knows the community could still tell who they are. Hide one of these columns, or group the values "
                "(for example ages 30–39) before sharing.")
        self.risk.setVisible(bool(rare))
        return documents.table_to_text(table.headers, table.rows)

    def change_columns(self) -> None:
        if self.table is None:
            return
        if ColumnsDialog(self.table, self.source_name, self).exec() != QDialog.DialogCode.Accepted:
            return
        self.choices, self.session = {}, Session()
        self.editor.setPlainText(self._use_table(self.table))
        self.refresh()

    def paste(self) -> None:
        self.editor.setFocus()
        self.editor.paste()

    def clear(self) -> None:
        self.editor.clear()
        self.preview.clear()
        self.table, self.known, self.manual, self.choices = None, {}, {}, {}
        self.risk.hide()
        self.source_name, self.source_path = "", None
        self.source_label.setText("")
        self.session = Session()
        self.refresh()

    # ---- detection ---------------------------------------------------------
    def detector(self) -> Detector:
        s = self.vault.settings
        patterns = tuple(k for k in PATTERN_KINDS if k not in s.off_patterns)
        det = Detector(never=s.never_hide, patterns=patterns, suggest_names=s.suggest_names)
        for term in s.always_hide:
            det.add_known(term, "OTHER")
        for term, kind in self.known.items():
            det.add_known(term, kind)
        return det

    def refresh(self) -> None:
        text = self.editor.toPlainText()
        found = self.detector().find(text) if text.strip() else []
        for term, kind in self.manual.items():
            for m in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE):
                found.append(Detection(m.start(), m.end(), m.group(0), kind, SOURCE_MANUAL, label="Added by you"))
        found = resolve_overlaps(found)
        for d in found:
            d.enabled = self.choices.get(_norm(d.text), d.enabled)
        self.detections = found
        self._paint()
        self._fill_tree()
        self._update_preview()

    def _paint(self) -> None:
        pal = self.palette()
        on = QColor(pal.color(QPalette.ColorRole.Highlight))
        on.setAlpha(70)
        selections = []
        for d in self.detections:
            sel = QTextEdit.ExtraSelection()
            cur = QTextCursor(self.editor.document())
            cur.setPosition(d.start)
            cur.setPosition(d.end, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            if d.enabled:
                fmt.setBackground(on)
            else:
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
                fmt.setUnderlineColor(pal.color(QPalette.ColorRole.PlaceholderText))
            sel.cursor, sel.format = cur, fmt
            selections.append(sel)
        self.editor.setExtraSelections(selections)

    def _fill_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        seen: set[str] = set()
        for d in self.detections:
            key = _norm(d.text)
            if key in seen:
                continue
            seen.add(key)
            if d.kind not in groups:
                groups[d.kind] = QTreeWidgetItem(self.tree, [KINDS[d.kind], ""])
                groups[d.kind].setFirstColumnSpanned(True)
                groups[d.kind].setExpanded(True)
            item = QTreeWidgetItem(groups[d.kind], [d.text, d.label])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if d.enabled else Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, key)
        for kind, item in groups.items():
            item.setText(0, f"{KINDS[kind]} ({item.childCount()})")
        self.tree.blockSignals(False)

    def tree_toggled(self, item: QTreeWidgetItem, column: int) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self.choices[key] = item.checkState(0) == Qt.CheckState.Checked
            for d in self.detections:
                if _norm(d.text) == key:
                    d.enabled = self.choices[key]
            self._paint()
            self._update_preview()

    def hide_selection(self) -> None:
        text = self.editor.textCursor().selectedText().strip()
        if not text:
            QMessageBox.information(self, "Select Text First",
                                    "Select the words in the original text that should be hidden, then try again.")
            return
        menu = QMenu(self)
        for kind, label in KINDS.items():
            menu.addAction(label).setData(kind)
        chosen = menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))
        if chosen:
            self.manual[" ".join(text.split())] = chosen.data()
            self.choices[_norm(text)] = True
            self.refresh()

    def _update_preview(self) -> None:
        text = self.editor.toPlainText()
        hidden = [d for d in self.detections if d.enabled]
        # Preview only: tokens are drawn from a scratch copy so nothing is recorded until staff copy or save.
        preview_session = Session(dict(self.session.mapping))
        self.preview.setPlainText(apply(text, hidden, preview_session) if text else "")
        n = len({_norm(d.text) for d in hidden})
        visible = [d for d in self.detections if d.source in (SOURCE_TOPIC, SOURCE_CLUE) and not d.enabled]
        topics = len({_norm(d.text) for d in visible if d.source == SOURCE_TOPIC})
        clues = len({_norm(d.text) for d in visible if d.source == SOURCE_CLUE})
        left = [f"{topics} protected topic{'s' if topics != 1 else ''}" if topics else "",
                f"{clues} identifying description{'s' if clues != 1 else ''}" if clues else ""]
        note = f" · {' and '.join(x for x in left if x)} left visible: check before sharing" if topics or clues else ""
        self.count_label.setText(f"{n} detail{'s' if n != 1 else ''} will be hidden{note}" if text.strip() else "")
        ready = bool(text.strip())
        self.copy_btn.setEnabled(ready)
        self.save_btn.setEnabled(ready)
        self.save_btn.setText(f"Save as {self._save_format()[0]} File…")

    # ---- output ------------------------------------------------------------
    def safe_text(self) -> str:
        text = self.editor.toPlainText()
        safe = apply(text, [d for d in self.detections if d.enabled], self.session)
        self._remember()
        return safe

    def _remember(self) -> None:
        """Save the tokens in the vault so the AI's reply can be restored, even next week."""
        label = self.source_name or " ".join(self.editor.toPlainText().split()[:6]) or "Pasted text"
        mapping = self.session.mapping
        existing = next((e for e in self.vault.entries if e.kind == KIND_MASK and e.mapping is mapping), None)
        if existing:
            self.vault.save()
        else:
            self.vault.add(KIND_MASK, label, mapping=self.session.mapping, source=str(self.source_path or ""))
        self.session_saved.emit()

    def copy_safe(self) -> None:
        QGuiApplication.clipboard().setText(self.safe_text())
        self.count_label.setText("Safe version copied. Paste it into your AI tool.")

    def _save_format(self) -> tuple[str, str, str]:
        """(name, suffix, file filter) for the safe file: the same type as the file it came from."""
        if self.table is None:
            if self.source_path and self.source_path.suffix.lower() == ".txt":
                return "Text", ".txt", "Text file (*.txt);;Word document (*.docx)"
            return "Word", ".docx", "Word document (*.docx);;Text file (*.txt)"
        if self.source_path and self.source_path.suffix.lower() == ".csv":
            return "CSV", ".csv", "CSV file (*.csv);;Excel workbook (*.xlsx)"
        return "Excel", ".xlsx", "Excel workbook (*.xlsx);;CSV file (*.csv)"

    def save_safe(self) -> None:
        stem = Path(self.source_name).stem if self.source_name else f"Safe copy {datetime.now():%Y-%m-%d %H%M}"
        name, suffix, filt = self._save_format()
        start = str((self.source_path.parent if self.source_path else Path.home()) / f"{stem} (safe){suffix}")
        path, _ = QFileDialog.getSaveFileName(self, f"Save as {name} File", start, filt)
        if not path:
            return
        path = Path(path)
        safe = self.safe_text()
        try:
            if self.table is not None:
                grid = list(csv.reader(io.StringIO(safe)))
                documents.save_table(path, grid[0], grid[1:])
            elif path.suffix.lower() == ".docx":
                documents.save_text_docx(path, safe)
            else:
                path.write_text(safe, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could Not Save", f"{path.name} could not be saved: {exc}")
            return
        self.count_label.setText(f"Saved {path.name}. Upload it to your AI tool, or copy the safe version.")

    def has_work(self) -> bool:
        return bool(self.editor.toPlainText().strip())


class DropTextEdit(QPlainTextEdit):
    files_dropped = Signal(list)

    def canInsertFromMimeData(self, source) -> bool:
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        files = [Path(u.toLocalFile()) for u in source.urls() if u.isLocalFile()] if source.hasUrls() else []
        if files:
            self.files_dropped.emit(files)
        else:
            super().insertFromMimeData(source)
