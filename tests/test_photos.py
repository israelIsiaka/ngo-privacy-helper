import struct
from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from privacy_helper.core import photos


def _photo_with_gps(path: Path) -> None:
    """A JPEG with an EXIF block that records a GPS location, like a phone photo."""
    img = QImage(120, 80, QImage.Format.Format_RGB32)
    for x in range(120):
        for y in range(80):
            img.setPixelColor(x, y, QColor((x * 2) % 256, (y * 3) % 256, (x * y) % 256))
    img.save(str(path), quality=95)
    # TIFF header, IFD0 with one entry: tag 0x8825 (GPS) pointing at an empty GPS IFD.
    tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + struct.pack("<HHII", 0x8825, 4, 1, 26)
    tiff += struct.pack("<I", 0) + struct.pack("<H", 0) + struct.pack("<I", 0)
    exif = b"Exif\x00\x00" + tiff
    data = path.read_bytes()
    path.write_bytes(data[:2] + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + data[2:])


def test_location_is_found_and_removed_and_areas_are_blurred(tmp_path: Path):
    src = tmp_path / "visit.jpg"
    _photo_with_gps(src)
    assert photos.has_location(src)
    area = QRect(10, 10, 60, 40)
    out = photos.save_safe_copy(src, tmp_path, [area])
    assert out.name == "visit (safe).jpg" and src.read_bytes()[:4] == b"\xff\xd8\xff\xe1"   # original untouched
    assert not photos.has_location(out) and b"Exif" not in out.read_bytes()[:4096]
    before, after = photos.load(src), photos.load(out)
    assert after.size() == before.size()
    # Inside the area, neighbouring pixels within a block are now (nearly) the same colour.
    assert abs(after.pixelColor(12, 12).red() - after.pixelColor(18, 14).red()) <= 8
    assert abs(before.pixelColor(12, 12).red() - before.pixelColor(18, 14).red()) >= 10
    # Outside it, the picture is unchanged apart from JPEG noise.
    assert abs(after.pixelColor(100, 70).green() - before.pixelColor(100, 70).green()) <= 12


def test_non_photos_are_refused(tmp_path: Path):
    bad = tmp_path / "notes.jpg"
    bad.write_text("not a photo")
    assert not photos.has_location(bad)
    with pytest.raises(photos.PhotoError):
        photos.load(bad)
