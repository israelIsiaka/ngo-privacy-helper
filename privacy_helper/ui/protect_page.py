"""Protect files: drop files to encrypt them, lock PDFs, or open protected files.

Every file gets its own key, saved in the vault under the file's name.
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import filecrypt, pdflock
from ..core.vault import KIND_FILE, KIND_PDF, Vault
from .common import FILE_MANAGER, SECRET_CLEAR_SECONDS, DropZone, Job, copy_secret, hint, page_header, reveal, run_job


class ProtectPage(QWidget):
    keys_changed = Signal()

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.queue: list[Path] = []
        self.busy = False
        self.rows: dict[int, dict] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(page_header("Protect files",
                                  "Encrypt any file, lock PDFs with a password, or open files you protected. "
                                  "Each file gets its own key, kept in Keys under the file's name."))

        self.zone = DropZone("Drop files here",
                             "Files are copied, never changed. Encrypted files end in .nph.")
        choose = QPushButton("Choose Files…")
        choose.clicked.connect(self.choose)
        self.zone.button_row.addWidget(choose)
        self.zone.dropped.connect(self.add_files)
        lay.addWidget(self.zone)

        pdf_row = QHBoxLayout()
        pdf_row.addWidget(QLabel("PDF files:"))
        self.pdf_lock = QRadioButton("Lock with a password (opens in any PDF reader)")
        self.pdf_encrypt = QRadioButton("Encrypt (opens only with this app)")
        self.pdf_lock.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.pdf_lock)
        group.addButton(self.pdf_encrypt)
        pdf_row.addWidget(self.pdf_lock)
        pdf_row.addWidget(self.pdf_encrypt)
        pdf_row.addStretch(1)
        lay.addLayout(pdf_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Result", "Saved as"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.show_selected)
        lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.status = hint("")
        self.show_btn = QPushButton(f"Show in {FILE_MANAGER}")
        self.copy_btn = QPushButton("Copy Key")
        self.show_btn.clicked.connect(self.show_selected)
        self.copy_btn.clicked.connect(self.copy_selected)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        foot.addWidget(self.progress)
        foot.addWidget(self.status, 1)
        foot.addWidget(self.copy_btn)
        foot.addWidget(self.show_btn)
        lay.addLayout(foot)
        self._update_buttons()

    # ---- queue ---------------------------------------------------------------
    def choose(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose Files to Protect or Open")
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        skipped = [p.name for p in paths if not p.is_file()]
        self.queue += [p for p in paths if p.is_file()]
        if skipped:
            self.status.setText("Folders are not supported. Drop the files inside instead: " + ", ".join(skipped))
        self._next()

    def _next(self) -> None:
        if self.busy or not self.queue:
            if not self.busy:
                self.progress.hide()
            return
        path = self.queue.pop(0)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(path.name))
        self.table.setItem(row, 1, QTableWidgetItem("Working…"))
        self.table.setItem(row, 2, QTableWidgetItem(""))
        self.rows[row] = {"source": path}
        try:
            self._start(row, path)
        except _Skip as exc:
            self._finish(row, None, str(exc))

    def _out_dir(self, path: Path) -> Path:
        folder = self.vault.settings.output_folder
        return Path(folder) if folder and Path(folder).is_dir() else path.parent

    def _start(self, row: int, path: Path) -> None:
        out_dir = self._out_dir(path)
        if path.suffix.lower() == filecrypt.SUFFIX:
            if not _readable(path):
                raise _Skip("Not a file encrypted by Encryptra.")
            key_id = filecrypt.read_key_id(path)
            entry = self.vault.get(key_id)
            key = base64.b64decode(entry.secret) if entry else self._ask_for_key(row, path, key_id)
            self._run(row, "Opened", lambda p: filecrypt.decrypt_file(path, out_dir, key, p))
            return

        if path.suffix.lower() == ".pdf":
            try:
                locked = pdflock.is_locked(path)
            except pdflock.PdfError as exc:
                raise _Skip(str(exc)) from None
            if locked:
                passwords = self.vault.find_pdf_password(path)
                self._run(row, "Unlocked", lambda p: self._unlock_pdf(path, out_dir, passwords))
                return
            if self.pdf_lock.isChecked():
                password = pdflock.new_password()
                entry = self.vault.add(KIND_PDF, path.name, secret=password, source=str(path))
                self.rows[row]["entry"] = entry.id
                self._run(row, "Locked with a password", lambda p: pdflock.lock_pdf(path, out_dir, password))
                return

        key = filecrypt.new_key()
        # The key is saved before the file is written, so an encrypted file can never exist without its key.
        entry = self.vault.add(KIND_FILE, path.name, secret=base64.b64encode(key).decode(), source=str(path))
        self.rows[row]["entry"] = entry.id
        self._run(row, "Encrypted", lambda p: filecrypt.encrypt_file(path, out_dir, entry.id, key, p))

    def _unlock_pdf(self, path: Path, out_dir: Path, passwords: list[str]) -> Path:
        try:
            return pdflock.unlock_pdf(path, out_dir, passwords)
        except pdflock.PdfError:
            raise _NeedPassword() from None

    def _ask_for_key(self, row: int, path: Path, key_id: str) -> bytes:
        text, ok = QInputDialog.getText(
            self, "Key Needed",
            f"No key for {path.name} is saved on this computer.\n"
            "Paste the key you were given. It starts with NPHKEY1.", QLineEdit.EchoMode.Normal)
        if not ok or not text.strip():
            raise _Skip("Skipped: no key.")
        try:
            got_id, key = filecrypt.parse_key(text)
        except ValueError as exc:
            raise _Skip(str(exc)) from None
        if got_id != key_id:
            raise _Skip("That key belongs to a different file.")
        self.rows[row]["import"] = key   # saved to Keys only once it has opened the file
        return key

    def _run(self, row: int, verb: str, work) -> None:
        self.busy = True
        self.progress.setValue(0)
        self.progress.show()
        job = Job(work)
        job.signals.progress.connect(self.progress.setValue)
        job.signals.done.connect(lambda out: self._finish(row, out, verb))
        job.signals.failed.connect(lambda msg: self._failed(row, msg))
        run_job(job)

    def _failed(self, row: int, message: str) -> None:
        entry_id = self.rows[row].get("entry")
        if entry_id:   # nothing was written, so the unused key is removed
            self.vault.remove(entry_id)
        if message == _NeedPassword.MESSAGE:
            self._retry_pdf_with_typed_password(row)
            return
        self._finish(row, None, f"Failed: {message}")

    def _retry_pdf_with_typed_password(self, row: int) -> None:
        path = self.rows[row]["source"]
        password, ok = QInputDialog.getText(self, "Password Needed",
                                            f"Enter the password for {path.name}.", QLineEdit.EchoMode.Password)
        if not ok or not password:
            self._finish(row, None, "Skipped: no password.")
            return
        self._run(row, "Unlocked", lambda p: pdflock.unlock_pdf(path, self._out_dir(path), [password]))

    def _finish(self, row: int, out: Path | None, message: str) -> None:
        self.busy = False
        self.table.item(row, 1).setText(message)
        if out is not None:
            imported = self.rows[row].pop("import", None)
            if imported:
                src = self.rows[row]["source"]
                self.vault.add(KIND_FILE, src.name.removesuffix(filecrypt.SUFFIX), entry_id=filecrypt.read_key_id(src),
                               secret=base64.b64encode(imported).decode(), output=str(src))
            self.rows[row]["output"] = Path(out)
            self.table.item(row, 2).setText(Path(out).name)
            entry = self.vault.get(self.rows[row].get("entry", ""))
            if entry:
                entry.output = str(out)
                self.vault.save()
            self.keys_changed.emit()
        self.table.selectRow(row)
        self._update_buttons()
        self._next()

    # ---- row actions ---------------------------------------------------------
    def _selected(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        return self.rows.get(rows[0].row()) if rows else None

    def _update_buttons(self) -> None:
        info = self._selected() or {}
        self.show_btn.setEnabled("output" in info)
        self.copy_btn.setEnabled(bool(info.get("entry")) and "output" in info)
        entry = self.vault.get(info.get("entry", "")) if info.get("entry") else None
        self.copy_btn.setText("Copy Password" if entry and entry.kind == KIND_PDF else "Copy Key")

    def show_selected(self) -> None:
        info = self._selected()
        if info and "output" in info:
            reveal(info["output"])

    def copy_selected(self) -> None:
        info = self._selected()
        entry = self.vault.get(info.get("entry", "")) if info else None
        if not entry:
            return
        if entry.kind == KIND_PDF:
            text = entry.secret
        else:
            text = filecrypt.export_key(entry.id, base64.b64decode(entry.secret))
        copy_secret(text)
        self.status.setText(f"Copied for {SECRET_CLEAR_SECONDS} seconds. Send it separately from the file, "
                            "for example by phone or SMS.")

    def clear(self) -> None:
        self.queue.clear()
        self.table.setRowCount(0)
        self.rows.clear()
        self.status.setText("")


def _readable(path: Path) -> bool:
    try:
        filecrypt.read_key_id(path)
        return True
    except (filecrypt.DecryptError, OSError):
        return False


class _Skip(Exception):
    pass


class _NeedPassword(Exception):
    MESSAGE = "A password is needed."

    def __str__(self) -> str:
        return self.MESSAGE
