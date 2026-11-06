"""Read the files staff bring (text, CSV, Excel, Word) and write masked copies.

Spreadsheets have no fixed layout: staff choose, per column, whether the whole
value is a detail to hide, whether the text in it should be scanned, or neither.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .masking import Detector

TEXT_TYPES = {".txt", ".md"}
TABLE_TYPES = {".csv", ".xlsx"}
WORD_TYPES = {".docx"}
PDF_TYPES = {".pdf"}
SUPPORTED = TEXT_TYPES | TABLE_TYPES | WORD_TYPES | PDF_TYPES

# Column roles
HIDE = "hide"   # whole value is a detail
SCAN = "scan"   # free text: look for details inside it
KEEP = "keep"   # leave as is

_HEADER_HINTS = [
    (r"name|beneficiary|client|surname|first|last|guardian|parent|spouse|contact person", "PERSON"),
    (r"phone|mobile|tel|whatsapp|gsm", "PHONE"),
    (r"e-?mail", "EMAIL"),
    (r"address|location|village|camp|shelter|lga|ward|town|city|street|house", "PLACE"),
    (r"\bnin\b|bvn|passport|national id|id ?(no|number)|card", "ID"),
    (r"account|iban|nuban", "ACCOUNT"),
    (r"birth|dob", "DATE"),
    (r"religion|faith|ethnic|tribe|diagnos|health|medical|disabilit|hiv|condition|illness|treatment|"
     r"sexual|orientation|gbv|incident|criminal|conviction|asylum|immigration|biometric|fingerprint", "SENSITIVE"),
    (r"card no|card number|pan\b", "CARD"),
    (r"plate|vehicle|car reg", "VEHICLE"),
    (r"gps|coordinates|latitude|longitude|lat\b|lng\b|lon\b", "PLACE"),
    (r"facebook|twitter|instagram|tiktok|handle|social|website|url|\bip\b", "ONLINE"),
]
_SCAN_HINTS = r"note|message|comment|description|story|narrative|details|remarks|summary|complaint|request"


class FileReadError(Exception):
    pass


@dataclass
class Column:
    name: str
    role: str = KEEP
    kind: str = "OTHER"


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    columns: list[Column] = field(default_factory=list)


def read_text_file(path: Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _sheet_grid(sheet) -> list[list[str]]:
    return [["" if v is None else str(v) for v in row] for row in sheet.iter_rows(values_only=True)]


def sheet_names(path: Path) -> list[str]:
    """The sheets of an Excel file that have something in them, hidden sheets included."""
    path = Path(path)
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return [s.title for s in wb.worksheets if any(c.strip() for r in _sheet_grid(s) for c in r)]
        finally:
            wb.close()
    except Exception as exc:  # openpyxl raises many types for damaged files
        raise FileReadError(f"{path.name} could not be read: {exc}") from None


def read_table(path: Path, sheet: str | None = None) -> Table:
    """Read a CSV or one Excel sheet: the one named, otherwise the first with something in it."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx" and sheet is None:
        sheet = next(iter(sheet_names(path)), None)
        if sheet is None:
            raise FileReadError(f"{path.name} is empty.")
    try:
        if path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                grid = _sheet_grid(wb[sheet])
            finally:
                wb.close()
        else:
            text = read_text_file(path)
            try:
                dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            grid = list(csv.reader(io.StringIO(text), dialect))
    except Exception as exc:  # openpyxl and csv raise many types for damaged files
        raise FileReadError(f"{path.name} could not be read: {exc}") from None
    grid = [r for r in grid if any(c.strip() for c in r)]
    if not grid:
        raise FileReadError(f"{path.name} is empty.")
    width = max(len(r) for r in grid)
    headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(grid[0] + [""] * (width - len(grid[0])))]
    rows = [r + [""] * (width - len(r)) for r in grid[1:]]
    table = Table(headers, rows)
    table.columns = [suggest_column(h, [r[i] for r in rows]) for i, h in enumerate(headers)]
    return table


def suggest_column(header: str, values: list[str]) -> Column:
    """Guess what a column holds from its heading, then from its contents."""
    h = header.lower()
    for pattern, kind in _HEADER_HINTS:
        if re.search(pattern, h):
            return Column(header, HIDE, kind)
    sample = [v for v in values[:200] if v.strip()]
    if sample:
        probe = Detector(suggest_names=False)
        hits = {}
        for v in sample:
            for d in probe.find(v):
                if d.end - d.start >= len(v.strip()) - 2:
                    hits[d.kind] = hits.get(d.kind, 0) + 1
        if hits:
            kind, count = max(hits.items(), key=lambda kv: kv[1])
            if count >= len(sample) / 2:
                return Column(header, HIDE, kind)
        if re.search(_SCAN_HINTS, h) or sum(len(v) for v in sample) / len(sample) > 40:
            return Column(header, SCAN, "OTHER")
    return Column(header, KEEP, "OTHER")


RARE_BELOW = 3   # a mix of details shared by fewer people than this can single someone out


