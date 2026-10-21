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
from datetime import date, datetime, timedelta
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


def owner_only(*paths: Path) -> None:
    """Only the signed-in user may read the vault (macOS; Windows AppData is already per user)."""
    if os.name == "posix":
        for p in paths:
            if p.exists():
                os.chmod(p, 0o600)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def days_from_today(days: int) -> str:
    """The delete date for a key kept this many days. 0 means keep it until deleted by hand."""
    return (date.today() + timedelta(days=days)).isoformat() if days > 0 else ""


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
    expires: str = ""                # ISO date the key is destroyed on; empty: kept until deleted by hand


@dataclass
class Settings:
    always_hide: list[str] = field(default_factory=list)
    never_hide: list[str] = field(default_factory=list)
    off_patterns: list[str] = field(default_factory=list)   # kinds switched off; new kinds start on
    suggest_names: bool = True
    lock_minutes: int = 10
    output_folder: str = ""          # empty: save next to the original
    # Days new keys are kept before they are destroyed. 0 keeps them until deleted by hand.
    mask_days: int = 0               # hidden-details records: after this, replies can no longer be restored
    file_days: int = 0               # file keys and PDF passwords: after this, the files can never be opened


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
        # A changed or damaged file must not be able to weaken the key or ask for unlimited memory.
        if not (2**14 <= kdf.get("n", 0) <= 2**20 and 1 <= kdf.get("r", 0) <= 16 and 1 <= kdf.get("p", 0) <= 4):
            raise VaultError("The key vault is damaged: its password settings are not valid.")
        try:
            key = _derive(password, _unb64(kdf["salt"]), kdf["n"], kdf["r"], kdf["p"])
            inner = AESGCM(key).decrypt(_unb64(outer["nonce"]), _unb64(outer["data"]), FORMAT.encode())
        except InvalidTag:
            raise WrongPassword("That password does not open this vault.") from None
        except (ValueError, KeyError, TypeError) as exc:
            raise VaultError(f"The key vault is damaged: {exc}") from None
        data = json.loads(inner)
        fields = Entry.__dataclass_fields__   # ignore fields added by newer versions
        self.entries = [Entry(**{k: v for k, v in e.items() if k in fields}) for e in data.get("entries", [])]
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
        # The kept previous copy still opens with the old password; replace it.
        shutil.copy2(self.path, self.path.with_suffix(".previous"))

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
        tmp.unlink(missing_ok=True)   # created fresh below, private from the first byte
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
            json.dump(outer, f)
            f.flush()
            os.fsync(f.fileno())
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".previous"))
        os.replace(tmp, self.path)
        owner_only(self.path, self.path.with_suffix(".previous"))

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
        days = self.settings.mask_days if kind == KIND_MASK else self.settings.file_days
        fields.setdefault("expires", days_from_today(days))
        entry = Entry(id=entry_id or secrets.token_hex(16), kind=kind, label=label, created=now(), **fields)
        self.entries.append(entry)
        self.save()
        return entry

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def remove(self, entry_id: str) -> None:
        self.entries = [e for e in self.entries if e.id != entry_id]
        self.save()

    def purge_expired(self, today: date | None = None) -> list[str]:
        """Destroy keys whose delete date has come. Hidden details then stay hidden for good,
        and expired files can never be opened. Returns the labels of what was destroyed."""
        today_iso = (today or date.today()).isoformat()
        gone = [e for e in self.entries if e.expires and e.expires <= today_iso]
        if gone:
            self.entries = [e for e in self.entries if e not in gone]
            self.save()
            # save() keeps the previous copy as a crash guard; save again so that copy forgets the keys too.
            self.save()
        return [e.label for e in gone]

    def find_pdf_password(self, path: Path) -> list[str]:
        """Passwords that might open a locked PDF, best guesses first."""
        path = str(path)
        pdfs = [e for e in self.entries if e.kind == KIND_PDF]
        exact = [e.secret for e in pdfs if e.output == path]
        return exact + [e.secret for e in reversed(pdfs) if e.output != path]
