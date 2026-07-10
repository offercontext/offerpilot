from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class LogEntry(TypedDict):
    level: str
    message: str


def append_log_entry(data_dir: Path, level: str, message: str) -> None:
    path = _log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"level": level.upper(), "message": message}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_recent_log_entries(data_dir: Path, limit: int = 100, level: str = "") -> list[LogEntry]:
    path = _log_path(data_dir)
    if not path.exists():
        return []
    rows = path.read_text(encoding="utf-8").splitlines()
    entries: list[LogEntry] = []
    normalized_level = level.strip().upper()
    for raw in rows:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        entry = {
            "level": str(parsed.get("level") or "INFO"),
            "message": str(parsed.get("message") or ""),
        }
        if normalized_level and entry["level"] != normalized_level:
            continue
        entries.append(entry)
    return entries[-max(1, limit) :]


def _log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / "offerpilot.log"
