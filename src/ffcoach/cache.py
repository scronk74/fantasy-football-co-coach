"""SQLite-backed cache with per-entry TTL.

Stale reads are a feature: a failed fetch on a Sunday morning should serve
old data with a visible staleness marker, not crash.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    stored_at  REAL NOT NULL,
    ttl        REAL NOT NULL
)
"""


class Cache:
    def __init__(self, path: Path, now: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._conn.execute(
            "INSERT INTO entries (key, value, stored_at, ttl) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "stored_at=excluded.stored_at, ttl=excluded.ttl",
            (key, value, self._now(), float(ttl_seconds)),
        )
        self._conn.commit()

    def _row(self, key: str) -> tuple[str, float, float] | None:
        cur = self._conn.execute(
            "SELECT value, stored_at, ttl FROM entries WHERE key = ?", (key,)
        )
        return cur.fetchone()

    def get(self, key: str) -> str | None:
        row = self._row(key)
        if row is None:
            return None
        value, stored_at, ttl = row
        if self._now() - stored_at > ttl:
            return None
        return value

    def get_with_age(self, key: str) -> tuple[str, float] | None:
        """A live-enough entry and how old it is, or None past its TTL.

        `get` answers "may I use this"; this answers "may I use this, and how
        old is it". Sources need the second question because a cache hit is
        still not a live fetch, and the page says so.
        """
        row = self._row(key)
        if row is None:
            return None
        value, stored_at, ttl = row
        age = self._now() - stored_at
        if age > ttl:
            return None
        return value, age

    def get_stale(self, key: str) -> tuple[str, float] | None:
        row = self._row(key)
        if row is None:
            return None
        value, stored_at, _ = row
        return value, self._now() - stored_at

    def age_seconds(self, key: str) -> float | None:
        row = self._row(key)
        if row is None:
            return None
        return self._now() - row[1]
