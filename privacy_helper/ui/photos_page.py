"""Safe photos: remove a photo's hidden location and camera details, and blur faces, name tags or signs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core import photos
from .common import FILE_MANAGER, DropZone, error_label, hint, page_header, primary, reveal

PHOTO_FILTER = "Photos (" + " ".join(f"*{s}" for s in sorted(photos.SUPPORTED)) + ");;All files (*)"


class PhotoCanvas(QWidget):
    """Shows the photo as it will be saved. Drag across a face, name tag or sign to blur it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.preview = QImage()
        self.areas: list[QRect] = []      # in photo pixels
        self._drag: QPoint | None = None
        self._now: QPoint | None = None
        self.on_change = lambda: None
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("Photo. Drag across an area to blur it.")

    def set_image(self, image: QImage) -> None:
        self.image, self.areas = image, []
        self._update()

    def _update(self) -> None:
        self.preview = photos.blurred(self.image, self.areas) if not self.image.isNull() else QImage()
        self.update()
        self.on_change()

    def undo(self) -> None:
        if self.areas:
            self.areas.pop()
            self._update()

    def _frame(self) -> tuple[QRectF, float]:
        """Where the photo is drawn, and how many screen pixels one photo pixel takes."""
        scale = min(self.width() / self.image.width(), self.height() / self.image.height())
        w, h = self.image.width() * scale, self.image.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), scale

    def _to_photo(self, p: QPoint) -> QPoint:
        frame, scale = self._frame()
        return QPoint(int((p.x() - frame.x()) / scale), int((p.y() - frame.y()) / scale))

    def paintEvent(self, event) -> None:
        if self.preview.isNull():
            return
        painter = QPainter(self)
        frame, scale = self._frame()
        painter.drawImage(frame, self.preview)
        pen = QPen(self.palette().highlight().color(), 2)
        painter.setPen(pen)
        for area in self.areas:
            painter.drawRect(QRectF(frame.x() + area.x() * scale, frame.y() + area.y() * scale,
                                    area.width() * scale, area.height() * scale))
        if self._drag and self._now:
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.fillRect(QRect(self._drag, self._now).normalized(), QColor(0, 0, 0, 60))
            painter.drawRect(QRect(self._drag, self._now).normalized())

    def mousePressEvent(self, event) -> None:
        if not self.image.isNull() and event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._now = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            self._now = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if not self._drag:
            return
        area = QRect(self._to_photo(self._drag), self._to_photo(event.position().toPoint())).normalized()
        self._drag = self._now = None
        area = area.intersected(self.image.rect())
        if area.width() >= 4 and area.height() >= 4:   # ignore a plain click
            self.areas.append(area)
        self._update()


class PhotosPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Path | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(page_header("Safe photos",
                                  "Photos from phones often record where they were taken. Remove that, and blur "
                                  "faces, name tags or signs, before a photo goes into a report or an AI tool."))

        self.zone = DropZone("Drop a photo here", "JPEG, PNG, HEIC and other common photo types. "
                             "The original is never changed.", accept=lambda p: p.suffix.lower() in photos.SUPPORTED)
        choose = QPushButton("Choose Photo…")
        choose.clicked.connect(self.choose)
        self.zone.button_row.addWidget(choose)
        self.zone.dropped.connect(lambda paths: self.open_path(paths[0]))
        lay.addWidget(self.zone)

        self.canvas = PhotoCanvas()
        self.canvas.on_change = self._update_buttons
        self.canvas.hide()
        lay.addWidget(self.canvas, 1)
        self.location = error_label()
        self.location.hide()
        lay.addWidget(self.location)
        self.tip = hint("Drag across each face, name tag, house number or sign that could identify someone. "
                        "Hidden details such as the camera, date and location are always removed.")
        self.tip.hide()
        lay.addWidget(self.tip)
        # Takes the spare height while no photo is open, so it is not spread between the heading and the drop area.
        lay.addStretch(0)

        foot = QHBoxLayout()
        self.status = hint("")
        self.other_btn = QPushButton("Choose Another…")
        self.undo_btn = QPushButton("Undo Blur")
        self.show_btn = QPushButton(f"Show in {FILE_MANAGER}")
        self.save_btn = primary(QPushButton("Save Safe Copy"))
        foot.addWidget(self.status, 1)
        for b in (self.other_btn, self.undo_btn, self.show_btn, self.save_btn):
            foot.addWidget(b)
        lay.addLayout(foot)
        self.saved: Path | None = None
        self.other_btn.clicked.connect(self.choose)
        self.undo_btn.clicked.connect(self.canvas.undo)
        self.show_btn.clicked.connect(lambda: self.saved and reveal(self.saved))
        self.save_btn.clicked.connect(self.save)
        self.clear()

    def choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose Photo", "", PHOTO_FILTER)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        try:
            image = photos.load(path)
        except photos.PhotoError as exc:
            self.status.setText(str(exc))
            return
        self.path, self.saved = path, None
        self.canvas.set_image(image)
        located = photos.has_location(path)
        self.location.setText("This photo records the place where it was taken. The safe copy will not."
                              if located else "")
        self.location.setVisible(located)
        for w in (self.canvas, self.tip):
            w.show()
        self.zone.hide()
        self.status.setText(path.name)
        self._update_buttons()

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.saved = photos.save_safe_copy(self.path, self.path.parent, self.canvas.areas)
        except (photos.PhotoError, OSError) as exc:
            self.status.setText(str(exc))
            return
        n = len(self.canvas.areas)
        blurred = f", {n} area{'s' if n != 1 else ''} blurred" if n else ""
        self.status.setText(f"Saved {self.saved.name}: hidden details removed{blurred}.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        loaded = self.path is not None
        for b in (self.other_btn, self.save_btn):
            b.setVisible(loaded)
        self.undo_btn.setVisible(loaded)
        self.undo_btn.setEnabled(bool(self.canvas.areas))
        self.show_btn.setVisible(self.saved is not None)

    def clear(self) -> None:
        """On lock: the photo may show the people the app protects."""
        self.path, self.saved = None, None
        self.canvas.set_image(QImage())
        for w in (self.canvas, self.tip, self.location):
            w.hide()
        self.zone.show()
        self.status.setText("")
        self._update_buttons()
