"""Keys: every file key, PDF password and hidden-details record, searchable by name."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core import filecrypt
from ..core.vault import KIND_FILE, KIND_MASK, KIND_PDF, Vault
from .common import FILE_MANAGER, SECRET_CLEAR_SECONDS, copy_secret, hint, page_header, reveal

TYPE_LABEL = {KIND_FILE: "Encrypted file", KIND_PDF: "Locked PDF", KIND_MASK: "Hidden details"}
KEY_FILTER = "NGO Privacy Helper key (*.nphkey);;All files (*)"


class KeysPage(QWidget):
    keys_changed = Signal()

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(page_header("Keys",
                                  "Every protected file has its own key, listed here by file name. Keys stay on "
                                  "this computer, locked by your master password."))

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search keys")
        import_btn = QPushButton("Import Key…")
        import_btn.clicked.connect(self.import_key)
        top.addWidget(self.search, 1)
        top.addWidget(import_btn)
        lay.addLayout(top)

        self.model = QStandardItemModel(0, 4)
        self.model.setHorizontalHeaderLabels(["Name", "Type", "Created", "Saved as"])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole + 1)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self.view.verticalHeader().hide()
        self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        head = self.view.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.view, 1)
        self.empty = hint("No keys yet. Protect a file and its key will appear here.")
        lay.addWidget(self.empty)

        foot = QHBoxLayout()
        self.status = hint("")
        self.copy_btn = QPushButton("Copy Key")
        self.export_btn = QPushButton("Export Key…")
        self.show_btn = QPushButton(f"Show in {FILE_MANAGER}")
        self.delete_btn = QPushButton("Delete…")
        foot.addWidget(self.status, 1)
        for b in (self.delete_btn, self.show_btn, self.export_btn, self.copy_btn):
            foot.addWidget(b)
        lay.addLayout(foot)

        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.view.selectionModel().selectionChanged.connect(self._update_buttons)
        self.view.doubleClicked.connect(self.show_file)
        self.copy_btn.clicked.connect(self.copy_key)
        self.export_btn.clicked.connect(self.export_key)
        self.show_btn.clicked.connect(self.show_file)
        self.delete_btn.clicked.connect(self.delete)
        self._update_buttons()

    def reload(self) -> None:
        selected = self._entry()
        self.model.setRowCount(0)
        for e in self.vault.entries:
            created = datetime.fromisoformat(e.created)
            cells = [e.label, TYPE_LABEL.get(e.kind, e.kind), created.strftime("%d %b %Y, %H:%M"),
                     Path(e.output).name if e.output else ("" if e.kind == KIND_MASK else "Not saved")]
            items = [QStandardItem(c) for c in cells]
            for item, sort in zip(items, [e.label.casefold(), cells[1], e.created, cells[3]], strict=True):
                item.setData(sort, Qt.ItemDataRole.UserRole + 1)
            items[0].setData(e.id, Qt.ItemDataRole.UserRole)
            if e.output:
                items[3].setToolTip(e.output)
            self.model.appendRow(items)
        self.empty.setVisible(not self.vault.entries)
        if selected:
            self.select(selected.id)
        self._update_buttons()

    def clear(self) -> None:
        self.model.setRowCount(0)
        self.search.clear()
        self.status.setText("")

    def select(self, entry_id: str) -> None:
        for row in range(self.proxy.rowCount()):
            if self.proxy.index(row, 0).data(Qt.ItemDataRole.UserRole) == entry_id:
                self.view.selectRow(row)
                return

    def _entry(self):
        rows = self.view.selectionModel().selectedRows() if self.view.selectionModel() else []
        return self.vault.get(rows[0].data(Qt.ItemDataRole.UserRole)) if rows else None

    def _update_buttons(self) -> None:
        e = self._entry()
        is_key = bool(e and e.kind in (KIND_FILE, KIND_PDF))
        self.copy_btn.setEnabled(is_key)
        self.copy_btn.setText("Copy Password" if e and e.kind == KIND_PDF else "Copy Key")
        self.export_btn.setEnabled(bool(e and e.kind == KIND_FILE))
        self.show_btn.setEnabled(bool(e and e.output and Path(e.output).exists()))
        self.delete_btn.setEnabled(e is not None)

    def _key_text(self, e) -> str:
        return e.secret if e.kind == KIND_PDF else filecrypt.export_key(e.id, base64.b64decode(e.secret))

    def copy_key(self) -> None:
        e = self._entry()
        if e:
            copy_secret(self._key_text(e))
            self.status.setText(f"Copied for {SECRET_CLEAR_SECONDS} seconds. Send it separately from the file, "
                                "for example by phone or SMS.")

    def export_key(self) -> None:
        e = self._entry()
        if not e:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Key", str(Path.home() / f"{e.label}.nphkey"), KEY_FILTER)
        if not path:
            return
        try:
            Path(path).write_text(self._key_text(e) + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could Not Export Key", str(exc))
            return
        self.status.setText(f"Exported. Anyone with {Path(path).name} can open {e.label}. Keep it safe.")

    def import_key(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Import Key")
        box.setText("Import a key you were given?")
        box.setInformativeText("Choose a .nphkey file, or paste a key that starts with NPHKEY1.")
        from_file = box.addButton("Choose File…", QMessageBox.ButtonRole.AcceptRole)
        paste = box.addButton("Paste Key…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is from_file:
            path, _ = QFileDialog.getOpenFileName(self, "Import Key", "", KEY_FILTER)
            if not path:
                return
            try:
                text, label = Path(path).read_text(encoding="utf-8"), Path(path).stem
            except (OSError, UnicodeDecodeError) as exc:
                QMessageBox.warning(self, "Could Not Read Key", str(exc))
                return
        elif box.clickedButton() is paste:
            text, ok = QInputDialog.getText(self, "Paste Key", "Key:")
            if not ok:
                return
            label, ok = QInputDialog.getText(self, "Name This Key", "Which file is this key for?")
            if not ok:
                return
            label = label.strip() or "Imported key"
        else:
            return
        try:
            key_id, key = filecrypt.parse_key(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Not a Valid Key", str(exc))
            return
        if self.vault.get(key_id):
            self.status.setText("This key is already saved.")
            self.select(key_id)
            return
        self.vault.add(KIND_FILE, label, entry_id=key_id, secret=base64.b64encode(key).decode())
        self.keys_changed.emit()
        self.select(key_id)
        self.status.setText(f"Key for {label} imported.")

    def show_file(self) -> None:
        e = self._entry()
        if e and e.output and Path(e.output).exists():
            reveal(Path(e.output))

    def delete(self) -> None:
        e = self._entry()
        if not e:
            return
        consequence = {
            KIND_FILE: f"{e.label} cannot be opened without this key unless you exported a copy.",
            KIND_PDF: f"You will no longer have the password for {e.label}.",
            KIND_MASK: "Replies that use these codes can no longer be restored.",
        }[e.kind]
        answer = QMessageBox.warning(self, "Delete Key", f"Delete the key for {e.label}?\n\n{consequence}",
                                     QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard,
                                     QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Discard:
            self.vault.remove(e.id)
            self.keys_changed.emit()
            self.status.setText(f"Deleted the key for {e.label}.")
