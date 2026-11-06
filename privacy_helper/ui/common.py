"""Small shared pieces: page header, drop zone, background jobs, file reveal."""

from __future__ import annotations

import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QFrame, QInputDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import documents

APP_NAME = "NGO Privacy Helper"
FILE_MANAGER = "Finder" if sys.platform == "darwin" else "File Explorer"

STYLE = """
QListWidget#sidebar { border: none; background: palette(window); padding: 8px 6px; outline: 0; }
QListWidget#sidebar::item { padding: 8px 12px; border-radius: 6px; margin: 1px 0; }
QListWidget#sidebar::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QLabel#pageTitle { font-weight: 600; }
QFrame#dropZone { border: 2px dashed palette(mid); border-radius: 10px; background: palette(base); }
QFrame#dropZone[active="true"] { border-color: palette(highlight); }
QFrame#divider { color: palette(mid); }
"""


def read_table_asking(parent: QWidget, path: Path) -> documents.Table | None:
    """Read a table, asking which sheet when an Excel file has several. None means staff cancelled."""
    sheet = None
    if path.suffix.lower() == ".xlsx":
        names = documents.sheet_names(path)
        if len(names) > 1:
            sheet, ok = QInputDialog.getItem(
                parent, "Choose a Sheet",
                f"{path.name} has {len(names)} sheets with details in them.\n"
                "Choose one to open. The others are left out of the result,\n"
                "so open the file again for each one you need.",
                names, 0, False)
            if not ok:
                return None
    return documents.read_table(path, sheet)


def page_header(title: str, subtitle: str) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 8)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    f = t.font()
    f.setPointSizeF(f.pointSizeF() * 1.6)
    t.setFont(f)
    t.setAccessibleName(title)
    s = hint(subtitle)
    lay.addWidget(t)
    lay.addWidget(s)
    return box


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    # Hints show file names and error messages: never let a name such as "<img src=…>.csv" render as HTML.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return label


def error_label() -> QLabel:
    """Red text readable on both light and dark system themes."""
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    dark = label.palette().color(QPalette.ColorRole.Window).lightness() < 128
    label.setStyleSheet(f"color: {'#ff8a80' if dark else '#b3261e'};")
    return label


def primary(button: QPushButton) -> QPushButton:
    button.setDefault(True)
    button.setAutoDefault(True)
    f = button.font()
    f.setWeight(QFont.Weight.DemiBold)
    button.setFont(f)
    return button


SECRET_CLEAR_SECONDS = 60


def copy_secret(text: str) -> None:
    """Copy a key or password, keep it out of Windows clipboard history and cloud sync,
    and clear it after a minute if it is still there."""
    data = QMimeData()
    data.setText(text)
    if sys.platform == "win32":
        win = 'application/x-qt-windows-mime;value="{}"'
        data.setData(win.format("ExcludeClipboardContentFromMonitorProcessing"), b"\x01\x00\x00\x00")
        data.setData(win.format("CanIncludeInClipboardHistory"), b"\x00\x00\x00\x00")
        data.setData(win.format("CanUploadToCloudClipboard"), b"\x00\x00\x00\x00")
    clipboard = QGuiApplication.clipboard()
    clipboard.setMimeData(data)

    def clear() -> None:
        if clipboard.text() == text:
            clipboard.clear()
    QTimer.singleShot(SECRET_CLEAR_SECONDS * 1000, clear)


def reveal(path: Path) -> None:
    """Show a file selected in Finder / File Explorer."""
    path = Path(path)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", "/select,", str(path)], check=False)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class DropZone(QFrame):
    """A labelled area that accepts dropped files. Highlights only while a
    file it can accept is over it (Apple HIG, Windows drag-and-drop guidance)."""

    dropped = Signal(list)

    def __init__(self, title: str, detail: str, accept: Callable[[Path], bool] | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setAccessibleName(title)
        self.accept_path = accept or (lambda p: p.is_file())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 28, 24, 28)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head = QLabel(title)
        f = head.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        f.setWeight(QFont.Weight.DemiBold)
        head.setFont(f)
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = hint(detail)
        sub.setWordWrap(False)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(head)
        lay.addWidget(sub)
        self.button_row = QVBoxLayout()
        self.button_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(6)
        lay.addLayout(self.button_row)

    def _paths(self, event) -> list[Path]:
        if not event.mimeData().hasUrls():
            return []
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        return [p for p in paths if self.accept_path(p)]

    def _set_active(self, on: bool) -> None:
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)   # never move the user's files
            event.accept()
            self._set_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_active(False)
        paths = self._paths(event)
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.dropped.emit(paths)


class _JobSignals(QObject):
    progress = Signal(int)
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    """Run slow work (encrypting a large file) off the UI thread."""

    def __init__(self, work: Callable[[Callable[[int, int], None]], object]):
        super().__init__()
        self.work = work
        self.signals = _JobSignals()

    def run(self) -> None:
        def report(done: int, total: int) -> None:
            self.signals.progress.emit(int(done * 100 / total) if total else 100)
        try:
            self.signals.done.emit(self.work(report))
        except Exception as exc:   # shown to the user, never swallowed
            msg = str(exc) or exc.__class__.__name__
            if not isinstance(exc, (OSError, ValueError)) and not exc.__class__.__module__.startswith("privacy_helper"):
                traceback.print_exc()
            self.signals.failed.emit(msg)


_running: set[Job] = set()


def run_job(job: Job) -> None:
    # Keep a Python reference until the job reports back, or it can be collected mid-run.
    _running.add(job)
    job.signals.done.connect(lambda _: _running.discard(job))
    job.signals.failed.connect(lambda _: _running.discard(job))
    job.setAutoDelete(False)
    QThreadPool.globalInstance().start(job)
