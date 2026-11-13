"""The small window a keyboard shortcut opens over any app: hide or restore the copied text."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.masking import KINDS, Session, _norm, apply, restore
from ..core.vault import KIND_MASK, Vault, VaultError, WrongPassword
from .common import SECRET_CLEAR_SECONDS, copy_secret, error_label, hint, primary
from .hide_page import MAX_OPEN_MB, settings_detector

HIDE, RESTORE = "hide", "restore"


def best_entry(text: str, entries) -> tuple[object | None, int]:
    """The hidden-details record whose codes fill in the most of text; the newest wins a tie."""
    best, best_n = None, 0
    for e in sorted(entries, key=lambda e: e.created, reverse=True):
        n = restore(text, e.mapping)[1]
        if n > best_n:
            best, best_n = e, n
    return best, best_n


class QuickPopup(QWidget):
    unlocked = Signal()
    saved = Signal()

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.vault = vault
        self.mode = HIDE
        self.masked = False
        self.text = ""
        self.detections = []
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        self.closer = QTimer(self, singleShot=True, interval=1500, timeout=self.close)

        # Locked: ask for the master password first.
        locked = QWidget()
        ll = QVBoxLayout(locked)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(hint("The app is locked. Enter your master password to continue."))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("Master password")
        self.password.returnPressed.connect(self.unlock)
        self.lock_error = error_label()
        unlock = primary(QPushButton("Unlock"))
        unlock.clicked.connect(self.unlock)
        ll.addWidget(self.password)
        ll.addWidget(self.lock_error)
        ll.addWidget(unlock, 0, Qt.AlignmentFlag.AlignRight)

        # Unlocked: what was found, the result, and one button.
        work = QWidget()
        wl = QVBoxLayout(work)
        wl.setContentsMargins(0, 0, 0, 0)
        self.status = hint("")
        self.found = QListWidget()
        self.found.setAccessibleName("Details found")
        self.found.setMaximumHeight(130)
        self.found.itemChanged.connect(self._toggled)
        self.sessions = QComboBox()
        self.sessions.setAccessibleName("Text it came from")
        self.sessions.currentIndexChanged.connect(self._show_restore)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(140)
        self.result.setAccessibleName("Result")
        row = QHBoxLayout()
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self.close)
        self.copy_btn = primary(QPushButton())
        self.copy_btn.clicked.connect(self.copy)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.copy_btn)
        self.found_label = QLabel("Details found. Untick anything that is safe to share.")
        self.from_label = QLabel("Text it came from:")
        for w in (self.status, self.found_label, self.found, self.from_label, self.sessions, self.result):
            wl.addWidget(w)
        wl.addLayout(row)

        # Shown one at a time, and not in a stacked widget, so the window is only as tall as what it shows.
        self.locked_box, self.work_box = locked, work
        for box in (locked, work):
            box.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        lay.addWidget(locked)
        lay.addWidget(work)

    # ---- opening ----------------------------------------------------------------
    def start(self, mode: str) -> None:
        """Called by the shortcut: read the clipboard and show the pop-up by the mouse pointer."""
        self.closer.stop()
        self.mode = mode
        self.text = QGuiApplication.clipboard().text()
        self.setWindowTitle("Hide Details" if mode == HIDE else "Restore Details")
        if self.vault.unlocked:
            self._show_work()
        else:
            self.password.clear()
            self.lock_error.clear()
            self.work_box.hide()
            self.locked_box.show()
            self.password.setFocus()
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()

    def _place(self) -> None:
        pos = QCursor.pos() + QPoint(12, 12)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x(), area.left()), area.right() - self.width())
        y = min(max(pos.y(), area.top()), area.bottom() - self.height())
        self.move(x, y)

    def unlock(self) -> None:
        if not self.vault.exists():
            self.lock_error.setText("Open Encryptra to set it up first.")
            return
        try:
            self.vault.unlock(self.password.text())
        except (WrongPassword, VaultError) as exc:
            self.lock_error.setText(str(exc))
            self.password.selectAll()
            return
        self.password.clear()
        self.unlocked.emit()
        self._show_work()
        self.adjustSize()

    def _show_work(self) -> None:
        self.locked_box.hide()
        self.work_box.show()
        hide = self.mode == HIDE
        for w in (self.found_label, self.found):
            w.setVisible(hide)
        for w in (self.from_label, self.sessions):
            w.setVisible(not hide)
        self.copy_btn.setText("Hide Details" if hide else "Copy Real Version")
        self.copy_btn.setEnabled(False)
        self.cancel_btn.setText("Cancel")
        self.found.clear()
        self.result.clear()
        self.result.setVisible(False)

        if not self.text.strip():
            self.status.setText("Nothing has been copied. Select the text, copy it, then press the shortcut again.")
            self._only_status()
            return
        if len(self.text) > MAX_OPEN_MB * 1024 * 1024:
            self.status.setText(f"The copied text is larger than {MAX_OPEN_MB} MB. Open it in the app instead.")
            self._only_status()
            return
        self.result.setVisible(True)
        (self._start_hide if hide else self._start_restore)()
        self.copy_btn.setFocus()

    def _only_status(self) -> None:
        for w in (self.found_label, self.found, self.from_label, self.sessions):
            w.hide()
        self.cancel_btn.setText("Close")

    # ---- hide -------------------------------------------------------------------
    def _start_hide(self) -> None:
        # First show the copied text as it is; the details are only replaced when staff click Hide Details.
        self.masked = False
        self.detections = []
        self.result.setPlainText(self.text)
        self.found.setVisible(False)
        self.found_label.setVisible(False)
        self.status.setText("This is the text you copied. Click Hide Details to replace personal details with codes.")
        self.copy_btn.setText("Hide Details")
        self.copy_btn.setEnabled(True)

    def _mask(self) -> None:
        self.masked = True
        self.detections = settings_detector(self.vault.settings).find(self.text)
        self.found.blockSignals(True)
        seen = set()
        for d in self.detections:
            key = _norm(d.text)
            if key in seen:
                continue
            seen.add(key)
            item = QListWidgetItem(f"{d.text}   ·   {d.label or KINDS[d.kind]}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if d.enabled else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.found.addItem(item)
        self.found.blockSignals(False)
        self.found.setVisible(bool(seen))
        self.found_label.setVisible(bool(seen))
        self.copy_btn.setText("Copy Safe Version")
        self._show_hide()
        self.adjustSize()

    def _toggled(self, item: QListWidgetItem) -> None:
        key, on = item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked
        for d in self.detections:
            if _norm(d.text) == key:
                d.enabled = on
        self._show_hide()

    def _show_hide(self) -> None:
        hidden = [d for d in self.detections if d.enabled]
        self.result.setPlainText(apply(self.text, hidden, Session()))
        n = len({_norm(d.text) for d in hidden})
        unticked = len({_norm(d.text) for d in self.detections if not d.enabled})
        msg = f"{n} detail{'s' if n != 1 else ''} will be hidden." if n else "No personal details were found."
        if unticked:
            msg += f" {unticked} unticked item{'s' if unticked != 1 else ''} will stay visible: check them first."
        self.status.setText(msg)
        self.copy_btn.setEnabled(True)

    # ---- restore ----------------------------------------------------------------
    def _start_restore(self) -> None:
        entries = [e for e in self.vault.entries if e.kind == KIND_MASK]
        best, _ = best_entry(self.text, entries)
        self.sessions.blockSignals(True)
        self.sessions.clear()
        for e in sorted(entries, key=lambda e: e.created, reverse=True):
            when = datetime.fromisoformat(e.created).strftime("%d %b %Y, %H:%M")
            self.sessions.addItem(f"{e.label}  ·  {when}", e.id)
        self.sessions.blockSignals(False)
        if not entries:
            self.status.setText("Nothing has been hidden yet, so there is nothing to restore.")
            self.result.hide()
            return
        if best is not None:
            self.sessions.setCurrentIndex(self.sessions.findData(best.id))
        self._show_restore()

    def _show_restore(self) -> None:
        entry = self.vault.get(self.sessions.currentData()) if self.sessions.count() else None
        if entry is None:
            return
        text, n = restore(self.text, entry.mapping)
        self.result.setPlainText(text)
        self.status.setText(f"{n} detail{'s' if n != 1 else ''} filled back in." if n else
                            "No codes from this text were found in the copied reply. Choose the text it came from.")
        self.copy_btn.setEnabled(n > 0)

    # ---- result -----------------------------------------------------------------
    def copy(self) -> None:
        if self.mode == HIDE and not self.masked:
            self._mask()
            return
        if self.mode == HIDE:
            session = Session()
            safe = apply(self.text, [d for d in self.detections if d.enabled], session)
            label = "Quick hide: " + " ".join(self.text.split()[:6])
            self.vault.add(KIND_MASK, label, mapping=session.mapping)
            # Replaces the real text on the clipboard, so it is not pasted anywhere by mistake.
            QGuiApplication.clipboard().setText(safe)
            self.saved.emit()
            self.status.setText("Safe version copied. Paste it into your AI tool.")
        else:
            copy_secret(self.result.toPlainText())
            self.status.setText(f"Copied. It is removed from the clipboard after {SECRET_CLEAR_SECONDS} seconds.")
        self.copy_btn.setEnabled(False)
        self.copy_btn.setText("Copied")
        self.closer.start()

    def closeEvent(self, event) -> None:
        # Nothing real stays in the window after it closes.
        self.text, self.detections = "", []
        self.found.clear()
        self.result.clear()
        self.sessions.clear()
        self.password.clear()
        super().closeEvent(event)
