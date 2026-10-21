"""Render the app icon from icon.svg: PNG for the window, .icns (macOS) and .ico (Windows).

Run once after editing icon.svg:  python packaging/make_icons.py
"""

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = Path(__file__).parent
RES = HERE.parent / "privacy_helper" / "resources"


def render(svg: QSvgRenderer, size: int) -> QImage:
    img = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg.render(p)
    p.end()
    return img


def write_ico(svg: QSvgRenderer, path: Path) -> None:
    """Multi-size .ico (PNG entries) so Windows picks a sharp icon at every size."""
    sizes, blobs = (16, 24, 32, 48, 64, 128, 256), []
    for size in sizes:
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        render(svg, size).save(buf, "PNG")
        blobs.append(bytes(buf.data()))
    offset = 6 + 16 * len(sizes)
    out = struct.pack("<HHH", 0, 1, len(sizes))
    for size, blob in zip(sizes, blobs):
        dim = 0 if size == 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(out + b"".join(blobs))


def main() -> None:
    QGuiApplication(sys.argv)
    svg = QSvgRenderer(str(HERE / "icon.svg"))
    RES.mkdir(parents=True, exist_ok=True)
    render(svg, 512).save(str(RES / "icon.png"))
    write_ico(svg, HERE / "icon.ico")

    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "icon.iconset"
            iconset.mkdir()
            for size in (16, 32, 128, 256, 512):
                render(svg, size).save(str(iconset / f"icon_{size}x{size}.png"))
                render(svg, size * 2).save(str(iconset / f"icon_{size}x{size}@2x.png"))
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
    print("Icons written.")


if __name__ == "__main__":
    main()
