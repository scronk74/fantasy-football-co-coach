"""Noticing that the tool itself has stopped working.

D-023 names the case exactly: **expired ESPN cookies produce no alert, which is
indistinguishable from "nothing is wrong."** Every silent failure has that
shape. A check that errors sends nothing, and sending nothing is precisely what
a clean week looks like -- so the better the product gets at staying quiet, the
more dangerous its silence becomes.

Two signals, because they fail in different directions:

**Consecutive failures.** Unambiguous, and needs no assumption about the
schedule: three errored runs in a row is three errored runs in a row whether
the scheduler fires every fifteen minutes or twice a day. This is the cookie
case.

**Silence since the last success.** Catches what failures cannot -- a scheduler
that was never loaded, or was unloaded, logs *nothing*, so there are no
failures to count. Measured from the last **success**, never the last run: a
machine erroring every fifteen minutes since Thursday is not alive, and
measuring from the last run would read constant failure as health.

**What this module cannot do**, and no amount of care here will fix: a process
on a dead machine reports nothing about the machine being dead. Everything
above runs on the same host as the scheduler. The off-host half is
`notify/heartbeat.py`, and the split is deliberate -- see R-3.

Pure: records in, an alert or `None` out. No clock, no I/O.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field

# One alert per threshold crossed. A long outage is re-raised as it worsens
# without being repeated on every scheduler cycle -- the same instinct as the
# two-strike policy, applied to an outage rather than to a lineup problem.
ESCALATION = (
    dt.timedelta(hours=12),
    dt.timedelta(hours=24),
    dt.timedelta(days=2),
    dt.timedelta(days=7),
)


@dataclass(frozen=True)
class WatchdogConfig:
    # How long without a *successful* run before that is itself news. The right
    # value depends on the schedule, which this module deliberately cannot see.
    max_silence: dt.timedelta = dt.timedelta(hours=12)
    # Below this, a failure is transient. Two is too eager: a single flaky
    # fetch would page you.
    min_consecutive_failures: int = 3


@dataclass(frozen=True)
class WatchdogAlert:
    reason: str
    # Stable while the outage is at the same severity, so it can be deduplicated
    # like any other alert; changes when it crosses the next threshold.
    key: str
    last_success: dt.datetime | None = None
    since_success: dt.timedelta | None = None
    consecutive_failures: int = 0
    blind_spots: tuple[str, ...] = field(default_factory=tuple)


def _parsed(record: dict) -> dt.datetime | None:
    """The record's timestamp, or `None` if it does not have a usable one.

    A missing or malformed `at` is skipped rather than guessed. Inventing a
    time here would manufacture an outage out of a corrupt line, which is the
    same class of mistake as a schedule gap becoming a bye.
    """
    raw = record.get("at")
    if not isinstance(raw, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    # Old or hand-edited lines may be naive, and comparing naive to aware
    # raises. Reading as UTC is what every writer in this codebase meant.
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _escalation_step(elapsed: dt.timedelta) -> int:
    return sum(1 for threshold in ESCALATION if elapsed >= threshold)


def _hours(delta: dt.timedelta) -> str:
    total = delta.total_seconds() / 3600
    return f"{round(total)}h" if total < 48 else f"{round(total / 24)}d"


def assess(
    records: Sequence[dict],
    now: dt.datetime,
    config: WatchdogConfig,
) -> WatchdogAlert | None:
    """Whether the tool has stopped working, newest record first.

    Returns `None` for a healthy install *and* for a fresh one: an empty log
    means nothing has ever run, which is a new setup rather than an outage.
    """
    usable = [(r, at) for r in records if (at := _parsed(r)) is not None]
    if not usable:
        return None

    streak = 0
    for record, _ in usable:
        if record.get("ok"):
            break
        streak += 1

    successes = [at for record, at in usable if record.get("ok")]
    last_success = max(successes) if successes else None
    since = now - last_success if last_success else None

    if streak >= config.min_consecutive_failures:
        detail = (
            f"last success {_hours(since)} ago" if since else "no run has ever succeeded"
        )
        step = _escalation_step(since) if since else len(ESCALATION)
        return WatchdogAlert(
            reason=(
                f"ffcoach has failed {streak} runs in a row ({detail}). "
                "Alerts are not being sent — check the ESPN cookies first."
            ),
            key=f"watchdog:failing:{step}",
            last_success=last_success,
            since_success=since,
            consecutive_failures=streak,
        )

    if last_success is None:
        return WatchdogAlert(
            reason=(
                "ffcoach has never completed a run, so no alert has ever been "
                "sent. Run `ffcoach doctor`."
            ),
            key="watchdog:never",
        )

    if since is not None and since >= config.max_silence:
        return WatchdogAlert(
            reason=(
                f"ffcoach has not completed a run in {_hours(since)}. "
                "Nothing is watching your lineup — check that the scheduler is loaded."
            ),
            key=f"watchdog:silent:{_escalation_step(since)}",
            last_success=last_success,
            since_success=since,
        )

    return None
