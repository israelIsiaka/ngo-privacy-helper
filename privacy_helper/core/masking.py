"""Find personal details in text, replace them with tokens, and put them back.

The same real value always gets the same token within a session, so an AI
model can still follow who is who: "[PERSON_1] lives with [PERSON_2]".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pii import KINDS, PATTERN_KINDS, find_clues, find_patterns, find_sensitive

# Source decides who wins when two detections overlap, and what is ticked by default.
SOURCE_KNOWN = "known"          # from the NGO's own records or always-hide list
SOURCE_PATTERN = "pattern"      # fixed-shape details such as phone numbers
SOURCE_MANUAL = "manual"        # staff selected it by hand
SOURCE_SUGGESTED = "suggested"  # looks like a name; staff must confirm
SOURCE_CLUE = "clue"            # description that may point to one person; staff decide
SOURCE_TOPIC = "topic"          # protected topic such as health or religion; staff decide
# A clue beats a topic inside it ("the only blind woman" over "blind"): hiding the clue hides both.
_PRIORITY = {SOURCE_MANUAL: 0, SOURCE_KNOWN: 1, SOURCE_PATTERN: 2, SOURCE_SUGGESTED: 3, SOURCE_CLUE: 4,
             SOURCE_TOPIC: 5}

_HONORIFIC = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Mallam|Malam|Alhaji|Alhaja|Hajiya|Chief|Pastor|Rev|"
    r"Madam|Mama|Baba|Barr|Engr|Prof)\.?\s+((?:[A-Z][a-z'’-]+)(?:[ \t]+[A-Z][a-z'’-]+){0,2})"
)
_INTRO = re.compile(
    r"\b(?:my name is|named|called|name:)\s+((?:[A-Z][a-z'’-]+)(?:[ \t]+[A-Z][a-z'’-]+){0,2})",
    re.IGNORECASE,
)
# Two to four capitalised words in a row ("Hadiza Ibrahim", "The Kano Office").
_CAPS_RUN = re.compile(r"\b[A-Z][a-z'’-]+(?:[ \t]+[A-Z][a-z'’-]+){1,3}\b")
# Capitalised only because they start a sentence; dropped from the front of a run.
_LEADING = {"the", "a", "an", "this", "that", "these", "those", "she", "he", "they", "we", "our", "her", "his",
            "their", "my", "your", "on", "in", "at", "from", "to", "for", "with", "after", "before", "when",
            "dear", "please", "today", "yesterday", "monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday", "and", "but", "if", "so"}

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
    label: str = ""       # what found it, shown to staff ("Phone number", "Health")


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
        self._known_rx: re.Pattern | None = None
        for term, kind in (known or {}).items():
            self.add_known(term, kind)

    def add_known(self, term: str, kind: str) -> None:
        term = " ".join(term.split())
        if len(term) >= 2 and _norm(term) not in self.never:
            self.known.setdefault(term, kind)
        self._known_rx = None
        # A person's first name or surname on its own ("Hadiza said...") is also hidden.
        if kind == "PERSON":
            for part in term.split():
                if len(part) >= 3 and _norm(part) not in self.never:
                    self.known.setdefault(part, kind)

    def _known_regex(self) -> re.Pattern | None:
        # Compiled once per set of terms: a spreadsheet can add thousands of names.
        if self._known_rx is None and self.known:
            terms = sorted(self.known, key=len, reverse=True)
            self._known_rx = re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in terms) + r")(?!\w)",
                                        re.IGNORECASE)
        return self._known_rx

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
                found.append(Detection(m.start(), m.end(), word, kind, SOURCE_KNOWN, label="From your records"))

        for start, end, value, kind, label in find_patterns(text, self.patterns):
            found.append(Detection(start, end, value, kind, SOURCE_PATTERN, label=label))
        if "SENSITIVE" in self.patterns:
            for start, end, value, topic in find_sensitive(text):
                found.append(Detection(start, end, value, "SENSITIVE", SOURCE_TOPIC, False, topic))
        if "DESCRIPTION" in self.patterns:
            for start, end, value, label in find_clues(text):
                found.append(Detection(start, end, value, "DESCRIPTION", SOURCE_CLUE, False, label))

        if self.suggest_names:
            for rx in (_HONORIFIC, _INTRO):
                for m in rx.finditer(text):
                    found.append(Detection(m.start(1), m.end(1), m.group(1), "PERSON", SOURCE_SUGGESTED,
                                           label="Name after a title"))
            # Other capitalised runs are listed unticked: staff decide.
            for m in _CAPS_RUN.finditer(text):
                start, words = m.start(), m.group(0).split()
                while words and words[0].casefold() in _LEADING:
                    start = text.index(words[1], start + len(words[0])) if len(words) > 1 else m.end()
                    words = words[1:]
                if len(words) >= 2 and len(words[0]) >= 3:
                    found.append(Detection(start, m.end(), text[start:m.end()], "PERSON", SOURCE_SUGGESTED, False,
                                           "Possible name"))

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
