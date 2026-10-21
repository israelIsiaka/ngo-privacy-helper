"""Read the files staff bring (text, CSV, Excel, Word) and write masked copies.

Spreadsheets have no fixed layout: staff choose, per column, whether the whole
value is a detail to hide, whether the text in it should be scanned, or neither.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .masking import Detector

TEXT_TYPES = {".txt", ".md"}
TABLE_TYPES = {".csv", ".xlsx"}
WORD_TYPES = {".docx"}
SUPPORTED = TEXT_TYPES | TABLE_TYPES | WORD_TYPES

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


def read_table(path: Path) -> Table:
    path = Path(path)
    try:
        if path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook
            sheet = load_workbook(path, read_only=True, data_only=True).worksheets[0]
            grid = [["" if v is None else str(v) for v in row] for row in sheet.iter_rows(values_only=True)]
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
def _docx_paragraphs(doc):
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for section in doc.sections:
        for part in (section.header, section.footer):
            yield from part.paragraphs


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


def load_any_text(path: Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in WORD_TYPES:
        return read_docx_text(path)
    if suffix in TEXT_TYPES:
        return read_text_file(path)
    raise FileReadError(f"{Path(path).name}: this type of file is not supported here.")
