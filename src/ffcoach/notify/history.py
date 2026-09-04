"""How many times each problem has already been alerted.

Lives in the same SQLite file as the cache (D-041), in its own table. Sharing
the file rather than the `Cache` class is deliberate: `Cache` is a TTL store
whose whole contract is that entries expire, and an alert record that quietly
expired would hand a fixed problem a fresh pair of strikes.

Deliberately append-only per key. `record()` increments rather than overwrites,
so the count survives a crash between the send and the write in the safe
direction -- an alert delivered but unrecorded costs at most one extra message,
where an alert recorded but undelivered costs the message that mattered.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from ffcoach.notify.policy import AlertRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    key        TEXT PRIMARY KEY,
    sent_count INTEGER NOT NULL,
    last_sent  REAL NOT NULL
)
"""


class AlertHistory:
    def __init__(self, path: Path, now: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def records(self) -> dict[str, AlertRecord]:
        """Every key we have ever sent, how often, and when last.

        Read whole rather than queried per key: the table holds a season's
        alerts at most, and one read keeps the policy decision a pure function
        of a snapshot rather than of a live database.
        """
        return {
            key: AlertRecord(
                count=count,
                last_sent=dt.datetime.fromtimestamp(last, dt.UTC),
            )
            for key, count, last in self._conn.execute(
                "SELECT key, sent_count, last_sent FROM alerts"
            )
        }

    def counts(self) -> dict[str, int]:
        """Just the counts. Kept for callers that do not need the timestamps."""
        return dict(self._conn.execute("SELECT key, sent_count FROM alerts"))

    def record(self, keys: tuple[str, ...] | list[str]) -> None:
        """Count one delivered alert per key. Call only after a successful send."""
        now = self._now()
        self._conn.executemany(
            "INSERT INTO alerts (key, sent_count, last_sent) VALUES (?, 1, ?) "
            "ON CONFLICT(key) DO UPDATE SET sent_count = sent_count + 1, "
            "last_sent = excluded.last_sent",
            [(key, now) for key in keys],
        )
        self._conn.commit()

    def last_sent(self, key: str) -> float | None:
        row = self._conn.execute(
            "SELECT last_sent FROM alerts WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def forget(self, key: str) -> None:
        """Drop one key's history. What a future `--reset` would use."""
        self._conn.execute("DELETE FROM alerts WHERE key = ?", (key,))
        self._conn.commit()
