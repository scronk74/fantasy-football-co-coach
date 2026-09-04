"""One JSON line per run: what was checked, what was found, what was sent.

**The gap this closes.** Nothing recorded anything. A quiet Sunday morning was
indistinguishable between "your lineup is clean" and "the ESPN cookies expired
at 6am and every run since has errored" -- and once a scheduler is running the
check unattended, that ambiguity is the product's main failure mode rather than
an edge case. It is also why E3 could not be built: a dead-man's switch is the
question "when did a run last succeed?", and that question had no answer.

JSONL rather than a table (D-041) because the first reader is a person with
`grep` at 9am on a Sunday, and the second is a UI history view that can read
line-oriented data just as easily. One line, self-contained, no array to parse.

**Two properties are load-bearing.**

*Secrets never reach it.* The ntfy topic is a credential, the ESPN cookies
authenticate as the user, and a log file is exactly what someone pastes into an
issue. `secrets` are scrubbed from every string in the record, at any depth.

*A logging failure never takes down the check.* A full disk must not cost you
the alert. Write errors warn on stderr and the run continues -- the check
succeeding matters more than the line about it.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

REDACTED = "***"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _scrub(value, secrets: tuple[str, ...]):
    """Replace every secret wherever it appears, at any depth."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {k: _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, secrets) for v in value]
    return value


class RunLog:
    def __init__(
        self,
        path: Path,
        now: Callable[[], dt.datetime] = _utcnow,
        secrets: Iterable[str | None] = (),
    ) -> None:
        self.path = Path(path)
        self._now = now
        # Empty and None are dropped: a missing credential is `""`, and
        # scrubbing that would replace every gap between characters.
        self._secrets = tuple(s for s in secrets if s)

    def append(self, record: dict) -> None:
        """Add one line. Never raises -- see the module docstring."""
        stamped = {"at": self._now().isoformat(timespec="seconds"), **record}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                # `default=str` rather than a custom encoder: a datetime that
                # slipped into the record should cost readability, not the line.
                fh.write(json.dumps(_scrub(stamped, self._secrets), default=str) + "\n")
        except OSError as exc:
            print(f"warning: could not write the run log ({exc})", file=sys.stderr)

    def tail(self, n: int = 1) -> list[dict]:
        """The `n` most recent records, newest first.

        A corrupt line -- a half-written record from a killed process -- is
        skipped rather than allowed to blind every reader of the file.
        """
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict] = []
        for line in reversed(lines):
            if len(out) >= n:
                break
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def last_success(self) -> dict | None:
        """The most recent run that actually completed. The question E3 asks.

        A failed run is not a heartbeat: it proves the machine is awake and
        proves nothing about whether anyone would have been told.
        """
        for record in self.tail(500):
            if record.get("ok"):
                return record
        return None
