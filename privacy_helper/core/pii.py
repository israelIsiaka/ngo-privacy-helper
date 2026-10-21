"""Catalogue of personal and protected data the app looks for.

Two groups:

* Identifiers: details that point to one person (names are handled in
  masking.py). Found by pattern, and checked where a check exists (card
  numbers by the Luhn check, IBANs by mod-97, IP addresses by range).
* Protected (special category) data: topics the law treats as sensitive
  under the Nigeria Data Protection Act 2023 (s. 30), GDPR Art. 9 and 10, and
  safeguarding practice. These are listed for staff to decide on, because the
  AI often needs the topic ("needs legal aid for an asylum case") once the
  person is hidden.

The README section "What counts as personal and protected data" mirrors this file.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass

# Kinds of detail, in the order they are shown to staff.
KINDS = {
    "PERSON": "Person",
    "PLACE": "Place or address",
    "PHONE": "Phone",
    "EMAIL": "Email",
    "ID": "ID number",
    "ACCOUNT": "Bank account",
    "CARD": "Payment card",
    "DATE": "Date",
    "VEHICLE": "Vehicle plate",
    "ONLINE": "Online identifier",
    "DESCRIPTION": "Identifying description",
    "SENSITIVE": "Protected topic",
    "OTHER": "Other",
}

# Pattern groups staff can switch on or off in Settings, by kind.
PATTERN_KINDS = ("PHONE", "EMAIL", "ID", "ACCOUNT", "CARD", "DATE", "PLACE", "VEHICLE", "ONLINE", "SENSITIVE",
                 "DESCRIPTION")


def _luhn(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _iban(value: str) -> bool:
    s = value.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def _ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (addr.is_loopback or addr.is_unspecified)


def _mixed(value: str) -> bool:
    """Long codes count only if they mix letters and digits (avoids ordinary words)."""
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


@dataclass(frozen=True)
class Pattern:
    kind: str
    label: str            # shown to staff as "Found by"
    regex: re.Pattern
    group: int = 0        # which group holds the detail itself
    check: Callable[[str], bool] | None = None


def _p(kind, label, pattern, flags=0, group=0, check=None) -> Pattern:
    return Pattern(kind, label, re.compile(pattern, flags), group, check)


_END = r"(?![\w@])"          # not followed by a word character
_NUM_END = r"(?!\w|\.\d)"    # a number may end a sentence
_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
           r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_ID_LABELS = (r"passport|driver'?s?\s+licen[cs]e|licen[cs]e|voter'?s?\s+card|PVC|VIN|NIN|BVN|TIN|SSN|NHS|"
              r"national\s+ID|ID\s+card|identity\s+card|UNHCR|refugee|asylum|alien|registration|reg|case|file|"
              r"reference|ref|member(?:ship)?|patient|hospital|clinic|MRN|medical\s+record|health\s+plan|"
              r"insurance|policy|student|staff|employee|beneficiary|household|tag|wristband|ration\s+card")

PATTERNS: list[Pattern] = [
    # ---- contact --------------------------------------------------------------
    _p("EMAIL", "Email address", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    _p("PHONE", "Phone number",
       r"(?<![\w+])(?:"
       r"(?:\+?234[\s.-]?|0)[789][01]\d(?:[\s.-]?\d){7}"        # Nigerian mobile
       r"|\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,5}"               # international
       r"|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"                    # 555-123-4567
       r")(?!\w)"),

    # ---- government and organisation IDs -----------------------------------------
    _p("ID", "NIN or BVN", r"(?<![\w.])\d{11}" + _NUM_END),
    _p("ID", "Labelled ID", r"\b(?:" + _ID_LABELS + r")\s*(?:no\.?|num(?:ber)?\.?|#|ID)?\s*[:#.\-]?\s*"
       r"([A-Z0-9](?:[A-Z0-9/-]*\d[A-Z0-9/-]*)(?<![/-]))", re.IGNORECASE, group=1,
       check=lambda v: len(v) >= 4 and not re.fullmatch(r"(?:19|20)\d\d", v)),   # "case 2024" is a year
    _p("ID", "Passport number", r"\b[A-Z]\d{8}\b"),                                   # Nigerian passport
    _p("ID", "Driver's licence", r"\b[A-Z]{3}\d{5}[A-Z]{2}\d{2}\b"),                  # Nigerian licence
    _p("ID", "Voter number", r"\b[0-9A-F]{19}\b", check=_mixed),                       # Nigerian VIN
    _p("ID", "Tax ID", r"\b\d{8}-\d{4}\b"),                                           # Nigerian TIN
    _p("ID", "Social Security number", r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    _p("ID", "National Insurance number", r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"),
    _p("ID", "Refugee or case number", r"\b\d{3}-\d{2}[A-Z]\d{5}\b|\b\d{3}-\d{8}\b"),    # UNHCR proGres styles

    # IMEIs pass the card check too, so the labelled form is listed first and wins.
    _p("ONLINE", "Phone IMEI", r"\bIMEI\s*(?:no\.?|number)?\s*[:#]?\s*(\d{15})\b", re.IGNORECASE, group=1),

    # ---- money -----------------------------------------------------------------
    _p("CARD", "Card number", r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])", check=_luhn),
    _p("ACCOUNT", "IBAN", r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b", check=_iban),
    _p("ACCOUNT", "Bank account (NUBAN)", r"(?<![\w.])\d{10}" + _NUM_END),

    # ---- dates -------------------------------------------------------------------
    _p("DATE", "Date",
       r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})"
       r"|\d{4}-\d{2}-\d{2}"
       rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}"
       rf"|{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})\b", re.IGNORECASE),

    # ---- places ------------------------------------------------------------------
    _p("PLACE", "Street address",
       r"\b(?:No\.?\s*)?\d{1,5}[A-Za-z]?,?\s+(?:[A-Z][\w'’-]+\s+){1,4}"
       r"(?:Street|St|Road|Rd|Avenue|Ave|Close|Crescent|Cres|Lane|Ln|Way|Drive|Dr|Estate|Layout|Quarters|"
       r"Boulevard|Blvd|Court|Ct|Place|Pl|Square|Sq)\b\.?"),
    _p("PLACE", "GPS coordinates", r"(?<![\d.])-?\d{1,2}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}(?!\d|\.\d)"),
    _p("PLACE", "UK postcode", r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b"),
    _p("PLACE", "US ZIP code", r"(?<=\b[A-Z]{2}\s)\d{5}(?:-\d{4})?\b"),
    _p("PLACE", "Plus code", r"\b[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3}\b"),

    # ---- vehicles ----------------------------------------------------------------
    _p("VEHICLE", "Vehicle plate", r"\b[A-Z]{3}[\s-]?\d{3}[\s-]?[A-Z]{2}\b"),          # Nigerian plate

    # ---- online ------------------------------------------------------------------
    _p("ONLINE", "Web link", r"\b(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:!?)\]]"),
    _p("ONLINE", "Social media handle", r"(?<![\w@.])@[A-Za-z0-9_](?:[A-Za-z0-9_.]{1,28}[A-Za-z0-9_])?" + _END),
    _p("ONLINE", "IP address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}\b",
       re.IGNORECASE, check=_ip),
    _p("ONLINE", "Device MAC address", r"\b(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}\b", re.IGNORECASE),
]

# Protected topics. Matched as whole words or phrases, case-insensitive.
SENSITIVE: dict[str, list[str]] = {
    "Health": [
        "HIV", "AIDS", "HIV positive", "antiretroviral", "ARV", "tuberculosis", "TB", "hepatitis", "cholera",
        "pregnant", "pregnancy", "miscarriage", "abortion", "stillbirth", "fistula", "VVF", "sickle cell",
        "STI", "STD", "syphilis", "gonorrhoea", "cancer", "diabetes", "epilepsy", "HIV status", "diagnosis",
        "diagnosed", "disability", "disabled", "blind", "deaf", "amputee", "wheelchair", "mental health",
        "depression", "anxiety", "PTSD", "trauma", "psychiatric", "psychosis", "schizophrenia", "bipolar",
        "suicide", "suicidal", "self-harm", "substance abuse", "addiction", "malnourished", "malnutrition",
        "medication", "prescription",
    ],
    "Sexual life or orientation": [
        "gay", "lesbian", "bisexual", "transgender", "LGBT", "LGBTQ", "LGBTQI", "LGBTQ+", "queer", "intersex",
        "homosexual", "sexual orientation", "gender identity", "sex worker", "sex work",
    ],
    "Violence and abuse": [
        "rape", "raped", "sexual assault", "sexual abuse", "sexually abused", "sexual violence", "defilement",
        "molested", "incest", "FGM", "female genital mutilation", "domestic violence", "GBV",
        "gender-based violence", "intimate partner violence", "child marriage", "forced marriage", "early marriage",
        "trafficking", "trafficked", "child labour", "abducted", "kidnapped", "torture", "survivor",
    ],
    "Religion or belief": [
        "Muslim", "Christian", "Catholic", "Anglican", "Pentecostal", "Islam", "Islamic", "Christianity",
        "Ahmadiyya", "Shia", "Shiite", "Sunni", "atheist", "traditional religion", "apostate",
    ],
    "Ethnic origin": [
        "Hausa", "Fulani", "Yoruba", "Igbo", "Kanuri", "Tiv", "Ijaw", "Ibibio", "Nupe", "Edo", "Urhobo", "Efik",
        "Berom", "Gwari", "Shuwa Arab", "Rohingya", "ethnicity", "tribe", "tribal", "indigene",
    ],
    "Political opinion": [
        "political party", "party member", "APC", "PDP", "Labour Party", "NNPP", "activist", "protester",
        "IPOB", "separatist",
    ],
    "Criminal record": [
        "arrested", "convicted", "conviction", "prison", "prisoner", "detained", "detention", "custody",
        "criminal record", "charged with", "on bail", "parole", "ex-convict", "ex-combatant", "insurgent",
        "Boko Haram", "ISWAP", "militant",
    ],
    "Immigration status": [
        "asylum", "asylum seeker", "refugee status", "undocumented", "deported", "deportation", "stateless",
        "visa overstay", "irregular migrant", "IDP", "internally displaced",
    ],
    "Biometric or genetic": [
        "fingerprint", "fingerprints", "biometric", "biometrics", "iris scan", "facial recognition", "DNA",
        "genetic", "blood group", "genotype",
    ],
    "Trade union": ["trade union", "union member", "NLC", "ASUU"],
}

_SENSITIVE_RX = [
    (topic, re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
                       + r")(?![\w-])", re.IGNORECASE))
    for topic, words in SENSITIVE.items()
]
# Short capitalised acronyms (TB, ARV, APC) only count when written in capitals.
_ACRONYMS = {w for words in SENSITIVE.values() for w in words if w.isupper() and len(w) <= 5}


# Descriptions that can point to one person even with the name hidden: "the only blind woman in the camp",
# "the village head", "wife of the imam". Someone who knows the community can tell who it is.
# ponytail: a word list, not a model. It cannot judge how rare a description is, so staff decide each one.
_ROLES = (r"village head|ward head|district head|community leader|traditional ruler|chief imam|imam|emir|"
          r"oba|sarki|headmaster|headmistress|head teacher|councillor|chairman|chairwoman|"
          r"youth leader|women leader|camp chairman|camp leader|block leader|zone leader|midwife")
# Trigger words in any case; the words after them lowercase only, so a following name ("Kano Clinic")
# is left to the name finder instead of being swallowed into the description.
_WORDS = r"(?:\s+[a-z'’-]+)"
_CLUE_RX = [   # (label, pattern, fewest words that still say something)
    ("Only one of a kind", re.compile(
        r"\b(?i:the only|the one (?:who|that)|the (?:woman|man|girl|boy|lady|child|widow) who)"
        + _WORDS + "{1,5}"), 3),
    ("Role in the community", re.compile(r"\b(?i:(?:the|our|their|a former)\s+(?:" + _ROLES + r"))\b"), 2),
    ("Related to someone known", re.compile(
        r"\b(?i:(?:wife|husband|son|daughter|mother|father|brother|sister|widow|child|niece|nephew)\s+of\s+the)"
        + _WORDS + "{1,3}"), 3),
]
# Small words a description should not end on: "the only blind woman in" stops before "in".
_CLUE_TAIL = re.compile(r"(?:\s+(?:in|at|on|of|from|to|with|and|or|who|that|the|a|an|is|was|has|had|her|his))+$",
                        re.IGNORECASE)


def find_clues(text: str):
    """Yield (start, end, text, label) for descriptions that may identify one person."""
    for label, rx, fewest in _CLUE_RX:
        for m in rx.finditer(text):
            value = _CLUE_TAIL.sub("", m.group(0))
            if len(value.split()) >= fewest:
                yield m.start(), m.start() + len(value), value, label


def find_patterns(text: str, enabled: set[str]):
    """Yield (start, end, text, kind, label) for every identifier found."""
    for p in PATTERNS:
        if p.kind not in enabled:
            continue
        for m in p.regex.finditer(text):
            value = m.group(p.group)
            if value and (p.check is None or p.check(value)):
                yield m.start(p.group), m.end(p.group), value, p.kind, p.label


def find_sensitive(text: str):
    """Yield (start, end, text, topic) for protected topics."""
    for topic, rx in _SENSITIVE_RX:
        for m in rx.finditer(text):
            word = m.group(0)
            if word.upper() in _ACRONYMS and not word.isupper():
                continue
            yield m.start(), m.end(), word, topic
