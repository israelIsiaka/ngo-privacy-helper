"""Main window, menus, auto-lock, and files opened from Finder / File Explorer."""

from __future__ import annotations

import getpass
import hashlib
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, QSettings, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QWidget,
)

from . import __version__, hotkeys
from .core import documents
from .core.vault import Vault
from .ui.common import APP_NAME, STORAGE_NAME, STYLE, TAGLINE
from .ui.hide_page import HidePage
from .ui.keys_page import KeysPage
from .ui.lock_screen import LockScreen
from .ui.photos_page import PhotosPage
from .ui.protect_page import ProtectPage
from .ui.quick_popup import HIDE, RESTORE, QuickPopup
from .ui.restore_page import RestorePage
from .ui.settings_dialog import SettingsDialog, ShortcutsDialog

RESOURCES = Path(__file__).parent / "resources"   # PyInstaller keeps this layout

GUIDE = """
<h3>Using Encryptra</h3>
<p><b>Hide details.</b> Paste a case note or open a Word, Excel, CSV or text file. Names, phone numbers,
places and ID numbers are highlighted and listed on the right. Untick anything that is safe, select missed
words and choose <i>Hide Selected Text</i>. Then choose <i>Copy Safe Version</i> and paste it into your AI tool.</p>
<p><b>Restore details.</b> Paste the AI's reply. Codes such as [PERSON_1] are replaced with the real details,
on this computer only.</p>
<p><b>Protect files.</b> Drop any file to encrypt it. PDFs can instead be locked with a password that opens in
any PDF reader. Drop a protected file to open it again. Each file gets its own key.</p>
<p><b>Safe photos.</b> Open a photo to remove the hidden details phones record, such as where it was taken. Drag
across faces, name tags or signs to blur them, then save a safe copy.</p>
<p><b>Shortcuts in other apps.</b> Copy text anywhere and press your Hide shortcut. A small window shows the
text. Choose <i>Hide Details</i>, check what was found, then choose <i>Copy Safe Version</i>.
Copy the AI's reply and press your Restore shortcut to fill the real
details back in. Choose the keys in Settings.</p>
<p><b>Keys.</b> Find any key by file name. To let a colleague open a file, send the file and, separately,
its key or password. Set a delete date so that a key is destroyed when it is no longer needed.</p>
<p><b>Keep your keys safe.</b> Back them up from Settings. Without your master password or a backup,
protected files cannot be opened.</p>
"""