def rare_rows(table: Table) -> tuple[int, list[str]]:
    """Rows that are still one of a kind once names are hidden, judged by the short columns left visible
    (age, sex, ward, disability...). Returns how many rows, and the columns that make them stand out most.

    ponytail: a plain count of matching rows (k-anonymity with k=3), not a full disclosure-risk model
    like sdcMicro. Enough to warn staff; the fix is theirs to choose."""
    cols = [i for i, c in enumerate(table.columns)
            if c.role == KEEP and table.rows and sum(len(r[i]) for r in table.rows) / len(table.rows) <= 30]
    if not cols:
        return 0, []

    def key(row: list[str]) -> tuple[str, ...]:
        return tuple(" ".join(row[i].split()).casefold() for i in cols)
    counts = Counter(key(r) for r in table.rows)
    rare = sum(1 for r in table.rows if counts[key(r)] < RARE_BELOW)
    # The columns with the most different values do the most to single people out.
    spread = sorted(cols, key=lambda i: len({r[i].strip().casefold() for r in table.rows}), reverse=True)
    return rare, [table.headers[i] for i in spread[:3]]


def add_known_terms(table: Table, detector: Detector) -> None:
    """Every value in a hidden column is hidden wherever it appears, including in notes."""
    for i, col in enumerate(table.columns):
        if col.role == HIDE:
            for row in table.rows:
                if row[i].strip():
                    detector.add_known(row[i], col.kind)


def table_to_text(headers: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([headers] + rows)
    return buf.getvalue()


def save_table(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for r in rows:
            ws.append(r)
        wb.save(path)
    else:
        # utf-8-sig so Excel on Windows shows accented names correctly.
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows([headers] + rows)


# ---- Word -------------------------------------------------------------------
def _block_paragraphs(container):
    """Paragraphs in reading order, going into tables (and tables inside tables) where they stand."""
    for block in container.iter_inner_content():
        if not hasattr(block, "rows"):
            yield block
            continue
        seen = set()   # a merged cell is returned once for every row and column it spans
        for row in block.rows:
            for cell in row.cells:
                if cell._tc not in seen:
                    seen.add(cell._tc)
                    yield from _block_paragraphs(cell)


def _docx_paragraphs(doc):
    yield from _block_paragraphs(doc)
    for section in doc.sections:
        for part in (section.header, section.footer):
            # A linked part has no text of its own. Reading it anyway makes python-docx create one from a
            # template file the packaged app does not have.
            if not part.is_linked_to_previous:
                yield from _block_paragraphs(part)


def read_docx_text(path: Path) -> str:
    from docx import Document
    try:
        doc = Document(str(path))
    except Exception as exc:
        raise FileReadError(f"{Path(path).name} could not be read: {exc}") from None
    return "\n".join(p.text for p in _docx_paragraphs(doc))


def save_text_docx(dest: Path, text: str) -> None:
    """Write masked text into a brand-new Word file.

    ponytail: deliberately not an edited copy of the original. Originals can hide
    details in tracked changes, comments, footnotes and author properties; a fresh
    file cannot leak them. Formatting is lost, which an AI tool does not need."""
    from docx import Document
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.save(str(dest))


def save_text_pdf(dest: Path, text: str) -> None:
    """Write text into a brand-new PDF, for the same reason save_text_docx starts from a blank file.

    ponytail: text only, the original layout and images are not kept. Keeping the layout means editing
    the original in place (PyMuPDF redaction, AGPL); worth it only if staff need the PDF to look the same."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    writer = QPdfWriter(str(dest))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter)
    writer.setTitle("")
    writer.setCreator("")
    doc = QTextDocument()
    doc.setPlainText(text)
    # A page size makes Qt lay out the pages itself; without one it adds page numbers, which would pile up
    # in the text each time a file goes to the AI and back.
    page = writer.pageLayout().paintRectPoints()
    doc.setPageSize(QSizeF(page.width(), page.height()))
    doc.print_(writer)
    del writer   # the file is finished when the writer goes


def read_pdf_text(path: Path) -> str:
    """The text of every page. The safe copy is a fresh file (see save_text_pdf), so the original's
    metadata, attachments and form fields cannot leak.

    ponytail: no OCR, so a scanned PDF is refused rather than read; add OCR if staff mostly have scans."""
    from pypdf import PdfReader
    path = Path(path)
    try:
        reader = PdfReader(str(path))
        # Many PDFs are encrypted only to stop editing, with an empty password to open them.
        if reader.is_encrypted and not reader.decrypt(""):
            raise FileReadError(f"{path.name} is locked with a password. Open it in a PDF reader, save a copy "
                                "without the password, then open that copy here.")
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        # PDFs often store "fi" and "fl" as one ligature character, which would hide names like "Rufai".
        text = unicodedata.normalize("NFKC", text)
        # Some PDF writers place each word separately, which reads back as tabs: "0803\t555\t1234".
        text = re.sub(r"[ \t]+", " ", text)
        # A PDF breaks lines where its page ran out. Join a line to the next one when the sentence carries on,
        # so the text rewraps to the new page instead of leaving short lines. Emails and links stay on their own.
        text = re.sub(r"(?<=\S) ?\n(?=[a-z])(?!\S*[@/])", " ", text)
    except FileReadError:
        raise
    except Exception as exc:  # pypdf raises many types for damaged files
        raise FileReadError(f"{path.name} could not be read: {exc}") from None
    if not text.strip():
        raise FileReadError(f"{path.name} has no text this app can read. It may be a scan or a photo of a page. "
                            "Hide details in it with Safe Photos, or type the text out.")
    return text


def load_any_text(path: Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in PDF_TYPES:
        return read_pdf_text(path)
    if suffix in WORD_TYPES:
        return read_docx_text(path)
    if suffix in TEXT_TYPES:
        return read_text_file(path)
    raise FileReadError(f"{Path(path).name}: this type of file is not supported here.")
