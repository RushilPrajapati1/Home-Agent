"""Small JSON cache keyed by string, timestamped by a Clock so tests control expiry.

housing-mcp has no database, so the cache is one JSON file per key on a volume. That keeps
RentCast's 50-a-month quota from resetting every time the container restarts.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from homefund_contracts import Clock


@dataclass(frozen=True)
class Entry:
    value: Any
    stored_at: datetime

    def fresh(self, clock: Clock, ttl: timedelta) -> bool:
        return clock.now() - self.stored_at < ttl


class Cache(Protocol):
    def get(self, key: str) -> Entry | None: ...
    def set(self, key: str, value: Any) -> None: ...


class MemoryCache:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._data: dict[str, Entry] = {}

    def get(self, key: str) -> Entry | None:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        # Round-trip through JSON so memory and file caches hold the same shapes.
        self._data[key] = Entry(json.loads(json.dumps(value)), self._clock.now())


class FileCache:
    def __init__(self, root: Path, clock: Clock) -> None:
        self._root = root
        self._clock = clock
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Hashed names: keys can hold addresses, which shouldn't show up in a directory listing.
        return self._root / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def get(self, key: str) -> Entry | None:
        try:
            raw = json.loads(self._path(key).read_text())
            return Entry(raw["value"], datetime.fromisoformat(raw["stored_at"]))
        except (OSError, ValueError, KeyError):
            return None

    def set(self, key: str, value: Any) -> None:
        body = json.dumps({"stored_at": self._clock.now().isoformat(), "value": value})
        fd, tmp = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.replace(tmp, self._path(key))
