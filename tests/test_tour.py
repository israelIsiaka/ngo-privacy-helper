import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from privacy_helper.ui import tour  # noqa: E402

app = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("ngo-privacy-helper-tests")


def test_tour_shows_on_the_first_four_openings_only():
    QSettings().clear()
    try:
        for _ in range(tour.TIMES):
            assert tour.due()
            tour.count_shown()
        assert not tour.due()
    finally:
        QSettings().clear()


def test_skip_can_stop_it_for_good_and_steps_name_real_sections():
    QSettings().clear()
    try:
        t = tour.Tour()
        seen = []
        t.section.connect(seen.append)
        for i in range(len(tour.STEPS)):
            t.go(i)
        assert t.next.text() == "Finish" and not t.back.isHidden()
        assert seen == ["Hide Details", "Restore Details", "Protect Files", "Safe Photos", "Keys"]
        t.go(2)
        t.stop.setChecked(True)
        t.skip.click()
        assert not tour.due()
    finally:
        QSettings().clear()
