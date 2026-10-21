"""First run: create a master password. Every run: unlock with it."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..core.vault import MIN_PASSWORD, Vault, VaultError, WrongPassword
from .common import APP_NAME, error_label, hint, primary


class LockScreen(QWidget):
    unlocked = Signal()

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card = QWidget()
        card.setFixedWidth(440)
        lay = QVBoxLayout(card)
        lay.setSpacing(10)

        self.title = QLabel()
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(f)
        self.body = hint("")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("Master password")
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setAccessibleName("Repeat master password")
        form = QVBoxLayout()
        form.setSpacing(4)
        form.addWidget(QLabel("Master password"))
        form.addWidget(self.password)
        form.addSpacing(6)
        self.confirm_label = QLabel("Repeat password")
        form.addWidget(self.confirm_label)
        form.addWidget(self.confirm)
        self.error = error_label()
        self.button = primary(QPushButton())
        self.note = hint("")

        lay.addWidget(self.title)
        lay.addWidget(self.body)
        lay.addSpacing(6)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignRight)
        lay.addSpacing(10)
        lay.addWidget(self.note)
        outer.addWidget(card)

        self.button.clicked.connect(self.submit)
        self.password.returnPressed.connect(self.submit)
        self.confirm.returnPressed.connect(self.submit)
        self.reset()

    def reset(self, message: str = "") -> None:
        first = not self.vault.exists()
        self.title.setText(f"Welcome to {APP_NAME}" if first else "Unlock")
        self.body.setText(
            "Create a master password. It locks the keys for every file you protect and every text you hide."
            if first else "Enter your master password to open your keys.")
        self.confirm.setVisible(first)
        self.confirm_label.setVisible(first)
        self.button.setText("Create Password" if first else "Unlock")
        self.note.setText(
            f"Use at least {MIN_PASSWORD} characters. A short sentence is easy to remember and hard to guess. "
            "Write it down and keep it somewhere safe: if it is lost, protected files cannot be opened."
            if first else message)
        self.password.clear()
        self.confirm.clear()
        self.error.clear()
        self.password.setFocus()

    def submit(self) -> None:
        password = self.password.text()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if not self.vault.exists():
                if password != self.confirm.text():
                    self.error.setText("The two passwords are different.")
                    return
                self.vault.create(password)
            else:
                self.vault.unlock(password)
        except (WrongPassword, VaultError) as exc:
            self.error.setText(str(exc))
            self.password.selectAll()
            self.password.setFocus()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.password.clear()
        self.confirm.clear()
        self.unlocked.emit()
