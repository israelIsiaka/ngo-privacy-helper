"""Make photos safe to share: drop hidden details (GPS location, camera, date) and blur chosen areas.

Photos are redrawn into a brand-new image, so nothing from the original file's
metadata is carried over: EXIF, GPS, XMP and PNG text all stay behind. Uses Qt's
own image support, so no extra libraries are needed.

ponytail: staff mark faces, name tags and signs by hand. Automatic face finding
needs a vision library about as large as the whole app; add it if NGOs ask.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter

from .filecrypt import free_path

# Each type is read only by its own Qt decoder. Without this, Qt guesses the type from the contents, so a
# ".jpg" that is really an ICNS or SVG file would reach decoders with known crash bugs in Qt 6.8.3
# (CVE-2025-5683, CVE-2025-10728). The build also leaves those decoders out.
_FORMAT = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp", ".heic": "heic",
           ".tif": "tiff", ".tiff": "tiff", ".bmp": "bmp"}
SUPPORTED = set(_FORMAT)
_KEEP_TYPE = {".jpg", ".jpeg", ".png"}   # other types are saved as JPEG, which every phone and computer opens
BLOCKS = 6   # a blurred area becomes about 6 × 6 blocks: too coarse to recognise a face or read a name


class PhotoError(Exception):
    pass


def has_location(path: Path) -> bool:
    """True if a JPEG photo records where it was taken (an EXIF GPS section)."""
    try:
        with open(path, "rb") as f:
            data = f.read(256 * 1024)   # EXIF sits at the start of the file
        tiff = _jpeg_exif(data)
        if not tiff:
            return False
        end = "<" if tiff[:2] == b"II" else ">"
        ifd = struct.unpack(end + "I", tiff[4:8])[0]
        count = struct.unpack(end + "H", tiff[ifd:ifd + 2])[0]
        for i in range(count):
            at = ifd + 2 + 12 * i
            if struct.unpack(end + "H", tiff[at:at + 2])[0] == 0x8825:   # GPS information
                return True
    except (OSError, struct.error):
        pass
    return False


def _jpeg_exif(data: bytes) -> bytes:
    if data[:2] != b"\xff\xd8":
        return b""
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xD9, 0xDA):   # end of image, start of picture data: no metadata after this
            break
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        segment = data[i + 4:i + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\0\0"):
            return segment[6:]
        i += 2 + length
    return b""


def load(path: Path) -> QImage:
    fmt = _FORMAT.get(Path(path).suffix.lower())
    if fmt is None:
        raise PhotoError(f"{Path(path).name} is not a supported photo type.")
    reader = QImageReader(str(path), fmt.encode())
    reader.setAutoDetectImageFormat(False)   # never fall back to guessing the type from the contents
    reader.setAutoTransform(True)   # apply the phone's rotation before the rotation tag is dropped
    image = reader.read()
    if image.isNull():
        raise PhotoError(f"{Path(path).name} could not be opened as a photo: {reader.errorString()}")
    return image


def blurred(image: QImage, areas: list[QRect]) -> QImage:
    """A fresh copy of the picture only, with each area turned into large blocks."""
    fresh = QImage(image.size(), QImage.Format.Format_ARGB32 if image.hasAlphaChannel() else QImage.Format.Format_RGB32)
    fresh.fill(Qt.GlobalColor.white)
    painter = QPainter(fresh)
    painter.drawImage(0, 0, image)
    for area in areas:
        area = area.intersected(fresh.rect())
        if area.isEmpty():
            continue
        cols = max(1, min(BLOCKS, area.width()))
        rows = max(1, min(BLOCKS, area.height()))
        small = fresh.copy(area).scaled(cols, rows, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(area, small.scaled(area.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.FastTransformation))
    painter.end()
    return fresh


def save_safe_copy(src: Path, out_dir: Path, areas: list[QRect]) -> Path:
    """Write "<name> (safe).jpg" next to the original, which is never changed."""
    src = Path(src)
    suffix = src.suffix.lower() if src.suffix.lower() in _KEEP_TYPE else ".jpg"
    out = free_path(Path(out_dir) / f"{src.stem} (safe){suffix}")
    if not blurred(load(src), areas).save(str(out), quality=92):
        raise PhotoError(f"{out.name} could not be saved.")
    return out
