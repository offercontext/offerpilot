from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import TypedDict


class LogEntry(TypedDict):
    level: str
    message: str


class LogPage(TypedDict):
    entries: list[LogEntry]
    total: int
    limit: int
    offset: int
    has_more: bool


def append_log_entry(data_dir: Path, level: str, message: str) -> None:
    path = _log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"level": level.upper(), "message": message}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_recent_log_page(data_dir: Path, *, limit: int, offset: int) -> LogPage:
    path = _log_path(data_dir)
    if not path.exists():
        return {
            "entries": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "has_more": False,
        }

    recent_entries: deque[LogEntry] = deque(maxlen=offset + limit)
    total = 0
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            total += 1
            recent_entries.append(
                {
                    "level": str(parsed.get("level") or "INFO"),
                    "message": str(parsed.get("message") or ""),
                }
            )

    entries = list(recent_entries)[: max(0, min(limit, total - offset))]
    return {
        "entries": entries,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": total > offset + len(entries),
    }


def _log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / "offerpilot.log"
