"""Decide which NFL week it is.

Small, but load-bearing: every finding, alert, and page in this system is
week-indexed, and until this existed nothing determined the index -- callers
passed a week in and nobody computed it.

**ESPN's own number is preferred over anything derived** (D-013). Computing the
week from the calendar means owning the rollover moment, and a rollover bug does
not degrade gracefully: it silently evaluates the wrong week's roster and
reports a clean lineup for a week that is not being played. Taking ESPN's
`scoringPeriodId` also guarantees agreement with whatever the league itself
thinks the week is.

Derivation exists only as a fallback for when the league fetch fails and a
stale-cache run still has to do something useful. It reports itself as derived
so callers can say so rather than quietly presenting a guess as fact.

Pure module: no I/O, no clock of its own -- `now` is passed in.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ffcoach.sources.schedule import Schedule

# NFL regular season. Weeks outside this are not something this tool handles:
# preseason has no fantasy relevance and the playoff weeks reuse numbering.
MIN_WEEK = 1
MAX_WEEK = 18

# Generous upper bound on a game's length, used to decide when a week's last
# game is finally over. Overtime and long reviews push past three hours.
_GAME_LENGTH = dt.timedelta(hours=4)


class WeekUnavailable(Exception):
    """Raised when the current week cannot be established.

    Deliberately an error rather than a default. A wrong week is worse than no
    week: it produces confident, wrong findings.
    """


@dataclass(frozen=True)
class WeekResolution:
    week: int
    source: str  # "espn" | "derived"

    @property
    def is_derived(self) -> bool:
        return self.source == "derived"

    @property
    def note(self) -> str:
        if self.source == "espn":
            return f"week {self.week} (from ESPN)"
        return f"week {self.week} (derived from the schedule; ESPN was unreachable)"


def _valid(week: int | None) -> bool:
    return week is not None and MIN_WEEK <= week <= MAX_WEEK


def derive_week(schedule: Schedule, now: dt.datetime) -> int | None:
    """The earliest week whose games are not all finished.

    During a week's games that week is current; once its last game ends, the
    next week becomes current. Returns None once the season is over.
    """
    for week in sorted(schedule.weeks):
        windows = schedule.lock_windows(week)
        if not windows:
            continue
        if now < max(windows) + _GAME_LENGTH:
            return week
    return None


def resolve_week(
    espn_week: int | None,
    schedule: Schedule,
    now: dt.datetime,
) -> WeekResolution:
    """ESPN's week if usable, otherwise derive one, otherwise fail loudly.

    `espn_week` is `League.current_week`. It is passed as a plain int rather
    than a League so this module stays independent of the leagues package.
    """
    if _valid(espn_week):
        return WeekResolution(week=int(espn_week), source="espn")

    derived = derive_week(schedule, now)
    if _valid(derived):
        return WeekResolution(week=int(derived), source="derived")

    raise WeekUnavailable(
        "could not establish the current NFL week: ESPN reported "
        f"{espn_week!r} and the schedule derived {derived!r}. Refusing to "
        "guess, since evaluating the wrong week reports a clean lineup for a "
        "week that is not being played."
    )
