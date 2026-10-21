"""Restore: paste the AI's reply and put the real details back."""

from __future__ import annotations

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
from .common import SECRET_CLEAR_SECONDS, copy_secret, hint, page_header, primary
from .hide_page import DropTextEdit


class RestorePage(QWidget):
    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(page_header("Restore details",
                                  "Paste the AI's reply. The real names and details are filled back in on this "
                                  "computer only."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Text it came from:"))
        self.sessions = QComboBox()
        self.sessions.setMinimumContentsLength(40)
        self.sessions.setAccessibleName("Text it came from")
        row.addWidget(self.sessions, 1)
        lay.addLayout(row)

        split = QSplitter(Qt.Orientation.Vertical)
        self.reply = DropTextEdit()
        self.reply.setPlaceholderText("Paste the AI's reply here, or drop a .txt or .docx file.")
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

    def load_file(self, paths: list[Path]) -> None:
        try:
            self.reply.setPlainText(documents.load_any_text(paths[0]))
        except documents.FileReadError as exc:
            QMessageBox.warning(self, "Could Not Open File", str(exc))

    def do_restore(self) -> None:
        entry = self.vault.get(self.sessions.currentData())
        if not entry:
            return
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

    def save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Restored Text", str(Path.home() / "Restored reply.docx"),
                                              "Word document (*.docx);;Text file (*.txt)")
        if not path:
            return
        try:
            if path.lower().endswith(".docx"):
                documents.save_text_docx(Path(path), self.result.toPlainText())
            else:
                Path(path).write_text(self.result.toPlainText(), encoding="utf-8")
            self.status.setText(f"Saved {Path(path).name}")
        except OSError as exc:
            QMessageBox.warning(self, "Could Not Save", str(exc))

    def clear(self) -> None:
        self.sessions.clear()
        self.reply.clear()
        self.result.clear()
        self.status.setText("")
