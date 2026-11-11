import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from privacy_helper import hotkeys  # noqa: E402
from privacy_helper.core.vault import KIND_MASK, Vault  # noqa: E402
from privacy_helper.ui.quick_popup import HIDE, RESTORE, QuickPopup, best_entry  # noqa: E402

app = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("ngo-privacy-helper-tests")   # keep test choices out of real preferences

NOTE = "Mrs Hadiza Ibrahim (0803 555 1234) needs clean water."


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path / "keys.vault")
    v.create("long enough password")
    return v


def test_shortcuts_must_not_take_ordinary_keys_from_other_apps():
    for bad in ("Ctrl+L", "H", "Shift+H", "Ctrl+Alt+F13", "Ctrl+Alt+Left"):
        with pytest.raises(hotkeys.ShortcutError):
            hotkeys.check(QKeySequence(bad))
    assert hotkeys.check(QKeySequence("Ctrl+Alt+H"))
    assert hotkeys.check(QKeySequence("Ctrl+Shift+F9"))


def test_letters_map_to_the_system_key_codes():
    from PySide6.QtCore import Qt
    if sys.platform == "darwin":
        assert hotkeys._key_code(Qt.Key.Key_H) == 4 and hotkeys._key_code(Qt.Key.Key_R) == 15
        assert hotkeys._key_code(Qt.Key.Key_0) == 29 and hotkeys._key_code(Qt.Key.Key_F1) == 0x7A
    else:
        assert hotkeys._key_code(Qt.Key.Key_H) == ord("H") and hotkeys._key_code(Qt.Key.Key_F1) == 0x70


def test_saved_shortcuts_round_trip():
    try:
        hotkeys.save({"hide": QKeySequence("Ctrl+Alt+H")})
        got = hotkeys.saved()
        assert got["hide"] == QKeySequence("Ctrl+Alt+H") and got["restore"].isEmpty()
        assert hotkeys.offered()
    finally:
        QSettings().clear()


@pytest.mark.skipif(sys.platform not in ("win32", "darwin"), reason="system shortcuts exist on Windows and macOS")
def test_shortcut_registers_with_the_system_and_refuses_a_taken_one():
    first, second = hotkeys.Hotkeys(), hotkeys.Hotkeys()
    seq = QKeySequence("Ctrl+Alt+Shift+F9")
    first.register(seq, lambda: None)
    try:
        with pytest.raises(hotkeys.ShortcutError, match="already uses"):
            second.register(seq, lambda: None)
    finally:
        first.clear()
    second.register(seq, lambda: None)   # free again once released
    second.clear()


def test_quick_hide_copies_the_safe_version_and_keeps_the_codes(vault):
    QGuiApplication.clipboard().setText(NOTE)
    popup = QuickPopup(vault)
    popup.start(HIDE)
    assert not popup.work_box.isHidden()
    assert "[PHONE_1]" in popup.result.toPlainText() and "0803" not in popup.result.toPlainText()
    popup.copy()
    safe = QGuiApplication.clipboard().text()
    assert "Hadiza" not in safe and "[PERSON_1]" in safe
    entry = next(e for e in vault.entries if e.kind == KIND_MASK)
    assert entry.mapping["PERSON_1"] == "Hadiza Ibrahim"
    popup.close()
    assert popup.result.toPlainText() == "" and popup.text == ""   # nothing real left behind


def test_unticking_a_detail_leaves_it_in_the_safe_version(vault):
    QGuiApplication.clipboard().setText(NOTE)
    popup = QuickPopup(vault)
    popup.start(HIDE)
    phone = next(popup.found.item(i) for i in range(popup.found.count()) if "0803" in popup.found.item(i).text())
    phone.setCheckState(phone.checkState().__class__.Unchecked)
    assert "0803 555 1234" in popup.result.toPlainText()
    assert "stay visible" in popup.status.text()


def test_quick_restore_picks_the_text_the_reply_came_from(vault):
    vault.add(KIND_MASK, "older", mapping={"PERSON_1": "Musa Bello"})
    vault.add(KIND_MASK, "case note", mapping={"PERSON_1": "Hadiza Ibrahim", "PHONE_1": "0803 555 1234"})
    vault.add(KIND_MASK, "newest", mapping={"PLACE_1": "Gusau"})
    reply = "Call [PERSON_1] on [PHONE_1] about water."
    best, n = best_entry(reply, vault.entries)
    assert best.label == "case note" and n == 2

    QGuiApplication.clipboard().setText(reply)
    popup = QuickPopup(vault)
    popup.start(RESTORE)
    assert popup.result.toPlainText() == "Call Hadiza Ibrahim on 0803 555 1234 about water."
    popup.copy()
    assert QGuiApplication.clipboard().text() == "Call Hadiza Ibrahim on 0803 555 1234 about water."
    popup.close()


def test_locked_app_asks_for_the_password_first(vault):
    vault.lock()
    QGuiApplication.clipboard().setText(NOTE)
    popup = QuickPopup(vault)
    unlocked = []
    popup.unlocked.connect(lambda: unlocked.append(True))
    popup.start(HIDE)
    assert popup.work_box.isHidden() and not popup.locked_box.isHidden()
    popup.password.setText("wrong password!")
    popup.unlock()
    assert not vault.unlocked and popup.lock_error.text()
    popup.password.setText("long enough password")
    popup.unlock()
    assert vault.unlocked and unlocked and not popup.work_box.isHidden()
    assert "[PHONE_1]" in popup.result.toPlainText()
    popup.close()


def test_nothing_copied_says_what_to_do(vault):
    QGuiApplication.clipboard().clear()
    popup = QuickPopup(vault)
    popup.start(HIDE)
    assert "Nothing has been copied" in popup.status.text() and not popup.copy_btn.isEnabled()
    popup.close()


@pytest.mark.skipif(sys.platform != "win32", reason="presses keys through the Windows input queue")
def test_pressing_the_shortcut_on_windows_calls_back():
    import ctypes
    import time
    keys = hotkeys.Hotkeys()
    hits = []
    keys.register(QKeySequence("Ctrl+Alt+Shift+F9"), lambda: hits.append(1))
    user32 = ctypes.windll.user32
    vk = (0x11, 0x12, 0x10, 0x78)   # Ctrl, Alt, Shift, F9
    try:
        for k in vk:
            user32.keybd_event(k, 0, 0, 0)
        for k in reversed(vk):
            user32.keybd_event(k, 0, 2, 0)   # key up
        deadline = time.monotonic() + 3
        while not hits and time.monotonic() < deadline:
            app.processEvents()
    finally:
        keys.clear()
    assert hits == [1]
