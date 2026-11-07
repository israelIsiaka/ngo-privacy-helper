import pytest
from PySide6.QtWidgets import QMessageBox


@pytest.fixture(autouse=True)
def no_message_boxes(monkeypatch):
    """A message box waits for a click that never comes in CI. Fail with its text instead."""
    def fail(parent, title, text, *a, **k):
        raise AssertionError(f"Unexpected message box '{title}': {text}")
    for kind in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(fail))