class MainWindow(QMainWindow):
    def __init__(self, vault: Vault):
        super().__init__()
        self.vault = vault
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(880, 600)
        self.resize(1120, 740)

        self.lock_screen = LockScreen(vault)
        self.hide_page = HidePage(vault)
        self.restore_page = RestorePage(vault)
        self.protect_page = ProtectPage(vault)
        self.photos_page = PhotosPage()
        self.keys_page = KeysPage(vault)
        self.pages = [("Hide Details", self.hide_page), ("Restore Details", self.restore_page),
                      ("Protect Files", self.protect_page), ("Safe Photos", self.photos_page),
                      ("Keys", self.keys_page)]

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        self.sidebar.setAccessibleName("Sections")
        self.stack = QStackedWidget()
        for title, page in self.pages:
            self.sidebar.addItem(title)
            # Not every style makes rows tall enough for the item padding in STYLE; without this the
            # highlight spills onto the next row (seen with Fusion, which Windows and Linux can use).
            self.sidebar.item(self.sidebar.count() - 1).setSizeHint(QSize(0, self.sidebar.fontMetrics().height() + 20))
            self.stack.addWidget(page)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        work = QWidget()
        row = QHBoxLayout(work)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.sidebar)
        row.addWidget(self.stack, 1)

        self.root = QStackedWidget()
        self.root.addWidget(self.lock_screen)
        self.root.addWidget(work)
        self.setCentralWidget(self.root)

        self.lock_screen.unlocked.connect(self.on_unlocked)
        self.hide_page.session_saved.connect(self.restore_page.reload_sessions)
        self.hide_page.session_saved.connect(self.keys_page.reload)
        for page in (self.protect_page, self.keys_page):
            page.keys_changed.connect(self.keys_page.reload)
            page.keys_changed.connect(self.restore_page.reload_sessions)

        # Shortcuts work from any app, even while the window is closed or the app is locked.
        self.popup = QuickPopup(vault)
        self.popup.unlocked.connect(self.on_unlocked)
        self.popup.saved.connect(self.restore_page.reload_sessions)
        self.popup.saved.connect(self.keys_page.reload)
        self.hotkeys = hotkeys.Hotkeys()
        self.tray: QSystemTrayIcon | None = None
        self.quitting = False

        self.idle = QTimer(self, singleShot=True)
        self.idle.timeout.connect(lambda: self.lock(auto=True))
        self.pending: list[Path] = []
        self._build_menus()
        self._set_locked(True)
        self.warn_shortcuts(self.apply_shortcuts())

    # ---- menus (Apple HIG: every command is in the menu bar) ------------------
    def _action(self, text, slot, shortcut=None, role=None) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        if role is not None:
            a.setMenuRole(role)
        return a

    def _build_menus(self) -> None:
        bar = self.menuBar()
        self.unlocked_actions: list[QAction] = []

        file_menu = bar.addMenu("&File")
        open_a = self._action("&Open File to Hide Details…", self.open_to_hide, QKeySequence.StandardKey.Open)
        protect_a = self._action("&Protect Files…", self.choose_to_protect, "Ctrl+Shift+O")
        save_a = self._action("&Save Safe File…", self.hide_page.save_safe, QKeySequence.StandardKey.Save)
        settings_a = self._action("Se&ttings…", self.open_settings, QKeySequence.StandardKey.Preferences,
                                  QAction.MenuRole.PreferencesRole)
        quit_a = self._action("&Quit" if sys.platform == "darwin" else "E&xit", QApplication.quit,
                              QKeySequence.StandardKey.Quit, QAction.MenuRole.QuitRole)
        for a in (open_a, protect_a, save_a):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(settings_a)   # moved to the app menu on macOS automatically
        file_menu.addSeparator()
        file_menu.addAction(quit_a)
        self.unlocked_actions += [open_a, protect_a, save_a, settings_a]

        edit_menu = bar.addMenu("&Edit")
        for item in (("&Undo", QKeySequence.StandardKey.Undo, "undo"),
                     ("&Redo", QKeySequence.StandardKey.Redo, "redo"), None,
                     ("Cu&t", QKeySequence.StandardKey.Cut, "cut"),
                     ("&Copy", QKeySequence.StandardKey.Copy, "copy"),
                     ("&Paste", QKeySequence.StandardKey.Paste, "paste"),
                     ("Select &All", QKeySequence.StandardKey.SelectAll, "selectAll")):
            if item is None:
                edit_menu.addSeparator()
                continue
            text, key, slot = item
            edit_menu.addAction(self._action(text, lambda _=False, s=slot: self._edit(s), key))

        view_menu = bar.addMenu("&View")
        for i, (title, _) in enumerate(self.pages):
            a = self._action(title, lambda _=False, i=i: self.sidebar.setCurrentRow(i), f"Ctrl+{i + 1}")
            view_menu.addAction(a)
            self.unlocked_actions.append(a)

        keys_menu = bar.addMenu("&Keys")
        lock_a = self._action("&Lock Now", lambda: self.lock(auto=False), "Ctrl+L")
        import_a = self._action("&Import Key…", self.keys_page.import_key)
        keys_menu.addAction(lock_a)
        keys_menu.addSeparator()
        keys_menu.addAction(import_a)
        keys_menu.addAction(self._action("&Back Up Keys…", lambda: self.open_settings(tab=2)))
        self.unlocked_actions += [lock_a, import_a] + keys_menu.actions()[-1:]

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self._action(f"{APP_NAME} &Guide", self.show_guide, QKeySequence.StandardKey.HelpContents))
        help_menu.addAction(self._action(f"&About {APP_NAME}", self.show_about, role=QAction.MenuRole.AboutRole))

    def _edit(self, slot: str) -> None:
        w = QApplication.focusWidget()
        if w is not None and hasattr(w, slot):
            getattr(w, slot)()

    # ---- lock --------------------------------------------------------------
    def _set_locked(self, locked: bool) -> None:
        self.root.setCurrentIndex(0 if locked else 1)
        for a in self.unlocked_actions:
            a.setEnabled(not locked)

    def on_unlocked(self) -> None:
        self._set_locked(False)
        # ponytail: expiry is checked at unlock only; auto-lock means the app is rarely open a whole day.
        gone = self.vault.purge_expired()
        if gone:
            names = ", ".join(gone[:5]) + (f" and {len(gone) - 5} more" if len(gone) > 5 else "")
            self.keys_page.status.setText(f"Keys past their delete date were destroyed: {names}.")
        self.keys_page.reload()
        self.restore_page.reload_sessions()
        self.sidebar.setCurrentRow(0)
        self.touch()
        pending, self.pending = self.pending, []
        for path in pending:
            self.open_path(path)
        if self.hotkeys.supported and not hotkeys.offered():
            QTimer.singleShot(0, self.offer_shortcuts)

    def lock(self, auto: bool) -> None:
        if not self.vault.unlocked:
            return
        # Never lock under a running file job or an open dialog: both still need the keys.
        if self.protect_page.busy or QApplication.activeModalWidget() is not None:
            self.idle.start(60_000)
            if not auto:
                self.protect_page.status.setText("The app will lock when the current files are finished.")
            return
        for page in (self.hide_page, self.restore_page, self.protect_page, self.photos_page, self.keys_page):
            page.clear()
        self.popup.close()
        self.vault.lock()
        self.lock_screen.reset("Locked after a period of no activity. Open text was cleared for privacy."
                               if auto else "")
        self._set_locked(True)

    def touch(self) -> None:
        if self.vault.unlocked:
            self.idle.start(self.vault.settings.lock_minutes * 60_000)

    # ---- actions ----------------------------------------------------------
    def open_to_hide(self) -> None:
        self.sidebar.setCurrentRow(0)
        self.hide_page.choose_file()

    def choose_to_protect(self) -> None:
        self.sidebar.setCurrentRow(2)
        self.protect_page.choose()

    def open_settings(self, tab: int = 0) -> None:
        dialog = SettingsDialog(self.vault, self)
        dialog.findChild(QTabWidget).setCurrentIndex(tab)
        self.hotkeys.clear()   # otherwise the shortcut boxes cannot record the keys in use
        dialog.exec()
        self.warn_shortcuts(self.apply_shortcuts())
        self.keys_page.reload()
        self.restore_page.reload_sessions()
        self.hide_page.refresh()
        self.touch()

    def open_path(self, path: Path) -> None:
        """A file opened from Finder / File Explorer, or passed on the command line."""
        if not self.vault.unlocked:
            self.pending.append(path)
            return
        # A PDF opened from outside most likely needs locking before it is sent, so it goes to Protect Files.
        if path.suffix.lower() in documents.SUPPORTED - documents.PDF_TYPES:
            self.sidebar.setCurrentRow(0)
            self.hide_page.open_path(path)
        else:
            self.sidebar.setCurrentRow(2)
            self.protect_page.add_files([path])
        self.raise_()
        self.activateWindow()

    # ---- shortcuts in other apps ----------------------------------------------------
    def offer_shortcuts(self) -> None:
        if ShortcutsDialog(self).exec():
            self.warn_shortcuts(self.apply_shortcuts())

    def apply_shortcuts(self) -> list[str]:
        """Register the saved shortcuts. Returns what could not be registered."""
        self.hotkeys.clear()
        problems, on = [], {}
        if not self.hotkeys.supported:
            return problems
        for action, seq in hotkeys.saved().items():
            if seq.isEmpty():
                continue
            try:
                self.hotkeys.register(seq, lambda a=action: self.popup.start(a))
                on[action] = hotkeys.label(seq)
            except hotkeys.ShortcutError as exc:
                problems.append(str(exc))
        self._show_tray(on)
        return problems

    def warn_shortcuts(self, problems: list[str]) -> None:
        if problems:
            QMessageBox.warning(self, "Shortcut Not Available",
                                "\n\n".join(problems) + "\n\nChoose another one in Settings › Shortcuts.")

    def _show_tray(self, on: dict[str, str]) -> None:
        """While shortcuts are on, the app keeps running in the menu bar or notification area."""
        QApplication.setQuitOnLastWindowClosed(not on)
        if not on or not QSystemTrayIcon.isSystemTrayAvailable():
            if self.tray:
                self.tray.hide()
            return
        if self.tray is None:
            self.tray = QSystemTrayIcon(tray_icon(), self)
            self.tray.setToolTip(APP_NAME)
            self.tray.activated.connect(
                lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger
                and sys.platform != "darwin" else None)
            self.tray.setContextMenu(QMenu(self))
        menu = self.tray.contextMenu()
        menu.clear()
        for action, title in ((HIDE, "Hide Copied Text"), (RESTORE, "Restore Copied Text")):
            a = menu.addAction(f"{title}    {on[action]}" if action in on else title)
            a.triggered.connect(lambda _=False, m=action: self.popup.start(m))
        menu.addSeparator()
        menu.addAction(f"Open {APP_NAME}").triggered.connect(self.show_window)
        menu.addAction("Lock Now").triggered.connect(lambda: self.lock(auto=False))
        menu.addSeparator()
        menu.addAction("Quit" if sys.platform == "darwin" else "Exit").triggered.connect(QApplication.quit)
        self.tray.show()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_guide(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"{APP_NAME} Guide")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(GUIDE)
        box.exec()

    def show_about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME}</h3><p>{TAGLINE}</p><p>Version {__version__}</p>"
                          "<p>Hide personal details before using AI tools, and protect files with "
                          "their own keys. Everything happens on this computer.</p>"
                          "<p>Free for non-profit organisations.<br>Startbench Innovation Hub</p>")

    def closeEvent(self, event) -> None:
        if self.tray is not None and self.tray.isVisible() and not self.quitting:
            # Closing the window keeps the shortcuts working; Quit in the menu ends the app.
            event.ignore()
            self.hide()
            prefs = QSettings()
            if not prefs.value("shortcuts/told", False, type=bool):
                prefs.setValue("shortcuts/told", True)
                where = "menu bar" if sys.platform == "darwin" else "notification area"
                self.tray.showMessage(APP_NAME, f"Still running in the {where} so your shortcuts keep working. "
                                      "Choose Quit there to close it fully.")
            return
        if self.vault.unlocked and self.hide_page.has_work():
            answer = QMessageBox.question(self, f"Quit {APP_NAME}?",
                                          "The text in Hide Details will be cleared. Copied or saved safe "
                                          "versions can still be restored later.")
            if answer != QMessageBox.StandardButton.Yes:
                self.quitting = False
                event.ignore()
                return
        event.accept()


