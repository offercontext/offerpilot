from __future__ import annotations

import base64
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

JOURNAL_KEY_FILENAME = "agent-journal-key.json"


@dataclass(frozen=True)
class JournalKeyDomain:
    key_id: str
    secret: bytes


def _decode_secret(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("invalid journal secret")
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if len(decoded) != 32:
        raise ValueError("invalid journal secret length")
    return decoded


def _read_key(path: Path) -> JournalKeyDomain:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "key_id", "secret"}:
        raise ValueError("invalid journal key payload")
    if payload["schema_version"] != 1 or not isinstance(payload["key_id"], str):
        raise ValueError("invalid journal key schema")
    parsed_id = UUID(payload["key_id"])
    key_id = str(parsed_id)
    if payload["key_id"] != key_id:
        raise ValueError("journal key id must be canonical")
    return JournalKeyDomain(key_id=key_id, secret=_decode_secret(payload["secret"]))


def load_or_create_journal_key(
    data_dir: Path,
    *,
    replace_file: Callable[[Path, Path], None] = os.replace,
    platform_name: str = os.name,
    chmod_file: Callable[[Path, int], None] = os.chmod,
) -> JournalKeyDomain | None:
    """Return the durable Journal key domain, or disable journaling on ordinary failure."""

    key_path = data_dir.resolve() / JOURNAL_KEY_FILENAME
    lock_path = key_path.with_name(f".{JOURNAL_KEY_FILENAME}.lock")
    temp_path: Path | None = None
    owns_lock = False
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            if platform_name != "nt":
                chmod_file(key_path, 0o600)
            return _read_key(key_path)

        for lock_attempt in range(2):
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if key_path.exists():
                    if platform_name != "nt":
                        chmod_file(key_path, 0o600)
                    return _read_key(key_path)
                try:
                    stale = time.time() - lock_path.stat().st_mtime > 30.0
                except OSError:
                    stale = False
                if stale and lock_attempt == 0:
                    lock_path.unlink(missing_ok=True)
                    continue
                return None
            else:
                os.close(lock_fd)
                owns_lock = True
                break
        if not owns_lock:
            return None

        domain = JournalKeyDomain(key_id=str(uuid4()), secret=secrets.token_bytes(32))
        payload = {
            "schema_version": 1,
            "key_id": domain.key_id,
            "secret": base64.urlsafe_b64encode(domain.secret).decode("ascii").rstrip("="),
        }
        temp_path = key_path.with_name(f".{JOURNAL_KEY_FILENAME}.{uuid4().hex}.tmp")
        if platform_name != "nt":
            temp_path.touch(mode=0o600, exist_ok=False)
            chmod_file(temp_path, 0o600)
        with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temp_path, key_path)
        temp_path = None
        if platform_name != "nt":
            chmod_file(key_path, 0o600)
        return domain
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    finally:
        if owns_lock:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
