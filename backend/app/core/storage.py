"""Safe file storage.

* Files are saved under generated names (uuid + allowed extension) — the client filename is
  kept only as metadata, never used as a path.
* Uploads are streamed to disk in chunks and aborted as soon as the size limit is passed.
* Every resolved path is checked to stay inside its storage directory.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.errors import FileTooLarge, ValidationFailed

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StoredFile:
    path: Path
    size_bytes: int
    sha256: str


def ensure_dirs(*dirs: Path) -> None:
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def safe_child(base: Path, name: str) -> Path:
    base = base.resolve()
    candidate = (base / name).resolve()
    if base != candidate.parent:
        raise ValidationFailed("Invalid storage path")
    return candidate


def save_stream(source: BinaryIO, directory: Path, extension: str, max_bytes: int) -> StoredFile:
    ensure_dirs(directory)
    target = safe_child(directory, f"{uuid.uuid4().hex}{extension}")
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := source.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLarge(
                        f"File exceeds the {max_bytes // (1024 * 1024)} MB limit",
                        {"limit_bytes": max_bytes},
                    )
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if size == 0:
        target.unlink(missing_ok=True)
        raise ValidationFailed("The uploaded file is empty")
    return StoredFile(path=target, size_bytes=size, sha256=digest.hexdigest())


def remove_file(directory: Path, name: str | None) -> None:
    if not name:
        return
    try:
        safe_child(directory, name).unlink(missing_ok=True)
    except ValidationFailed:
        pass