class Application(QApplication):
    """Receives files opened from Finder (macOS sends them as events, not arguments)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.window: MainWindow | None = None

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.FileOpen and self.window is not None:
            self.window.open_path(Path(e.file()))
            return True
        if e.type() == QEvent.Type.Quit and self.window is not None:
            self.window.quitting = True   # Quit from a menu or the Dock really quits, even with the tray icon
        return super().event(e)


def tray_icon() -> QIcon:
    if sys.platform != "darwin":
        return QIcon(str(RESOURCES / "icon.png"))
    # macOS menu bar icons are one-colour templates that the system tints for light and dark menu bars.
    pm = QPixmap(36, 36)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(Qt.GlobalColor.black, 1.8))
    p.drawArc(QRectF(5.5, 2.5, 7, 9), 0, 180 * 16)
    p.drawLine(5.5, 7, 5.5, 8.5)
    p.drawLine(12.5, 7, 12.5, 8.5)
    p.setBrush(Qt.GlobalColor.black)
    p.drawRoundedRect(QRectF(3.5, 8, 11, 8), 1.5, 1.5)
    p.end()
    icon = QIcon(pm)
    icon.setIsMask(True)
    return icon


class ActivityWatcher(QObject):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self.window.touch()
        return False


# ---- one running copy per user ------------------------------------------------------
# Two copies would each keep their own list of keys and overwrite each other's saves.
SERVER_NAME = "ngo-privacy-helper-" + hashlib.sha256(getpass.getuser().encode()).hexdigest()[:16]


def hand_over_to_running_copy(paths: list[str]) -> bool:
    """If the app is already open, send it the files to open and return True."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(("\n".join(paths) + "\n").encode("utf-8"))
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def listen_for_other_copies(window: MainWindow) -> QLocalServer:
    server = QLocalServer(window)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # same user only
    QLocalServer.removeServer(SERVER_NAME)    # clears a stale socket left by a crash
    server.listen(SERVER_NAME)

    def accept() -> None:
        sock = server.nextPendingConnection()
        buffer = bytearray()

        def finish() -> None:
            for line in bytes(buffer).decode("utf-8", "replace").splitlines():
                if line.strip() and Path(line).is_file():
                    window.open_path(Path(line))
            window.showNormal()
            window.raise_()
            window.activateWindow()
        sock.readyRead.connect(lambda: buffer.extend(bytes(sock.readAll())))
        sock.disconnected.connect(finish)
        sock.disconnected.connect(sock.deleteLater)
    server.newConnection.connect(accept)
    return server


