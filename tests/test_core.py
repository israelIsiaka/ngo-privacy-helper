from pathlib import Path

import pytest

from privacy_helper.core import documents, filecrypt, masking, pdflock
from privacy_helper.core.vault import KIND_FILE, Vault, VaultError, WrongPassword

NOTE = ("Hadiza Ibrahim (0803 555 1234, hadiza@example.org) at Zamfara Shelter needs water. "
        "Hadiza said Mallam Musa Garba visited. NIN 12345678901, born 12/03/1990. "
        "Blessing and hope.")


def test_mask_and_restore_round_trip():
    det = masking.Detector({"Hadiza Ibrahim": "PERSON", "Zamfara Shelter": "PLACE", "Blessing Okafor": "PERSON"})
    session = masking.Session()
    masked = masking.mask_text(NOTE, det, session)
    secrets = ("Hadiza", "0803 555 1234", "hadiza@example.org", "Zamfara", "Musa Garba", "12345678901", "12/03/1990")
    for secret in secrets:
        assert secret not in masked, secret
    assert "[PERSON_1]" in masked and "[PLACE_1]" in masked
    assert "Blessing and hope" not in masked     # capitalised name is hidden...
    assert "hope." in masked                      # ...ordinary word is not
    restored, n = masking.restore(masked, session.mapping)
    assert restored == NOTE and n >= 8


def test_restore_accepts_ai_variations():
    mapping = {"PERSON_1": "Hadiza Ibrahim", "PLACE_2": "Kano"}
    text, n = masking.restore("Dear [Person 1] in PLACE_2, see [PERSON_9].", mapping)
    assert text == "Dear Hadiza Ibrahim in Kano, see [PERSON_9]." and n == 2


def test_names_at_sentence_start_are_suggested():
    found = {d.text: d.enabled for d in masking.Detector().find("Hadiza Ibrahim needs water. The Kano Office called.")}
    assert found == {"Hadiza Ibrahim": False, "Kano Office": False}   # listed, staff decide


def test_never_hide_list_wins():
    det = masking.Detector({"Startbench": "OTHER"}, never=["Startbench"])
    assert det.find("Startbench helps") == []


def test_same_value_same_token():
    s = masking.Session()
    assert s.token_for("PERSON", "Amina  Yusuf") == s.token_for("PERSON", "amina yusuf") == "PERSON_1"
    assert s.token_for("PERSON", "John") == "PERSON_2"


def test_table_columns_are_guessed_and_masked(tmp_path: Path):
    csv_file = tmp_path / "cases.csv"
    csv_file.write_text("Case_id,Full_name,Age,Location,message\n"
                        "1001,Maryam Muhammad,34,Kano Shelter,Maryam needs school for two children\n",
                        encoding="utf-8-sig")
    table = documents.read_table(csv_file)
    roles = {c.name: (c.role, c.kind) for c in table.columns}
    assert roles["Full_name"] == (documents.HIDE, "PERSON")
    assert roles["Location"] == (documents.HIDE, "PLACE")
    assert roles["Age"][0] == documents.KEEP
    assert roles["message"][0] == documents.SCAN
    det = masking.Detector()
    documents.add_known_terms(table, det)
    safe = masking.mask_text(documents.table_to_text(table.headers, table.rows), det, masking.Session())
    assert "Maryam" not in safe and "Kano Shelter" not in safe and "[PERSON_1]" in safe


def test_file_encrypt_decrypt_and_tamper(tmp_path: Path):
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF" + bytes(range(256)) * 9000)   # > 2 chunks
    key, key_id = filecrypt.new_key(), "ab" * 16
    enc = filecrypt.encrypt_file(src, tmp_path, key_id, key)
    assert filecrypt.read_key_id(enc) == key_id
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert filecrypt.decrypt_file(enc, out_dir, key).read_bytes() == src.read_bytes()

    with pytest.raises(filecrypt.DecryptError):
        filecrypt.decrypt_file(enc, out_dir, filecrypt.new_key())
    data = enc.read_bytes()
    enc.write_bytes(data[:-50])                                   # cut short
    with pytest.raises(filecrypt.DecryptError):
        filecrypt.decrypt_file(enc, out_dir, key)
    assert not list(out_dir.glob("*.part"))


def test_empty_file(tmp_path: Path):
    src = tmp_path / "empty.txt"
    src.write_bytes(b"")
    key = filecrypt.new_key()
    enc = filecrypt.encrypt_file(src, tmp_path, "cd" * 16, key)
    (tmp_path / "o").mkdir()
    assert filecrypt.decrypt_file(enc, tmp_path / "o", key).read_bytes() == b""


def test_key_text_round_trip():
    key = filecrypt.new_key()
    assert filecrypt.parse_key(filecrypt.export_key("ef" * 16, key)) == ("ef" * 16, key)
    with pytest.raises(ValueError):
        filecrypt.parse_key("NPHKEY1:abc:def")


def test_pdf_lock_unlock(tmp_path: Path):
    from pypdf import PdfWriter
    src = tmp_path / "letter.pdf"
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.write(str(src))
    password = pdflock.new_password()
    locked = pdflock.lock_pdf(src, tmp_path, password)
    assert pdflock.is_locked(locked)
    with pytest.raises(pdflock.PdfError):
        pdflock.unlock_pdf(locked, tmp_path, ["wrong"])
    unlocked = pdflock.unlock_pdf(locked, tmp_path, ["wrong", password])
    assert not pdflock.is_locked(unlocked) and unlocked.name == "letter (unlocked).pdf"


