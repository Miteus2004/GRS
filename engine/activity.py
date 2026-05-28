"""Persistent activity log for dashboard and demo output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_NAME = "engine_activity.jsonl"


def log_path(base_dir: str | Path) -> Path:
    return Path(base_dir) / DEFAULT_LOG_NAME


def append_event(base_dir: str | Path, kind: str, message: str, details: dict[str, Any] | None = None) -> Path:
    path = log_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "message": message,
        "details": details or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def read_events(base_dir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    path = log_path(base_dir)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events