def report_unexpected_error(exc_type, exc, tb) -> None:
    traceback.print_exception(exc_type, exc, tb)
    if QApplication.instance() is not None:
        QMessageBox.critical(None, "Something Went Wrong",
                             f"The last action did not finish.\n\n{exc}\n\n"
                             "Your saved keys are not affected. If this keeps happening, restart the app.")


def vault_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "keys.vault"


def main() -> int:
    QApplication.setApplicationName(STORAGE_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName("Startbench")
    QApplication.setApplicationVersion(__version__)
    app = Application(sys.argv)
    # Windows passes opened files as arguments; macOS turns them into FileOpen events (handled above).
    paths = [a for a in sys.argv[1:] if Path(a).is_file()] if sys.platform != "darwin" else []
    if hand_over_to_running_copy(paths):
        return 0
    sys.excepthook = report_unexpected_error
    icon = RESOURCES / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    app.setStyleSheet(STYLE)

    window = MainWindow(Vault(vault_path()))
    app.window = window
    app.installEventFilter(ActivityWatcher(window))
    listen_for_other_copies(window)
    for path in paths:
        window.open_path(Path(path))
    if sys.platform == "darwin":
        # Clicking the Dock icon brings back a window closed while shortcuts kept the app running.
        app.applicationStateChanged.connect(
            lambda state: window.show_window() if state == Qt.ApplicationState.ApplicationActive
            and window.isHidden() and not window.popup.isVisible() else None)
    window.show()
    return app.exec()
