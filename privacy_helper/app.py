"""Main window, menus, auto-lock, and files opened from Finder / File Explorer."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QMainWindow, QMessageBox, QStackedWidget,
                               QTabWidget, QWidget)

from . import __version__
from .core import documents
from .core.vault import Vault
from .ui.common import APP_NAME, STYLE
from .ui.hide_page import HidePage
from .ui.keys_page import KeysPage
from .ui.lock_screen import LockScreen
from .ui.protect_page import ProtectPage
from .ui.restore_page import RestorePage
from .ui.settings_dialog import SettingsDialog

RESOURCES = Path(__file__).parent / "resources"   # PyInstaller keeps this layout

GUIDE = """
<h3>Using NGO Privacy Helper</h3>
<p><b>Hide details.</b> Paste a case note or open a Word, Excel, CSV or text file. Names, phone numbers,
places and ID numbers are highlighted and listed on the right. Untick anything that is safe, select missed
words and choose <i>Hide Selected Text</i>. Then choose <i>Copy Safe Version</i> and paste it into your AI tool.</p>
<p><b>Restore details.</b> Paste the AI's reply. Codes such as [PERSON_1] are replaced with the real details,
on this computer only.</p>
<p><b>Protect files.</b> Drop any file to encrypt it. PDFs can instead be locked with a password that opens in
any PDF reader. Drop a protected file to open it again. Each file gets its own key.</p>
<p><b>Keys.</b> Find any key by file name. To let a colleague open a file, send the file and, separately,
its key or password.</p>
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
        self.keys_page = KeysPage(vault)
        self.pages = [("Hide Details", self.hide_page), ("Restore Details", self.restore_page),
                      ("Protect Files", self.protect_page), ("Keys", self.keys_page)]

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        self.sidebar.setAccessibleName("Sections")
        self.stack = QStackedWidget()
        for title, page in self.pages:
            self.sidebar.addItem(title)
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

        self.idle = QTimer(self, singleShot=True)
        self.idle.timeout.connect(lambda: self.lock(auto=True))
        self.pending: list[Path] = []
        self._build_menus()
        self._set_locked(True)

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
        save_a = self._action("&Save Safe Copy…", self.hide_page.save_safe, QKeySequence.StandardKey.Save)
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
        self.keys_page.reload()
        self.restore_page.reload_sessions()
        self.sidebar.setCurrentRow(0)
        self.touch()
        pending, self.pending = self.pending, []
        for path in pending:
            self.open_path(path)

    def lock(self, auto: bool) -> None:
        if not self.vault.unlocked:
            return
        for page in (self.hide_page, self.restore_page, self.protect_page):
            page.clear()
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
        dialog.exec()
        self.keys_page.reload()
        self.restore_page.reload_sessions()
        self.hide_page.refresh()
        self.touch()

    def open_path(self, path: Path) -> None:
        """A file opened from Finder / File Explorer, or passed on the command line."""
        if not self.vault.unlocked:
            self.pending.append(path)
            return
        if path.suffix.lower() in documents.SUPPORTED:
            self.sidebar.setCurrentRow(0)
            self.hide_page.open_path(path)
        else:
            self.sidebar.setCurrentRow(2)
            self.protect_page.add_files([path])
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
                          f"<h3>{APP_NAME}</h3><p>Version {__version__}</p>"
                          "<p>Hide personal details before using AI tools, and protect files with "
                          "their own keys. Everything happens on this computer.</p>"
                          "<p>Free for non-profit organisations.<br>Startbench Innovation Hub</p>")

    def closeEvent(self, event) -> None:
        if self.vault.unlocked and self.hide_page.has_work():
            answer = QMessageBox.question(self, f"Quit {APP_NAME}?",
                                          "The text in Hide Details will be cleared. Copied or saved safe "
                                          "versions can still be restored later.")
            if answer != QMessageBox.StandardButton.Yes:
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
        return super().event(e)


class ActivityWatcher(QObject):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self.window.touch()
        return False


def vault_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "keys.vault"


def main() -> int:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName("Startbench")
    QApplication.setApplicationVersion(__version__)
    app = Application(sys.argv)
    icon = RESOURCES / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    app.setStyleSheet(STYLE)

    window = MainWindow(Vault(vault_path()))
    app.window = window
    app.installEventFilter(ActivityWatcher(window))
    # Windows passes opened files as arguments; macOS turns them into FileOpen events (handled above).
    for arg in sys.argv[1:] if sys.platform != "darwin" else []:
        if Path(arg).is_file():
            window.open_path(Path(arg))
    window.show()
    return app.exec()
