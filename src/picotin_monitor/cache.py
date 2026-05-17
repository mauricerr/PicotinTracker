from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


class DedupeCache:
    def __init__(self, path: Path, ttl_hours: float) -> None:
        self.path = path
        self.ttl = timedelta(hours=ttl_hours)
        self.records = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def should_notify(self, key: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        raw_seen = self.records.get(key)
        if not raw_seen:
            return True
        try:
            seen = datetime.fromisoformat(raw_seen)
        except ValueError:
            return True
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        return now - seen >= self.ttl

    def mark_notified(self, key: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.records[key] = now.isoformat()
        cutoff = now - self.ttl * 4
        cleaned: dict[str, str] = {}
        for item_key, raw_seen in self.records.items():
            try:
                seen = datetime.fromisoformat(raw_seen)
            except ValueError:
                continue
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if seen >= cutoff:
                cleaned[item_key] = raw_seen
        self.records = cleaned
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, indent=2, sort_keys=True), encoding="utf-8")
