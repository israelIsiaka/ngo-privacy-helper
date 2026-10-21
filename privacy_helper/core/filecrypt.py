"""Encrypt any file with its own key (AES-256-GCM), in chunks so large files work.

File layout (.nph), identical on Windows and macOS:

    magic   b"NPH1"         4 bytes
    key id  16 bytes        which vault entry holds the key
    prefix  8 random bytes  nonce = prefix + 4-byte record number
    records [4-byte big-endian length][ciphertext + 16-byte tag] ...

Record 0 holds the original file name; the rest hold the file contents.
Each record's associated data is header + record number + last-record flag,
so records cannot be reordered, swapped between files, or cut off.
"""

from __future__ import annotations

import json
import secrets
import struct
from pathlib import Path
from typing import Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"NPH1"
SUFFIX = ".nph"
CHUNK = 1024 * 1024
HEADER_LEN = 4 + 16 + 8

Progress = Callable[[int, int], None] | None


class DecryptError(Exception):
    pass


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def read_key_id(path: Path) -> str:
    """The vault entry id stored in an encrypted file's header."""
    with open(path, "rb") as f:
        header = f.read(HEADER_LEN)
    if len(header) < HEADER_LEN or header[:4] != MAGIC:
        raise DecryptError("This is not a file encrypted by NGO Privacy Helper.")
    return header[4:20].hex()


def _aad(header: bytes, index: int, last: bool) -> bytes:
    return header + struct.pack(">I?", index, last)


def _nonce(prefix: bytes, index: int) -> bytes:
    return prefix + struct.pack(">I", index)


def free_path(path: Path) -> Path:
    """Never overwrite: report.pdf -> report (2).pdf."""
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem} ({n}){path.suffix}")).exists():
        n += 1
    return candidate


def encrypt_file(src: Path, out_dir: Path, key_id: str, key: bytes, progress: Progress = None) -> Path:
    src = Path(src)
    out = free_path(Path(out_dir) / (src.name + SUFFIX))
    header = MAGIC + bytes.fromhex(key_id) + secrets.token_bytes(8)
    prefix, aes = header[20:], AESGCM(key)
    total, done = src.stat().st_size, 0
    tmp = out.with_name(out.name + ".part")
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            fout.write(header)

            def put(index: int, data: bytes, last: bool) -> None:
                sealed = aes.encrypt(_nonce(prefix, index), data, _aad(header, index, last))
                fout.write(struct.pack(">I", len(sealed)) + sealed)

            put(0, json.dumps({"name": src.name}).encode("utf-8"), False)
            index, chunk = 1, fin.read(CHUNK)
            while True:
                following = fin.read(CHUNK)
                put(index, chunk, last=not following)
                done += len(chunk)
                if progress:
                    progress(done, total)
                if not following:
                    break
                index, chunk = index + 1, following
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def decrypt_file(src: Path, out_dir: Path, key: bytes, progress: Progress = None) -> Path:
    src = Path(src)
    total = src.stat().st_size
    aes = AESGCM(key)
    with open(src, "rb") as fin:
        header = fin.read(HEADER_LEN)
        if len(header) < HEADER_LEN or header[:4] != MAGIC:
            raise DecryptError("This is not a file encrypted by NGO Privacy Helper.")
        prefix = header[20:]

        def take(index: int) -> tuple[bytes, bool]:
            size_raw = fin.read(4)
            if len(size_raw) < 4:
                raise DecryptError("The file is incomplete. It may have been cut short while copying.")
            sealed = fin.read(struct.unpack(">I", size_raw)[0])
            last = not fin.peek(1)   # nothing after this record
            try:
                return aes.decrypt(_nonce(prefix, index), sealed, _aad(header, index, last)), last
            except InvalidTag:
                raise DecryptError("The key does not match, or the file was changed after it was encrypted.") from None

        meta, _ = take(0)
        name = Path(json.loads(meta)["name"]).name or "decrypted"   # .name drops any folder parts
        out = free_path(Path(out_dir) / name)
        tmp = out.with_name(out.name + ".part")
        try:
            with open(tmp, "wb") as fout:
                index, last = 1, False
                while not last:
                    data, last = take(index)
                    fout.write(data)
                    if progress:
                        progress(fin.tell(), total)
                    index += 1
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
    return out


def export_key(key_id: str, key: bytes) -> str:
    """A single line staff can send to a colleague by a separate channel."""
    return f"NPHKEY1:{key_id}:{key.hex()}"


def parse_key(text: str) -> tuple[str, bytes]:
    parts = text.strip().split(":")
    if len(parts) != 3 or parts[0] != "NPHKEY1":
        raise ValueError("This is not an NGO Privacy Helper key. It should start with NPHKEY1.")
    key_id, key = parts[1], bytes.fromhex(parts[2])
    if len(bytes.fromhex(key_id)) != 16 or len(key) != 32:
        raise ValueError("This key is incomplete. Copy the whole line and try again.")
    return key_id, key
