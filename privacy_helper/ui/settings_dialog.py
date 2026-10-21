"""Settings: what to hide, auto-lock, where files are saved, password and backup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.masking import KINDS, PATTERN_KINDS
from ..core.vault import Vault, VaultError, WrongPassword
from .common import hint

PLURAL = {"PLACE": "Addresses and locations", "ID": "ID numbers", "ACCOUNT": "Bank accounts",
          "CARD": "Payment cards", "VEHICLE": "Vehicle plates", "ONLINE": "Links, handles and IP addresses",
          "SENSITIVE": "Protected topics"}


class SettingsDialog(QDialog):
    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        s = vault.settings
        self.setWindowTitle("Settings")
        self.resize(560, 520)
        tabs = QTabWidget()

        # Hiding
        hiding = QWidget()
        form = QVBoxLayout(hiding)
        form.addWidget(QLabel("<b>Always hide these words</b>"))
        form.addWidget(hint("One per line. For example your partner organisations, local place names or "
                            "project code names."))
        self.always = QPlainTextEdit("\n".join(s.always_hide))
        form.addWidget(self.always)
        form.addWidget(QLabel("<b>Never hide these words</b>"))
        form.addWidget(hint("One per line. For example your own organisation's name."))
        self.never = QPlainTextEdit("\n".join(s.never_hide))
        form.addWidget(self.never)
        form.addWidget(QLabel("<b>Look for</b>"))
        self.pattern_boxes = {}
        grid = QGridLayout()
        for i, kind in enumerate(PATTERN_KINDS):
            box = QCheckBox(PLURAL.get(kind, KINDS[kind] + "s"))
            box.setChecked(kind not in s.off_patterns)
            self.pattern_boxes[kind] = box
            grid.addWidget(box, i // 3, i % 3)
        form.addLayout(grid)
        self.suggest = QCheckBox("Suggest possible names (Mr, Mrs, Mallam, Alhaji, Hajiya and similar)")
        self.suggest.setChecked(s.suggest_names)
        form.addWidget(self.suggest)
        tabs.addTab(hiding, "Hiding")

        # Files
        files = QWidget()
        flay = QVBoxLayout(files)
        flay.addWidget(QLabel("<b>Save protected and opened files</b>"))
        self.next_to = QRadioButton("Next to the original file")
        self.in_folder = QRadioButton("In this folder:")
        self.folder = QLineEdit(s.output_folder)
        self.folder.setReadOnly(True)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self.choose_folder)
        (self.in_folder if s.output_folder else self.next_to).setChecked(True)
        flay.addWidget(self.next_to)
        frow = QHBoxLayout()
        frow.addWidget(self.in_folder)
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)
        flay.addLayout(frow)
        flay.addStretch(1)
        tabs.addTab(files, "Files")

        # Security
        security = QWidget()
        slay = QVBoxLayout(security)
        lock_form = QFormLayout()
        self.lock_minutes = QSpinBox()
        self.lock_minutes.setRange(1, 240)
        self.lock_minutes.setSuffix(" minutes")
        self.lock_minutes.setValue(s.lock_minutes)
        lock_form.addRow("Lock after no activity for", self.lock_minutes)
        slay.addLayout(lock_form)
        slay.addWidget(hint("Locking clears any open text from the screen."))
        slay.addSpacing(12)
        slay.addWidget(QLabel("<b>Master password</b>"))
        change = QPushButton("Change Master Password…")
        change.clicked.connect(self.change_password)
        slay.addWidget(change)
        slay.addSpacing(12)
        slay.addWidget(QLabel("<b>Backup</b>"))
        slay.addWidget(hint("A backup holds every key, still locked by your master password. Keep one on a USB "
                            "drive or another safe place. Without it, a broken computer means lost files."))
        brow = QHBoxLayout()
        backup = QPushButton("Back Up Keys…")
        restore = QPushButton("Restore from Backup…")
        backup.clicked.connect(self.backup)
        restore.clicked.connect(self.restore)
        brow.addWidget(backup)
        brow.addWidget(restore)
        brow.addStretch(1)
        slay.addLayout(brow)
        slay.addStretch(1)
        tabs.addTab(security, "Security")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Folder", self.folder.text() or str(Path.home()))
        if folder:
            self.folder.setText(folder)
            self.in_folder.setChecked(True)

    def accept(self) -> None:
        s = self.vault.settings

        def lines(edit: QPlainTextEdit) -> list[str]:
            return [w.strip() for w in edit.toPlainText().splitlines() if w.strip()]
        s.always_hide, s.never_hide = lines(self.always), lines(self.never)
        s.off_patterns = [k for k, box in self.pattern_boxes.items() if not box.isChecked()]
        s.suggest_names = self.suggest.isChecked()
        s.lock_minutes = self.lock_minutes.value()
        s.output_folder = self.folder.text() if self.in_folder.isChecked() else ""
        self.vault.save()
        super().accept()

    def change_password(self) -> None:
        old, ok = QInputDialog.getText(self, "Change Master Password", "Current password:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Change Master Password", "New password (at least 10 characters):",
                                       QLineEdit.EchoMode.Password)
        if not ok:
            return
        again, ok = QInputDialog.getText(self, "Change Master Password", "Repeat the new password:",
                                         QLineEdit.EchoMode.Password)
        if not ok:
            return
        if new != again:
            QMessageBox.warning(self, "Password Not Changed", "The two new passwords are different.")
            return
        try:
            self.vault.change_password(old, new)
        except (WrongPassword, VaultError) as exc:
            QMessageBox.warning(self, "Password Not Changed", str(exc))
            return
        QMessageBox.information(self, "Password Changed",
                                "Your master password was changed. Older backups still use the old password.")

    def backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Back Up Keys", str(Path.home() / "NGO Privacy Helper keys.backup"),
                                              "Key backup (*.backup)")
        if path:
            try:
                self.vault.backup_to(Path(path))
            except OSError as exc:
                QMessageBox.warning(self, "Backup Failed", str(exc))
                return
            QMessageBox.information(self, "Backup Saved", f"Your keys were backed up to {Path(path).name}.")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore from Backup", "", "Key backup (*.backup);;All files (*)")
        if not path:
            return
        password, ok = QInputDialog.getText(self, "Restore from Backup", "Master password used for that backup:",
                                            QLineEdit.EchoMode.Password)
        if not ok:
            return
        answer = QMessageBox.warning(self, "Replace Your Keys?",
                                     "Restoring replaces the keys on this computer with the keys in the backup. "
                                     "Keys made since the backup will be lost unless they are also in it.",
                                     QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                                     QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Ok:
            return
        try:
            self.vault.restore_from(Path(path), password)
        except (WrongPassword, VaultError, OSError) as exc:
            QMessageBox.warning(self, "Restore Failed", str(exc))
            return
        QMessageBox.information(self, "Keys Restored",
                                "Your keys were restored. From now on, use the master password of the backup.")
        self.reject()   # the settings shown were from before the restore
