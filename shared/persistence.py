"""Small, auditable persistence primitives for the native editor."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


def record_etag(record: Any) -> str:
    """레코드 하나의 지문.  **낙관적 잠금의 열쇠다.**

    덱에 종속되지 않는다 — 어느 덱이든 '내가 읽은 그 레코드가 아직 그대로인가' 를
    묻는 방법은 같다.  덱마다 따로 만들면 같은 레코드에 다른 열쇠가 나와 저장이
    통째로 거절된다.
    """
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any, *, newline: str = "\n") -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if newline != "\n":
        text = text.replace("\n", newline)
    return text.encode("utf-8")


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    verify: Callable[[Any], None] | None = None,
    newline: str = "\n",
) -> str:
    """Write one JSON document with same-directory temp + fsync + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json_bytes(value, newline=newline)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())

        parsed = json.loads(temporary.read_text(encoding="utf-8"))
        if verify is not None:
            verify(parsed)
        os.replace(temporary, path)
        temporary = None
        return hashlib.sha256(body).hexdigest()
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


@contextmanager
def advisory_file_lock(path: Path) -> Iterator[None]:
    """Serialize writers across editor processes on Windows and POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
