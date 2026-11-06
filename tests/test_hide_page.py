import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog  # noqa: E402

from privacy_helper.core import documents  # noqa: E402
from privacy_helper.core.vault import Vault  # noqa: E402
from privacy_helper.ui import hide_page  # noqa: E402

app = QApplication.instance() or QApplication([])


def _page(tmp_path: Path) -> hide_page.HidePage:
    vault = Vault(tmp_path / "keys.vault")
    vault.create("long enough password")
    return hide_page.HidePage(vault)


def test_safe_file_is_saved_as_the_same_type(tmp_path: Path, monkeypatch):
    """Staff upload the safe file to their AI tool, so an Excel file must come back as Excel, Word as Word."""
    from docx import Document
    from openpyxl import Workbook, load_workbook
    xlsx = tmp_path / "register.xlsx"
    wb = Workbook()
    wb.active.append(["Full Name", "Phone", "Age"])
    wb.active.append(["Hadiza Ibrahim", "0803 555 1234", "36"])
    wb.save(xlsx)
    docx = tmp_path / "report.docx"
    doc = Document()
    doc.add_paragraph("Mrs Hadiza Ibrahim (0803 555 1234) needs water.")
    doc.save(str(docx))

    monkeypatch.setattr(hide_page.ColumnsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda parent, title, start, filt: (asked.append(start) or start, "")))
    page = _page(tmp_path)

    page.open_path(xlsx)
    assert page.save_btn.text() == "Save as Excel File…"
    page.save_safe()
    assert asked[-1].endswith("register (safe).xlsx")
    rows = list(load_workbook(tmp_path / "register (safe).xlsx").active.values)
    assert rows[0] == ("Full Name", "Phone", "Age") and "Hadiza" not in str(rows) and "0803" not in str(rows)

    page.open_path(docx)
    assert page.save_btn.text() == "Save as Word File…"
    page.save_safe()
    text = documents.read_docx_text(tmp_path / "report (safe).docx")
    assert "[PERSON_1]" in text and "Hadiza" not in text and "0803" not in text


def test_column_titles_are_not_listed_as_names(tmp_path: Path, monkeypatch):
    csv_file = tmp_path / "people.csv"
    csv_file.write_text("Full Name,Health Condition,Notes\nHadiza Ibrahim,Diabetes,visited by Amina Yusuf\n",
                        encoding="utf-8")
    monkeypatch.setattr(hide_page.ColumnsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page = _page(tmp_path)
    page.open_path(csv_file)
    found = {d.text for d in page.detections}
    assert "Full Name" not in found and "Health Condition" not in found
    assert {"Hadiza Ibrahim", "Amina Yusuf"} <= found


def test_ai_reply_files_are_restored_and_saved_as_the_same_type(tmp_path: Path, monkeypatch):
    """The AI hands back a Word or Excel file; restoring gives the same type with the real details in it."""
    from docx import Document
    from openpyxl import Workbook, load_workbook

    from privacy_helper.core.vault import KIND_MASK
    from privacy_helper.ui import restore_page
    vault = Vault(tmp_path / "keys.vault")
    vault.create("long enough password")
    vault.add(KIND_MASK, "register", mapping={"PERSON_1": "Hadiza Ibrahim", "PLACE_1": "Block C, Gusau"})
    xlsx = tmp_path / "reply.xlsx"
    wb = Workbook()
    wb.active.append(["Name", "Address", "Next step"])
    wb.active.append(["[PERSON_1]", "[PLACE_1]", "Visit [PERSON_1]"])
    wb.save(xlsx)
    docx = tmp_path / "letter.docx"
    doc = Document()
    doc.add_paragraph("Dear [PERSON_1], we will visit you at [PLACE_1].")
    doc.save(str(docx))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda parent, title, start, filt: (start, "")))
    page = restore_page.RestorePage(vault)
    page.reload_sessions()

    page.load_file([xlsx])
    page.do_restore()
    assert page.save_btn.text() == "Save as Excel File…"
    page.save()
    rows = list(load_workbook(tmp_path / "reply (restored).xlsx").active.values)
    assert rows[1] == ("Hadiza Ibrahim", "Block C, Gusau", "Visit Hadiza Ibrahim")   # the comma stays in its cell

    page.load_file([docx])
    page.do_restore()
    assert page.save_btn.text() == "Save as Word File…"
    page.save()
    assert documents.read_docx_text(tmp_path / "letter (restored).docx") == \
        "Dear Hadiza Ibrahim, we will visit you at Block C, Gusau."


def test_several_sheets_ask_which_one(tmp_path: Path, monkeypatch):
    """Staff must choose, not silently get the first sheet. Cancelling opens nothing."""
    from openpyxl import Workbook
    from PySide6.QtWidgets import QInputDialog
    xlsx = tmp_path / "book.xlsx"
    wb = Workbook()
    wb.active.append(["Full Name"])
    wb.active.append(["Hadiza Ibrahim"])
    wb.create_sheet("Staff").append(["Full Name"])
    wb["Staff"].append(["Musa Bello"])
    wb.save(xlsx)
    monkeypatch.setattr(hide_page.ColumnsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page = _page(tmp_path)

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    page.open_path(xlsx)
    assert page.table is None

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Staff", True)))
    page.open_path(xlsx)
    assert page.table.rows == [["Musa Bello"]]
