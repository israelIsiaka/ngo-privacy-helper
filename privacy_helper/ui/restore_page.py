"""Restore: paste or open the AI's reply and put the real details back."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import documents
from ..core.masking import restore
from ..core.vault import KIND_MASK, Vault
from .common import SECRET_CLEAR_SECONDS, copy_secret, hint, page_header, primary, read_table_asking
from .hide_page import MAX_OPEN_MB, OPEN_FILTER, DropTextEdit


class RestorePage(QWidget):
    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.source_path: Path | None = None   # file the reply was opened from
        self.grid: list[list[str]] | None = None   # restored rows, when the reply is a spreadsheet
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(page_header("Restore details",
                                  "Paste the AI's reply, or open the file it gave you. The real names and details "
                                  "are filled back in on this computer only."))

        row = QHBoxLayout()
        self.open_btn = QPushButton("Open File…")
        self.open_btn.clicked.connect(self.choose_file)
        row.addWidget(self.open_btn)
        row.addSpacing(12)
        row.addWidget(QLabel("Text it came from:"))
        self.sessions = QComboBox()
        self.sessions.setMinimumContentsLength(40)
        self.sessions.setAccessibleName("Text it came from")
        row.addWidget(self.sessions, 1)
        lay.addLayout(row)

        split = QSplitter(Qt.Orientation.Vertical)
        self.reply = DropTextEdit()
        self.reply.setPlaceholderText(
            "Paste the AI's reply here, or open or drop a Word, PDF, Excel, CSV or text file.")
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("The reply with real details will appear here.")
        split.addWidget(self.reply)
        split.addWidget(self.result)
        lay.addWidget(split, 1)

        foot = QHBoxLayout()
        self.status = hint("")
        self.restore_btn = primary(QPushButton("Restore Details"))
        self.copy_btn = QPushButton("Copy")
        self.save_btn = QPushButton("Save…")
        foot.addWidget(self.status, 1)
        for b in (self.restore_btn, self.copy_btn, self.save_btn):
            foot.addWidget(b)
        lay.addLayout(foot)

        self.restore_btn.clicked.connect(self.do_restore)
        self.copy_btn.clicked.connect(self.copy)
        self.save_btn.clicked.connect(self.save)
        self.reply.files_dropped.connect(self.load_file)
        self.reply.textChanged.connect(self._reply_edited)     # first: it clears the result the buttons look at
        self.reply.textChanged.connect(self._update_buttons)
        self.sessions.currentIndexChanged.connect(self._update_buttons)
        self._update_buttons()

    def reload_sessions(self) -> None:
        current = self.sessions.currentData()
        self.sessions.clear()
        for e in sorted((e for e in self.vault.entries if e.kind == KIND_MASK), key=lambda e: e.created, reverse=True):
            when = datetime.fromisoformat(e.created).strftime("%d %b %Y, %H:%M")
            self.sessions.addItem(f"{e.label}  ·  {when}  ·  {len(e.mapping)} details", e.id)
        if self.sessions.count() == 0:
            self.sessions.addItem("Nothing hidden yet. Use Hide Details first.", None)
        idx = self.sessions.findData(current)
        self.sessions.setCurrentIndex(max(idx, 0))
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.restore_btn.setEnabled(bool(self.reply.toPlainText().strip()) and self.sessions.currentData() is not None)
        has = bool(self.result.toPlainText())
        self.copy_btn.setEnabled(has)
        self.save_btn.setEnabled(has)
        self.save_btn.setText(f"Save as {self._save_format()[0]} File…")

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open the AI's Reply", "", OPEN_FILTER)
        if path:
            self.load_file([Path(path)])

    def load_file(self, paths: list[Path]) -> None:
        path = paths[0]
        if path.is_file() and path.stat().st_size > MAX_OPEN_MB * 1024 * 1024:
            QMessageBox.information(self, "File Too Large", f"{path.name} is larger than {MAX_OPEN_MB} MB.")
            return
        try:
            if path.suffix.lower() in documents.TABLE_TYPES:
                table = read_table_asking(self, path)
                if table is None:
                    return
                text = documents.table_to_text(table.headers, table.rows)
            else:
                text = documents.load_any_text(path)
        except documents.FileReadError as exc:
            QMessageBox.warning(self, "Could Not Open File", str(exc))
            return
        self.reply.setPlainText(text)
        self.source_path = path       # after setPlainText, which forgets the file
        self.status.setText(f"Opened {path.name}. Choose the text it came from, then Restore Details.")

    def _reply_edited(self) -> None:
        self.source_path = None
        self.grid = None
        self.result.clear()

    def _is_table(self) -> bool:
        return self.source_path is not None and self.source_path.suffix.lower() in documents.TABLE_TYPES

    def do_restore(self) -> None:
        entry = self.vault.get(self.sessions.currentData())
        if not entry:
            return
        if self._is_table():
            # Cell by cell, so a restored "Block C, Gusau" cannot split into two columns.
            self.grid, count = [], 0
            for row in csv.reader(io.StringIO(self.reply.toPlainText())):
                cells = [restore(cell, entry.mapping) for cell in row]
                self.grid.append([c for c, _ in cells])
                count += sum(n for _, n in cells)
            text = documents.table_to_text(self.grid[0], self.grid[1:]) if self.grid else ""
        else:
            text, count = restore(self.reply.toPlainText(), entry.mapping)
        self.result.setPlainText(text)
        self.status.setText(f"{count} detail{'s' if count != 1 else ''} restored." if count else
                            "No codes from this text were found in the reply. "
                            "Check that the right text is chosen above.")
        self._update_buttons()

    def copy(self) -> None:
        # The restored text holds real names: keep it out of Windows clipboard history and cloud sync too.
        copy_secret(self.result.toPlainText())
        self.status.setText(f"Copied. It is removed from the clipboard after {SECRET_CLEAR_SECONDS} seconds.")

    def _save_format(self) -> tuple[str, str, str]:
        """(name, suffix, file filter): the same type as the file the reply came in."""
        suffix = self.source_path.suffix.lower() if self.source_path else ""
        if self.grid is not None:
            if suffix == ".csv":
                return "CSV", ".csv", "CSV file (*.csv);;Excel workbook (*.xlsx)"
            return "Excel", ".xlsx", "Excel workbook (*.xlsx);;CSV file (*.csv)"
        if suffix in documents.TEXT_TYPES:
            return "Text", ".txt", "Text file (*.txt);;Word document (*.docx)"
        return "Word", ".docx", "Word document (*.docx);;Text file (*.txt)"

    def save(self) -> None:
        name, suffix, filt = self._save_format()
        stem = self.source_path.stem if self.source_path else "Restored reply"
        folder = self.source_path.parent if self.source_path else Path.home()
        path, _ = QFileDialog.getSaveFileName(self, f"Save as {name} File", str(folder / f"{stem} (restored){suffix}"),
                                              filt)
        if not path:
            return
        try:
            if self.grid and Path(path).suffix.lower() in documents.TABLE_TYPES:
                documents.save_table(Path(path), self.grid[0], self.grid[1:])
            elif path.lower().endswith(".docx"):
                documents.save_text_docx(Path(path), self.result.toPlainText())
            else:
                Path(path).write_text(self.result.toPlainText(), encoding="utf-8")
            self.status.setText(f"Saved {Path(path).name}")
        except OSError as exc:
            QMessageBox.warning(self, "Could Not Save", str(exc))

    def clear(self) -> None:
        self.sessions.clear()
        self.reply.clear()
        self.source_path, self.grid = None, None
        self.result.clear()
        self.status.setText("")
