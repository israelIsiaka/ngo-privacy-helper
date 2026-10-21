"""Lock a PDF with a password (AES-256) so it opens in any PDF reader:
Adobe Reader, Preview, Edge, Chrome. Unlike .nph files, the receiver does
not need this app, only the password.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from .filecrypt import free_path

# No 0/O, 1/l/I: passwords are often read out over the phone.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


class PdfError(Exception):
    pass


def new_password() -> str:
    """Four groups of five characters, about 115 bits."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(5)) for _ in range(4))


def _reader(src: Path) -> PdfReader:
    try:
        return PdfReader(str(src))
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfError(f"This PDF could not be read: {exc}") from None


def is_locked(src: Path) -> bool:
    return _reader(src).is_encrypted


def lock_pdf(src: Path, out_dir: Path, password: str) -> Path:
    reader = _reader(src)
    if reader.is_encrypted:
        raise PdfError("This PDF already has a password.")
    writer = PdfWriter(clone_from=reader)
    # Owner password is separate and random, so the open password cannot be used to lift restrictions.
    writer.encrypt(user_password=password, owner_password=secrets.token_urlsafe(24), algorithm="AES-256")
    out = free_path(Path(out_dir) / f"{Path(src).stem} (locked).pdf")
    with open(out, "wb") as f:
        writer.write(f)
    return out


def unlock_pdf(src: Path, out_dir: Path, passwords: list[str]) -> Path:
    reader = _reader(src)
    if not reader.is_encrypted:
        raise PdfError("This PDF does not have a password.")
    if not any(reader.decrypt(p) for p in passwords if p):
        raise PdfError("None of the saved passwords open this PDF.")
    writer = PdfWriter(clone_from=reader)
    stem = Path(src).stem.removesuffix(" (locked)")
    out = free_path(Path(out_dir) / f"{stem} (unlocked).pdf")
    with open(out, "wb") as f:
        writer.write(f)
    return out
