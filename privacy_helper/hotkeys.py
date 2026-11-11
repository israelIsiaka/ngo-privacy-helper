"""System-wide keyboard shortcuts, so staff can hide or restore text without opening the app.

Uses the one call each system offers for this: RegisterHotKey on Windows, RegisterEventHotKey on macOS.
Neither needs administrator or Accessibility permission, and neither sees any key other than the
shortcut itself: this is not a keyboard hook, so the app never observes what staff type.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QKeyCombination, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence

MOD = Qt.KeyboardModifier
# Qt calls the Command key "Ctrl" on macOS and the Control key "Meta".
_MODS = (MOD.ControlModifier, MOD.AltModifier, MOD.ShiftModifier, MOD.MetaModifier)


class ShortcutError(Exception):
    pass


def check(seq: QKeySequence) -> QKeyCombination:
    """The single key combination in seq, if it is safe to take over in every app. Raises ShortcutError."""
    if seq.count() != 1:
        raise ShortcutError("Press one key combination.")
    combo = seq[0]
    mods = combo.keyboardModifiers() & (MOD.ControlModifier | MOD.AltModifier | MOD.ShiftModifier | MOD.MetaModifier)
    # A shortcut with one modifier (Ctrl+L) would be taken away from every other app.
    if sum(bool(mods & m) for m in _MODS) < 2:
        raise ShortcutError("Use at least two of Ctrl, Shift, Alt" + (" or Command" if sys.platform == "darwin" else "")
                            + " with a letter, number or F-key, so it does not clash with other apps.")
    if sys.platform == "win32" and mods & MOD.MetaModifier:
        raise ShortcutError("Windows keeps the Windows key for itself. Use Ctrl, Shift or Alt.")
    if sys.platform == "darwin" and not mods & (MOD.ControlModifier | MOD.MetaModifier):
        # Since macOS 15, shortcuts made only of Option and Shift are refused for apps like this one.
        raise ShortcutError("Include Command or Control.")
    if _key_code(combo.key()) is None:
        raise ShortcutError("Use a letter, a number or F1 to F12 as the last key.")
    return combo


def label(seq: QKeySequence) -> str:
    return seq.toString(QKeySequence.SequenceFormat.NativeText)


# ---- key codes ------------------------------------------------------------------------
# ponytail: letters map by position on a US/UK layout. On AZERTY or QWERTZ the shortcut fires on the key
# printed in that spot on a US keyboard; staff see it working in the Try It step, so this is left simple.
_MAC_LETTERS = {"A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7, "C": 8, "V": 9, "B": 11, "Q": 12,
                "W": 13, "E": 14, "R": 15, "Y": 16, "T": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
                "9": 25, "7": 26, "8": 28, "0": 29, "O": 31, "U": 32, "I": 34, "P": 35, "L": 37, "J": 38, "K": 40,
                "N": 45, "M": 46}
_MAC_F = [0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D, 0x67, 0x6F]


def _key_code(key: Qt.Key) -> int | None:
    k = int(key.value if hasattr(key, "value") else key)
    if Qt.Key.Key_F1.value <= k <= Qt.Key.Key_F12.value:
        n = k - Qt.Key.Key_F1.value
        return _MAC_F[n] if sys.platform == "darwin" else 0x70 + n
    if ord("A") <= k <= ord("Z") or ord("0") <= k <= ord("9"):
        return _MAC_LETTERS.get(chr(k)) if sys.platform == "darwin" else k   # Windows VK codes are ASCII here
    return None


# ---- the registry ---------------------------------------------------------------------
class Hotkeys:
    """Register shortcuts with the system and call back on the UI thread when one is pressed."""

    def __init__(self):
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next = 1
        self._native = _Windows(self._fire) if sys.platform == "win32" else (
            _Mac(self._fire) if sys.platform == "darwin" else None)

    @property
    def supported(self) -> bool:
        return self._native is not None

    @staticmethod
    def supported_here() -> bool:
        return sys.platform in ("win32", "darwin")

    def register(self, seq: QKeySequence, callback: Callable[[], None]) -> None:
        """Raises ShortcutError if the shortcut is not allowed or another app already has it."""
        combo = check(seq)
        if self._native is None:
            raise ShortcutError("Shortcuts in other apps work on Windows and macOS only.")
        hid, self._next = self._next, self._next + 1
        self._native.register(hid, combo, label(seq))
        self._callbacks[hid] = callback

    def clear(self) -> None:
        for hid in list(self._callbacks):
            self._native.unregister(hid)
        self._callbacks.clear()

    def _fire(self, hid: int) -> None:
        cb = self._callbacks.get(hid)
        if cb:
            # Leave the system's callback first; the pop-up opens on the next turn of the event loop.
            QTimer.singleShot(0, cb)


class _Windows(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
    ERROR_HOTKEY_ALREADY_REGISTERED = 1409

    def __init__(self, fire: Callable[[int], None]):
        super().__init__()
        from ctypes import wintypes
        self._msg_type = wintypes.MSG
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._fire = fire
        # Thread hotkeys (no window) arrive as plain messages that Qt shows to native event filters.
        QCoreApplication.instance().installNativeEventFilter(self)

    def register(self, hid: int, combo: QKeyCombination, name: str) -> None:
        m = combo.keyboardModifiers()
        mods = self.MOD_NOREPEAT
        mods |= self.MOD_CONTROL if m & MOD.ControlModifier else 0
        mods |= self.MOD_ALT if m & MOD.AltModifier else 0
        mods |= self.MOD_SHIFT if m & MOD.ShiftModifier else 0
        if not self._user32.RegisterHotKey(None, hid, mods, _key_code(combo.key())):
            err = ctypes.get_last_error()
            if err == self.ERROR_HOTKEY_ALREADY_REGISTERED:
                raise ShortcutError(f"Another app already uses {name}. Choose a different shortcut.")
            raise ShortcutError(f"Windows did not accept {name} (error {err}).")

    def unregister(self, hid: int) -> None:
        self._user32.UnregisterHotKey(None, hid)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            msg = self._msg_type.from_address(int(message))
            if msg.message == self.WM_HOTKEY:
                self._fire(int(msg.wParam))
                return True, 0
        return False, 0


class _Mac:
    CMD, SHIFT, OPTION, CONTROL = 0x100, 0x200, 0x800, 0x1000
    SIGNATURE = int.from_bytes(b"NPHk", "big")
    KEYBOARD_CLASS, HOTKEY_PRESSED = int.from_bytes(b"keyb", "big"), 5
    DIRECT_OBJECT, TYPE_HOTKEY_ID = int.from_bytes(b"----", "big"), int.from_bytes(b"hkid", "big")
    EXCLUSIVE = 1
    HOTKEY_EXISTS = -9878

    class HotKeyID(ctypes.Structure):
        _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

    class EventTypeSpec(ctypes.Structure):
        _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

    HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    def __init__(self, fire: Callable[[int], None]):
        c = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, self.HANDLER, ctypes.c_uint32,
                                          ctypes.POINTER(self.EventTypeSpec), ctypes.c_void_p, ctypes.c_void_p]
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, self.HotKeyID, ctypes.c_void_p,
                                          ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        self._c, self._fire, self._refs = c, fire, {}
        self._target = c.GetApplicationEventTarget()

        def handler(_call, event, _data) -> int:
            hk = self.HotKeyID()
            c.GetEventParameter(event, self.DIRECT_OBJECT, self.TYPE_HOTKEY_ID, None, ctypes.sizeof(hk), None,
                                ctypes.byref(hk))
            if hk.signature == self.SIGNATURE:
                self._fire(hk.id)
            return 0
        self._handler = self.HANDLER(handler)   # kept: the system calls it for as long as the app runs
        spec = self.EventTypeSpec(self.KEYBOARD_CLASS, self.HOTKEY_PRESSED)
        c.InstallEventHandler(self._target, self._handler, 1, ctypes.byref(spec), None, None)

    def register(self, hid: int, combo: QKeyCombination, name: str) -> None:
        m = combo.keyboardModifiers()
        mods = (self.CMD if m & MOD.ControlModifier else 0) | (self.CONTROL if m & MOD.MetaModifier else 0)
        mods |= (self.OPTION if m & MOD.AltModifier else 0) | (self.SHIFT if m & MOD.ShiftModifier else 0)
        ref = ctypes.c_void_p()
        err = self._c.RegisterEventHotKey(_key_code(combo.key()), mods, self.HotKeyID(self.SIGNATURE, hid),
                                          self._target, self.EXCLUSIVE, ctypes.byref(ref))
        if err == self.HOTKEY_EXISTS:
            raise ShortcutError(f"Another app already uses {name}. Choose a different shortcut.")
        if err:
            raise ShortcutError(f"macOS did not accept {name} (error {err}).")
        self._refs[hid] = ref

    def unregister(self, hid: int) -> None:
        ref = self._refs.pop(hid, None)
        if ref:
            self._c.UnregisterEventHotKey(ref)


# ---- saved choice ---------------------------------------------------------------------
# Kept outside the key vault: the shortcut must work while the app is locked, to ask for the password.
ACTIONS = ("hide", "restore")
DEFAULTS = ({"hide": "Meta+Alt+H", "restore": "Meta+Alt+R"} if sys.platform == "darwin"   # Control+Option
            else {"hide": "Ctrl+Alt+H", "restore": "Ctrl+Alt+R"})


def saved() -> dict[str, QKeySequence]:
    """The shortcuts staff chose. An empty sequence means that shortcut is off."""
    prefs = QSettings()
    return {a: QKeySequence(str(prefs.value(f"shortcuts/{a}", "")), QKeySequence.SequenceFormat.PortableText)
            for a in ACTIONS}


def save(chosen: dict[str, QKeySequence]) -> None:
    prefs = QSettings()
    for a in ACTIONS:
        seq = chosen.get(a, QKeySequence())
        prefs.setValue(f"shortcuts/{a}", seq.toString(QKeySequence.SequenceFormat.PortableText))
    prefs.setValue("shortcuts/offered", True)


def offered() -> bool:
    return QSettings().value("shortcuts/offered", False, type=bool)
