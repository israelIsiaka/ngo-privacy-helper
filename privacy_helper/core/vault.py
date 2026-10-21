"""The key vault: one file, encrypted with the staff member's master password.

It holds every file key, PDF password and hidden-details session, so staff can
find any key by file name. Losing the master password means losing the keys,
which is why the app offers a backup.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT = "ngo-privacy-helper-vault"
VERSION = 1
# scrypt at OWASP's recommended cost: ~128 MB and well under a second on a modest laptop.
SCRYPT = {"n": 2**17, "r": 8, "p": 1}
MIN_PASSWORD = 10

KIND_FILE = "file"      # file encrypted by this app (.nph)
KIND_PDF = "pdf"        # PDF locked with a password
KIND_MASK = "mask"      # tokens from a hidden-details session


class WrongPassword(Exception):
    pass


class VaultError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=256 * 1024 * 1024, dklen=32)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Entry:
    id: str
    kind: str
    label: str                       # what staff recognise: the original file name, or a session name
    created: str
    secret: str = ""                 # base64 file key, or PDF password
    mapping: dict[str, str] = field(default_factory=dict)
    source: str = ""                 # where the original file was
    output: str = ""                 # where the protected file was saved


@dataclass
class Settings:
    always_hide: list[str] = field(default_factory=list)
    never_hide: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=lambda: ["EMAIL", "PHONE", "ID", "ACCOUNT", "DATE"])
    suggest_names: bool = True
    lock_minutes: int = 10
    output_folder: str = ""          # empty: save next to the original


class Vault:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[Entry] = []
        self.settings = Settings()
        self._key: bytes | None = None
        self._kdf: dict | None = None

    # ---- lifecycle -------------------------------------------------------
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    def create(self, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise VaultError(f"Use at least {MIN_PASSWORD} characters.")
        self._set_password(password)
        self.entries, self.settings = [], Settings()
        self.save()

    def unlock(self, password: str) -> None:
        outer = self._read_outer(self.path)
        kdf = outer["kdf"]
        key = _derive(password, _unb64(kdf["salt"]), kdf["n"], kdf["r"], kdf["p"])
        try:
            inner = AESGCM(key).decrypt(_unb64(outer["nonce"]), _unb64(outer["data"]), FORMAT.encode())
        except InvalidTag:
            raise WrongPassword("That password does not open this vault.") from None
        data = json.loads(inner)
        self.entries = [Entry(**e) for e in data.get("entries", [])]
        known = Settings.__dataclass_fields__
        self.settings = Settings(**{k: v for k, v in data.get("settings", {}).items() if k in known})
        self._key, self._kdf = key, kdf

    def lock(self) -> None:
        self._key = None
        self.entries = []
        self.settings = Settings()

    def change_password(self, old: str, new: str) -> None:
        if len(new) < MIN_PASSWORD:
            raise VaultError(f"Use at least {MIN_PASSWORD} characters.")
        Vault(self.path).unlock(old)   # raises WrongPassword
        self._set_password(new)
        self.save()

    def _set_password(self, password: str) -> None:
        self._kdf = {"name": "scrypt", "salt": _b64(secrets.token_bytes(16)), **SCRYPT}
        self._key = _derive(password, _unb64(self._kdf["salt"]), **SCRYPT)

    # ---- storage ---------------------------------------------------------
    @staticmethod
    def _read_outer(path: Path) -> dict:
        try:
            outer = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise VaultError(f"The key vault could not be read: {exc}") from None
        if outer.get("format") != FORMAT:
            raise VaultError("This is not an NGO Privacy Helper key vault.")
        if outer.get("version", 0) > VERSION:
            raise VaultError("This vault was made by a newer version of the app. Please update.")
        return outer

    def save(self) -> None:
        if self._key is None:
            raise VaultError("The vault is locked.")
        inner = json.dumps({"entries": [asdict(e) for e in self.entries],
                            "settings": asdict(self.settings)}).encode("utf-8")
        nonce = secrets.token_bytes(12)
        outer = {"format": FORMAT, "version": VERSION, "kdf": self._kdf, "nonce": _b64(nonce),
                 "data": _b64(AESGCM(self._key).encrypt(nonce, inner, FORMAT.encode()))}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write a temp file and swap it in, keeping the previous version, so a crash never loses keys.
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(outer, f)
            f.flush()
            os.fsync(f.fileno())
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".previous"))
        os.replace(tmp, self.path)

    def backup_to(self, target: Path) -> None:
        shutil.copy2(self.path, target)

    def restore_from(self, backup: Path, password: str) -> None:
        """Replace this vault with a backup, after proving the password opens it."""
        probe = Vault(backup)
        probe.unlock(password)
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".previous"))
        shutil.copy2(backup, self.path)
        self.unlock(password)

    # ---- entries ---------------------------------------------------------
    def add(self, kind: str, label: str, entry_id: str | None = None, **fields) -> Entry:
        entry = Entry(id=entry_id or secrets.token_hex(16), kind=kind, label=label, created=now(), **fields)
        self.entries.append(entry)
        self.save()
        return entry

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def update(self, entry: Entry) -> None:
        self.save()

    def remove(self, entry_id: str) -> None:
        self.entries = [e for e in self.entries if e.id != entry_id]
        self.save()

    def find_pdf_password(self, path: Path) -> list[str]:
        """Passwords that might open a locked PDF, best guesses first."""
        path = str(path)
        pdfs = [e for e in self.entries if e.kind == KIND_PDF]
        exact = [e.secret for e in pdfs if e.output == path]
        return exact + [e.secret for e in reversed(pdfs) if e.output != path]
