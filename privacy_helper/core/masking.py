"""Find personal details in text, replace them with tokens, and put them back.

The same real value always gets the same token within a session, so an AI
model can still follow who is who: "[PERSON_1] lives with [PERSON_2]".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Kinds of detail, in the order they are shown to staff.
KINDS = {
    "PERSON": "Person",
    "PLACE": "Place",
    "PHONE": "Phone",
    "EMAIL": "Email",
    "ID": "ID number",
    "ACCOUNT": "Account number",
    "DATE": "Date",
    "OTHER": "Other",
}

# Source decides who wins when two detections overlap, and what is ticked by default.
SOURCE_KNOWN = "known"          # from the NGO's own records or always-hide list
SOURCE_PATTERN = "pattern"      # fixed-shape details such as phone numbers
SOURCE_MANUAL = "manual"        # staff selected it by hand
SOURCE_SUGGESTED = "suggested"  # looks like a name; staff must confirm
_PRIORITY = {SOURCE_MANUAL: 0, SOURCE_KNOWN: 1, SOURCE_PATTERN: 2, SOURCE_SUGGESTED: 3}

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# Nigerian mobile numbers (0803 555 1234, +234 803 555 1234) and general
# international or grouped numbers (555-123-4567, +44 20 7946 0958).
_PHONE = re.compile(
    r"(?<![\w+])(?:"
    r"(?:\+?234[\s.-]?|0)[789][01]\d(?:[\s.-]?\d){7}"
    r"|\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,5}"
    r"|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"
    r")(?!\w)"
)
_ID_11 = re.compile(r"(?<![\w.])\d{11}(?!\w|\.\d)")      # NIN, BVN
_ACCOUNT_10 = re.compile(r"(?<![\w.])\d{10}(?!\w|\.\d)")  # NUBAN bank account
_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
           r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DATE = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})"
    r"|\d{4}-\d{2}-\d{2}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}"
    rf"|{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})\b",
    re.IGNORECASE,
)
_HONORIFIC = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Mallam|Malam|Alhaji|Alhaja|Hajiya|Chief|Pastor|Rev|"
    r"Madam|Mama|Baba|Barr|Engr|Prof)\.?\s+((?:[A-Z][a-z'’-]+)(?:\s+[A-Z][a-z'’-]+){0,2})"
)
_INTRO = re.compile(
    r"\b(?:my name is|named|called|name:)\s+((?:[A-Z][a-z'’-]+)(?:\s+[A-Z][a-z'’-]+){0,2})",
    re.IGNORECASE,
)
# Two or three capitalised words in a row, not at the start of a sentence.
_CAPS_RUN = re.compile(r"(?<=[a-z,;:)]\s)([A-Z][a-z'’-]{2,}(?:\s+[A-Z][a-z'’-]{2,}){1,2})")

PATTERN_KINDS = ("EMAIL", "PHONE", "ID", "ACCOUNT", "DATE")

_TOKEN = re.compile(r"\[\s*(" + "|".join(KINDS) + r")[ _](\d+)\s*\]|\b(" + "|".join(KINDS) + r")_(\d+)\b",
                    re.IGNORECASE)


@dataclass
class Detection:
    start: int
    end: int
    text: str
    kind: str
    source: str
    enabled: bool = True


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass
class Session:
    """Tokens handed out so far. Saved (encrypted) so replies can be restored later."""

    mapping: dict[str, str] = field(default_factory=dict)   # "PERSON_1" -> "Hadiza Ibrahim"
    _by_value: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for token, value in self.mapping.items():
            self._by_value[(token.rsplit("_", 1)[0], _norm(value))] = token

    def token_for(self, kind: str, value: str) -> str:
        key = (kind, _norm(value))
        if key not in self._by_value:
            n = 1 + sum(1 for t in self.mapping if t.rsplit("_", 1)[0] == kind)
            token = f"{kind}_{n}"
            self._by_value[key] = token
            self.mapping[token] = value
        return self._by_value[key]


class Detector:
    """Finds details using known terms, fixed patterns and (optionally) name suggestions."""

    def __init__(self, known: dict[str, str] | None = None, never: list[str] | None = None,
                 patterns: tuple[str, ...] = PATTERN_KINDS, suggest_names: bool = True):
        self.never = {_norm(w) for w in (never or []) if w.strip()}
        self.patterns = set(patterns)
        self.suggest_names = suggest_names
        self.known: dict[str, str] = {}
        for term, kind in (known or {}).items():
            self.add_known(term, kind)

    def add_known(self, term: str, kind: str) -> None:
        term = " ".join(term.split())
        if len(term) >= 2 and _norm(term) not in self.never:
            self.known.setdefault(term, kind)
        # A person's first name or surname on its own ("Hadiza said...") is also hidden.
        if kind == "PERSON":
            for part in term.split():
                if len(part) >= 3 and _norm(part) not in self.never:
                    self.known.setdefault(part, kind)

    def _known_regex(self) -> re.Pattern | None:
        if not self.known:
            return None
        terms = sorted(self.known, key=len, reverse=True)
        return re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in terms) + r")(?!\w)", re.IGNORECASE)

    def find(self, text: str) -> list[Detection]:
        found: list[Detection] = []
        rx = self._known_regex()
        if rx:
            lookup = {_norm(t): k for t, k in self.known.items()}
            for m in rx.finditer(text):
                kind, word = lookup[_norm(m.group(0))], m.group(0)
                # Names such as Blessing or Hope are also ordinary words: only hide them capitalised.
                if kind == "PERSON" and " " not in word and not word[0].isupper():
                    continue
                found.append(Detection(m.start(), m.end(), word, kind, SOURCE_KNOWN))

        checks = [("EMAIL", _EMAIL), ("PHONE", _PHONE), ("ID", _ID_11), ("ACCOUNT", _ACCOUNT_10), ("DATE", _DATE)]
        for kind, rx in checks:
            if kind in self.patterns:
                found += [Detection(m.start(), m.end(), m.group(0), kind, SOURCE_PATTERN) for m in rx.finditer(text)]

        if self.suggest_names:
            for rx, enabled in ((_HONORIFIC, True), (_INTRO, True), (_CAPS_RUN, False)):
                for m in rx.finditer(text):
                    found.append(Detection(m.start(1), m.end(1), m.group(1), "PERSON", SOURCE_SUGGESTED, enabled))

        found = [d for d in found if _norm(d.text) not in self.never]
        return resolve_overlaps(found)


def resolve_overlaps(found: list[Detection]) -> list[Detection]:
    """Keep one detection per stretch of text: best source, then ticked, then the longest."""
    found.sort(key=lambda d: (_PRIORITY[d.source], not d.enabled, -(d.end - d.start), d.start))
    taken: list[Detection] = []
    for d in found:
        if all(d.end <= t.start or d.start >= t.end for t in taken):
            taken.append(d)
    return sorted(taken, key=lambda d: d.start)


def apply(text: str, detections: list[Detection], session: Session) -> str:
    """Replace every enabled detection with its token."""
    out, pos = [], 0
    for d in sorted(detections, key=lambda d: d.start):
        if not d.enabled:
            continue
        out.append(text[pos:d.start])
        out.append(f"[{session.token_for(d.kind, d.text)}]")
        pos = d.end
    out.append(text[pos:])
    return "".join(out)


def restore(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Put real values back. Accepts "[PERSON_1]", "[Person 1]" and "PERSON_1",
    because AI tools do not always copy tokens exactly. Returns (text, count)."""
    count = 0

    def swap(m: re.Match) -> str:
        nonlocal count
        kind, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = mapping.get(f"{kind.upper()}_{num}")
        if value is None:
            return m.group(0)
        count += 1
        return value

    return _TOKEN.sub(swap, text), count


def mask_text(text: str, detector: Detector, session: Session) -> str:
    return apply(text, [d for d in detector.find(text) if d.enabled], session)
