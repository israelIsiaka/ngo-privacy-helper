import pytest

from privacy_helper.core import masking
from privacy_helper.core.pii import PATTERN_KINDS


def kinds(text):
    return {(d.text, d.kind) for d in masking.Detector(suggest_names=False).find(text)}


@pytest.mark.parametrize("text, value, kind", [
    ("Card 4111 1111 1111 1111 was used", "4111 1111 1111 1111", "CARD"),
    ("IBAN GB82 WEST 1234 5698 7654 32 please", "GB82 WEST 1234 5698 7654 32", "ACCOUNT"),
    ("Account 0123456789.", "0123456789", "ACCOUNT"),
    ("NIN 12345678901.", "12345678901", "ID"),
    ("Passport A12345678 expired", "A12345678", "ID"),
    ("Licence ABC12345AB12 seen", "ABC12345AB12", "ID"),
    ("UNHCR no: 123-15C00456 registered", "123-15C00456", "ID"),
    ("Case ref: KD/2024/0193 opened", "KD/2024/0193", "ID"),
    ("SSN 123-45-6789", "123-45-6789", "ID"),
    ("NI number AB 12 34 56 C", "AB 12 34 56 C", "ID"),
    ("Lives at No. 12 Adeola Odeku Street, Lagos", "No. 12 Adeola Odeku Street", "PLACE"),
    ("Found at 9.0765, 7.3986 near the camp", "9.0765, 7.3986", "PLACE"),
    ("GPS 12.1700, 6.6600.", "12.1700, 6.6600", "PLACE"),
    ("Post to SW1A 1AA today", "SW1A 1AA", "PLACE"),
    ("Car KJA-456AB parked", "KJA-456AB", "VEHICLE"),
    ("See https://facebook.com/hadiza.i for photos", "https://facebook.com/hadiza.i", "ONLINE"),
    ("Message @hadiza_ib on Instagram", "@hadiza_ib", "ONLINE"),
    ("Logged from 197.210.54.12 yesterday", "197.210.54.12", "ONLINE"),
    ("Phone IMEI 356938035643809 lost", "356938035643809", "ONLINE"),
    ("Born on 3rd March 1990", "3rd March 1990", "DATE"),
    ("Call +234 803 555 1234 now", "+234 803 555 1234", "PHONE"),
])
def test_identifiers(text, value, kind):
    assert (value, kind) in kinds(text)


@pytest.mark.parametrize("text", [
    "Card 4111 1111 1111 1112 is not valid",       # fails Luhn
    "In this case 2024 was hard",                  # a year is not an ID
    "The meeting is at 10:30:45 today",            # a time is not an IP address
    "Email me at the office",                      # no handle
    "She is 34 and has 2 children",
])
def test_no_false_alarms(text):
    found = {k for _, k in kinds(text)} - {"SENSITIVE"}
    assert not found, kinds(text)


def test_protected_topics_are_listed_but_not_ticked():
    found = masking.Detector(suggest_names=False).find(
        "She is HIV positive, a Christian, and survived domestic violence. She aids others; tb is lowercase.")
    topics = {d.text: (d.label, d.enabled) for d in found if d.kind == "SENSITIVE"}
    assert topics["HIV positive"] == ("Health", False)
    assert topics["Christian"] == ("Religion or belief", False)
    assert topics["domestic violence"] == ("Violence and abuse", False)
    assert "aids" not in topics and "tb" not in topics      # acronyms only in capitals


def test_every_kind_can_be_switched_off():
    text = "Call 0803 555 1234, NIN 12345678901, HIV."
    assert masking.Detector(patterns=(), suggest_names=False).find(text) == []
    assert set(PATTERN_KINDS) >= {"PHONE", "ID", "SENSITIVE"}
