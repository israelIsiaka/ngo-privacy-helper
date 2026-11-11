"""Settings: what to hide, auto-lock, where files are saved, password and backup."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
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

from .. import hotkeys
from ..core.masking import KINDS, PATTERN_KINDS
from ..core.vault import Vault, VaultError, WrongPassword
from .common import hint

PLURAL = {"PLACE": "Addresses and locations", "ID": "ID numbers", "ACCOUNT": "Bank accounts",
          "CARD": "Payment cards", "VEHICLE": "Vehicle plates", "ONLINE": "Links, handles and IP addresses",
          "SENSITIVE": "Protected topics", "DESCRIPTION": "Descriptions that point to one person"}


class SettingsDialog(QDialog):
    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        s = vault.settings
        self.setWindowTitle("Settings")
        self.resize(560, 640)
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
        slay.addWidget(QLabel("<b>Delete keys automatically</b>"))
        keep_form = QFormLayout()
        self.mask_days, self.file_days = QSpinBox(), QSpinBox()
        for box, value in ((self.mask_days, s.mask_days), (self.file_days, s.file_days)):
            box.setRange(0, 3650)
            box.setSuffix(" days")
            box.setSpecialValueText("Never")
            box.setValue(value)
        keep_form.addRow("Hidden-details records after", self.mask_days)
        keep_form.addRow("File keys and PDF passwords after", self.file_days)
        slay.addLayout(keep_form)
        slay.addWidget(hint("Once a hidden-details record is destroyed, the AI's replies can no longer be filled "
                            "in, so the people in them stay hidden for good. Once a file key is destroyed, that file "
                            "can never be opened again. Applies to new keys; set a date for older ones in Keys. "
                            "Backups made before the date still hold the keys."))
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

        self.shortcuts = ShortcutsForm(hotkeys.saved())
        if hotkeys.Hotkeys.supported_here():
            tabs.addTab(self.shortcuts, "Shortcuts")

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
        problem = self.shortcuts.problem()
        if problem:
            QMessageBox.warning(self, "Choose Another Shortcut", problem)
            return
        hotkeys.save(self.shortcuts.chosen())
        s = self.vault.settings

        def lines(edit: QPlainTextEdit) -> list[str]:
            return [w.strip() for w in edit.toPlainText().splitlines() if w.strip()]
        s.always_hide, s.never_hide = lines(self.always), lines(self.never)
        s.off_patterns = [k for k, box in self.pattern_boxes.items() if not box.isChecked()]
        s.suggest_names = self.suggest.isChecked()
        s.lock_minutes = self.lock_minutes.value()
        s.mask_days, s.file_days = self.mask_days.value(), self.file_days.value()
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


class ShortcutsForm(QWidget):
    """Pick the keys that hide or restore copied text from any app."""

    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(hint("Copy text in any app, such as Word, email or a browser, then press a shortcut. A small "
                           "window shows what will be hidden and copies the safe version for you to paste into your "
                           "AI tool. Copy the AI's reply and press the other shortcut to fill the real details back "
                           "in. The app never reads what you type or what is on your screen."))
        form = QFormLayout()
        self.edits = {}
        for action, title in (("hide", "Hide copied text"), ("restore", "Restore copied text")):
            edit = QKeySequenceEdit(current.get(action, QKeySequence()))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            edit.setAccessibleName(title)
            self.edits[action] = edit
            form.addRow(title, edit)
        lay.addLayout(form)
        mods = "Command, Control, Option or Shift" if sys.platform == "darwin" else "Ctrl, Alt or Shift"
        lay.addWidget(hint(f"Click a box and press the keys you want. Use at least two of {mods} with a letter, so "
                           "the shortcut does not take keys from other apps. Clear a box to turn that shortcut off."))
        lay.addStretch(1)

    def chosen(self) -> dict:
        return {a: e.keySequence() for a, e in self.edits.items()}

    def problem(self) -> str:
        """Why the choice cannot be used, or an empty string."""
        seqs = [s for s in self.chosen().values() if not s.isEmpty()]
        for seq in seqs:
            try:
                hotkeys.check(seq)
            except hotkeys.ShortcutError as exc:
                return f"{hotkeys.label(seq)}: {exc}"
        if len(seqs) == 2 and seqs[0] == seqs[1]:
            return "Choose two different shortcuts."
        return ""


class ShortcutsDialog(QDialog):
    """Offered once, after the master password is created."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shortcuts for Other Apps")
        self.form = ShortcutsForm({a: QKeySequence(k) for a, k in hotkeys.DEFAULTS.items()})
        buttons = QDialogButtonBox()
        buttons.addButton("Turn On Shortcuts", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Not Now", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Hide details without opening the app</b>"))
        lay.addWidget(self.form)
        lay.addWidget(hint("You can change or turn these off later in Settings."))
        lay.addWidget(buttons)
        lay.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        self.form.setFixedWidth(500)   # a fixed width lets the wrapped text work out its height

    def accept(self) -> None:
        problem = self.form.problem()
        if problem:
            QMessageBox.warning(self, "Choose Another Shortcut", problem)
            return
        hotkeys.save(self.form.chosen())
        super().accept()

    def reject(self) -> None:
        hotkeys.save({})   # remembered, so the offer is not repeated
        super().reject()
