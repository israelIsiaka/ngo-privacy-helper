"""Save a picture of every page, for checking the look on a platform the developer does not use.

CI runs this on Windows and keeps the pictures. Run it yourself with: python packaging/screenshots.py OUT_DIR
"""

import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from privacy_helper.app import MainWindow  # noqa: E402
from privacy_helper.core.vault import Vault  # noqa: E402
from privacy_helper.ui.common import STYLE  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
print("Style:", app.style().name())
window = MainWindow(Vault(Path(tempfile.mkdtemp()) / "keys.vault"))
window.show()
app.processEvents()
window.grab().save(str(out / "0 Lock screen.png"))
window.vault.create("long enough password")
window.on_unlocked()
window.hide_page.editor.setPlainText(
    "Mrs Hadiza Ibrahim (0803 555 1234) at Zamfara Shelter is HIV positive. NIN 12345678901, born 03/04/1988.")
window.hide_page.refresh()
for row, (title, _) in enumerate(window.pages):
    window.sidebar.setCurrentRow(row)
    app.processEvents()
    window.grab().save(str(out / f"{row + 1} {title}.png"))
