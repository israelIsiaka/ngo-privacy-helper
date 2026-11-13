"""A short step-by-step tour, shown after unlocking the first few times the app is opened."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .common import APP_NAME, TAGLINE, hint, primary

TIMES = 4   # how many openings the tour is shown on

# (title, text, sidebar section to show behind the tour or None)
STEPS = [
    (f"Welcome to {APP_NAME}", f"{TAGLINE}<br><br>This short tour shows what each part of the app does. "
     "Everything happens on this computer: nothing is uploaded and no account is needed.", None),
    ("Hide details before using AI", "Paste a case note or open a Word, Excel, CSV or text file. Names, phone "
     "numbers, places and ID numbers are highlighted and replaced with codes such as [PERSON_1].<br><br>"
     "Untick anything that is safe to share, then choose <i>Copy Safe Version</i> and paste it into your AI tool.",
     "Hide Details"),
    ("Put the real details back", "Paste the AI's reply here. The codes are replaced with the real names and "
     "numbers, on this computer only.", "Restore Details"),
    ("Protect files", "Drop any file to encrypt it with its own key. PDFs can instead be locked with a password "
     "that opens in any PDF reader. Drop a protected file to open it again.", "Protect Files"),
    ("Share photos safely", "Open a photo to remove the hidden details phones record, such as where it was taken. "
     "Drag across faces, name tags or signs to blur them, then save a safe copy.", "Safe Photos"),
    ("Your keys", "Every protected file and hidden text has a key, kept here and locked by your master password. "
     "To let a colleague open a file, send the file and, separately, its key. Back up your keys from Settings: "
     "without your password or a backup, protected files cannot be opened.", "Keys"),
    ("Shortcuts in other apps", "Copy text in Word, email or a browser and press your Hide shortcut. A small "
     "window shows the text. Choose <i>Hide Details</i>, check what was found, then <i>Copy Safe Version</i>. "
     "Copy the AI's reply and press your Restore shortcut to fill the details back in.<br><br>"
     "Choose the keys in Settings. You can take this tour again from the Help menu.", None),
]


def due() -> bool:
    s = QSettings()
    return not s.value("tour/off", False, bool) and s.value("tour/shown", 0, int) < TIMES


def count_shown() -> None:
    s = QSettings()
    s.setValue("tour/shown", s.value("tour/shown", 0, int) + 1)


class Tour(QDialog):
    section = Signal(str)   # asks the main window to show this sidebar section

    def __init__(self, parent=None, offer_stop: bool = True):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Tour")
        self.i = 0
        self.step = hint("")
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.setMinimumHeight(130)
        self.stop = QCheckBox("Don't show this again")
        self.stop.setVisible(offer_stop)
        self.skip = QPushButton("Skip Tour")
        self.back = QPushButton("Back")
        self.next = primary(QPushButton())
        self.skip.clicked.connect(self.reject)
        self.back.clicked.connect(lambda: self.go(self.i - 1))
        self.next.clicked.connect(lambda: self.go(self.i + 1) if self.i < len(STEPS) - 1 else self.accept())

        row = QHBoxLayout()
        row.addWidget(self.stop)
        row.addStretch(1)
        for b in (self.skip, self.back, self.next):
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        for w in (self.step, self.title, self.body):
            lay.addWidget(w)
        lay.addLayout(row)
        self.body.setFixedWidth(520)
        self.go(0)

    def go(self, i: int) -> None:
        self.i = i
        title, text, section = STEPS[i]
        self.step.setText(f"Step {i + 1} of {len(STEPS)}")
        self.title.setText(title)
        self.body.setText(text)
        self.back.setEnabled(i > 0)
        last = i == len(STEPS) - 1
        self.next.setText("Finish" if last else "Next")
        self.skip.setVisible(not last)
        self.next.setFocus()
        if section:
            self.section.emit(section)

    def done(self, result: int) -> None:
        # Skip, Finish, Escape and the close button all end here.
        if self.stop.isChecked():
            QSettings().setValue("tour/off", True)
        super().done(result)