def test_vault(tmp_path: Path):
    path = tmp_path / "vault.json"
    v = Vault(path)
    with pytest.raises(VaultError):
        v.create("short")
    v.create("correct horse battery")
    entry = v.add(KIND_FILE, "report.pdf", secret="abc")
    v.lock()
    with pytest.raises(WrongPassword):
        v.unlock("wrong password!!")
    v.unlock("correct horse battery")
    assert v.get(entry.id).label == "report.pdf"
    v.change_password("correct horse battery", "a new long password")
    v.lock()
    v.unlock("a new long password")
    assert len(v.entries) == 1


def test_password_change_leaves_no_copy_openable_with_old_password(tmp_path: Path):
    v = Vault(tmp_path / "keys.vault")
    v.create("old password here")
    v.add(KIND_FILE, "a.pdf", secret="x")
    v.change_password("old password here", "new password here")
    previous = Vault(tmp_path / "keys.previous")
    with pytest.raises(WrongPassword):
        previous.unlock("old password here")
    previous.unlock("new password here")


def test_expired_keys_are_destroyed_everywhere(tmp_path: Path):
    from datetime import date, timedelta

    from privacy_helper.core.vault import KIND_MASK
    v = Vault(tmp_path / "keys.vault")
    v.create("long enough password")
    v.settings.mask_days = 30
    old = v.add(KIND_MASK, "case note", mapping={"PERSON_1": "Hadiza Ibrahim"})
    kept = v.add(KIND_FILE, "report.pdf", secret="x")          # file_days is 0: kept until deleted
    assert old.expires == (date.today() + timedelta(days=30)).isoformat() and kept.expires == ""
    assert v.purge_expired(date.today()) == []
    assert v.purge_expired(date.today() + timedelta(days=30)) == ["case note"]
    assert [e.id for e in v.entries] == [kept.id]
    for copy in (v.path, v.path.with_suffix(".previous")):     # the crash-guard copy forgets it too
        probe = Vault(copy)
        probe.unlock("long enough password")
        assert probe.get(old.id) is None


def test_tampered_password_settings_are_refused(tmp_path: Path):
    import json
    v = Vault(tmp_path / "keys.vault")
    v.create("long enough password")
    for n in (2, 2**30):    # too weak to protect the keys / more memory than any laptop has
        outer = json.loads(v.path.read_text())
        outer["kdf"]["n"] = n
        v.path.write_text(json.dumps(outer))
        with pytest.raises(VaultError):
            Vault(v.path).unlock("long enough password")


def test_vault_is_private_to_the_user(tmp_path: Path):
    import os
    import stat
    v = Vault(tmp_path / "keys.vault")
    v.create("long enough password")
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(v.path).st_mode) == 0o600


def test_encrypted_name_cannot_escape_output_folder():
    for evil in ("../../etc/passwd", "..\\..\\Windows\\win.ini", "..", "", "/abs/x.txt"):
        name = filecrypt._safe_name(evil)
        assert "/" not in name and "\\" not in name and name not in ("", ".", "..")


def test_rows_that_still_stand_out_are_counted(tmp_path: Path):
    csv_file = tmp_path / "people.csv"
    rows = ["Name,Age,Sex,Children"] + [f"Person {i},30,F,2" for i in range(4)] + ["Amina Bello,71,F,7"]
    csv_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    table = documents.read_table(csv_file)
    assert table.columns[0].role == documents.HIDE
    rare, columns = documents.rare_rows(table)
    assert rare == 1 and set(columns) == {"Age", "Sex", "Children"}   # only the 71-year-old stands out
    table.columns[1].role = documents.HIDE                       # hiding Age is not enough...
    assert documents.rare_rows(table)[0] == 1                    # ...she is the only one with 7 children
    table.columns[3].role = documents.HIDE
    assert documents.rare_rows(table) == (0, ["Sex"])


def test_names_stop_at_the_end_of_the_line():
    found = [d.text for d in masking.Detector().find("Name: Mrs Hadiza Ibrahim\nPhone: 0803 555 1234\n"
                                                     "Called Amina Yusuf\nAddress: Block C")]
    assert found == ["Mrs Hadiza Ibrahim", "0803 555 1234", "Amina Yusuf"]


def test_word_files_without_a_header_are_read(tmp_path: Path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("Hadiza Ibrahim needs water.")
    doc.save(str(tmp_path / "plain.docx"))
    doc.sections[0].header.paragraphs[0].text = "Hope Bridge Foundation"
    doc.save(str(tmp_path / "header.docx"))
    plain = Document(str(tmp_path / "plain.docx"))
    assert [p.text for p in documents._docx_paragraphs(plain)] == ["Hadiza Ibrahim needs water."]
    assert plain.sections[0].header.is_linked_to_previous      # reading did not add a header
    assert "Hope Bridge Foundation" in documents.read_docx_text(tmp_path / "header.docx")


def test_sentence_start_verbs_are_not_part_of_a_name():
    text = "Met Amina Yusuf at the clinic. Visited Musa Garba. Spoke To Hadiza Ibrahim. Grace Adeyemi came."
    found = [d.text for d in masking.Detector().find(text)]
    assert found == ["Amina Yusuf", "Musa Garba", "Hadiza Ibrahim", "Grace Adeyemi"]


def test_a_name_ticked_once_is_hidden_everywhere():
    text = ("The caseworker visited with Hajiya Fatima Bello. Name: Mrs Hadiza Ibrahim\n"
            "Need,Who\nDisability support,Fatima Bello\nHealth,Hadiza Ibrahim\n")
    found = masking.Detector().find(text)
    assert {d.text: d.enabled for d in found if "Bello" in d.text or "Hadiza" in d.text} == \
        {"Fatima Bello": True, "Mrs Hadiza Ibrahim": True, "Hadiza Ibrahim": True}
    safe = masking.apply(text, found, masking.Session())
    assert "Bello" not in safe and "Hadiza" not in safe
