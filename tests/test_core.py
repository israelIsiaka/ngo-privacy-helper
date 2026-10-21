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
    for secret in ("Hadiza", "0803 555 1234", "hadiza@example.org", "Zamfara", "Musa Garba", "12345678901", "12/03/1990"):
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
