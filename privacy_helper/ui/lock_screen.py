"""First run: create a master password. Every run: unlock with it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..core.vault import MIN_PASSWORD, Vault, VaultError, WrongPassword
from .common import APP_NAME, error_label, hint, primary


def _eye_icon(color, crossed: bool) -> QIcon:
    """An eye, or a crossed-out eye. Drawn here because Qt has no eye icon on Windows or macOS."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(color, 4.5))
    eye = QPainterPath(QPointF(6, 32))
    eye.quadTo(32, 6, 58, 32)
    eye.quadTo(32, 58, 6, 32)
    p.drawPath(eye)
    p.drawEllipse(QRectF(23, 23, 18, 18))
    if crossed:
        p.drawLine(QPointF(12, 54), QPointF(52, 10))
    p.end()
    return QIcon(pm)


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
        color = self.palette().color(QPalette.ColorRole.PlaceholderText)
        self._eyes = (_eye_icon(color, False), _eye_icon(color, True))
        self.show_action = QAction(self._eyes[0], "Show password", self)
        self.show_action.setCheckable(True)
        self.show_action.toggled.connect(self._show_password)
        self.password.addAction(self.show_action, QLineEdit.ActionPosition.TrailingPosition)
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
        self.warning = QLabel(
            "<b>Save this password somewhere safe before you continue.</b> Use a password manager, or write it "
            "down and keep it locked away. It cannot be reset or recovered: the app works fully offline, so there "
            "is no account, email or helpdesk that can get it back. If it is lost, every file and text it protects "
            "can never be opened again. You can change it later in Settings, but only by entering this one.")
        self.warning.setTextFormat(Qt.TextFormat.RichText)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("border: 1px solid palette(mid); border-radius: 6px; padding: 8px;")

        lay.addWidget(self.title)
        lay.addWidget(self.body)
        lay.addSpacing(6)
        lay.addLayout(form)
        lay.addWidget(self.warning)
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
        self.warning.setVisible(first)
        self.button.setText("Create Password" if first else "Unlock")
        self.note.setText(
            f"Use at least {MIN_PASSWORD} characters. A short sentence is easy to remember and hard to guess."
            if first else message)
        self.show_action.setChecked(False)
        self.password.clear()
        self.confirm.clear()
        self.error.clear()
        self.password.setFocus()

    def _show_password(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.password.setEchoMode(mode)
        self.confirm.setEchoMode(mode)
        self.show_action.setIcon(self._eyes[shown])
        self.show_action.setText("Hide password" if shown else "Show password")

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
        self.show_action.setChecked(False)
        self.password.clear()
        self.confirm.clear()
        self.unlocked.emit()
