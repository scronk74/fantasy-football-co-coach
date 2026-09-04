"""One safety check, composed: is my lineup fixable, and did we actually look?

**Why this module exists.** Stage C built and tested the detection logic and
then never called it: `find_problems()` appeared exactly once under `src/`, at
its own definition. `ffcoach league` parsed ESPN and wrote a roster page --
it never loaded the schedule, computed a waiver deadline, picked the user's
team, or asked the advisor anything. Every alert this product promises depends
on a composition step that did not exist, and building a notifier first would
have hidden that step inside a delivery module.

**The one idea worth arguing with.** A check that finds nothing is not the same
as a check that found nothing wrong. If the league did not publish
`lineupSlotCounts` the empty-slot check never ran, and an empty starting slot
-- the most elementary failure in fantasy football -- produces exactly the same
empty finding list as a healthy roster. Same for a week-old cached roster, a
week we had to derive, or a lineup slot ESPN renamed. So `CheckResult` carries
`blind_spots`, and `all_clear` requires **both** no findings and nothing that
stopped us looking. Absence is not evidence; only a positive check is.

That gives three states, not two, and they map onto what a notifier should do:

    problems    findings the user can still act on   -> interrupt
    unverified  nothing found, but we were partly blind -> say so, do not reassure
    all_clear   nothing found, and we looked everywhere -> silence is honest
    pre_draft   the roster does not exist yet          -> nothing to check

The fourth state was not designed; it was found by running this against the
real league on 2026-09-03, four days before the draft. Every starting slot was
legitimately empty, and the check produced nine confident "claim someone by
Friday" findings for a roster the draft would fill on Monday. An empty roster
before a draft is not a lineup problem, and nine wrong alerts on the first
night is how a notification channel becomes something you mute.

Pure: no I/O, no clock, no network. `now` and already-fetched sources are
passed in, which is what makes the whole safety decision runnable offline with
no cookies (`ffcoach check --fixture`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from ffcoach.advisors.lineup import LineupFinding, actionable, find_problems, lock_time
from ffcoach.leagues.base import BENCH_SLOTS, League, LineupLock
from ffcoach.model.deadlines import next_waiver_deadline
from ffcoach.model.week import WeekResolution
from ffcoach.sources.schedule import Schedule

# Fallback only. The league's real clock comes from `league.yaml` (D-065): ESPN
# publishes `waiverProcessHour` as a bare integer and **no timezone field
# anywhere** -- the whole payload was searched to confirm it -- so 11:00 Eastern
# and 11:00 Pacific are both plausible readings of the same number, three hours
# apart, on a deadline this tool states as fact. When the config cannot be read
# the caller records a blind spot rather than letting the assumption pass as
# knowledge.
LEAGUE_TZ = ZoneInfo("America/New_York")


class CheckError(Exception):
    """The check cannot be run at all, as opposed to finding nothing."""


@dataclass(frozen=True)
class SourceHealth:
    """One input's provenance, carried through to the page and the log.

    Mirrors `SourceResult` deliberately rather than reusing it: that type owns
    response *text*, which nothing downstream of here should be able to touch.
    """

    name: str
    age_seconds: float
    stale: bool
    error: str | None = None


@dataclass(frozen=True)
class CheckResult:
    """Everything one run of the check concluded, and how much to trust it."""

    week: int
    week_source: str
    team_name: str
    team_abbrev: str = ""
    findings: list[LineupFinding] = field(default_factory=list)
    actionable: list[LineupFinding] = field(default_factory=list)
    sources: tuple[SourceHealth, ...] = ()
    # Reasons this run could not see the whole picture. Non-empty means an
    # empty `findings` must not be read as "nothing is wrong".
    blind_spots: tuple[str, ...] = ()
    # When the next starting slot freezes. Present even in a clean week: the
    # user's next deadline is information whether or not anything is broken.
    next_lock: dt.datetime | None = None
    waiver_deadline: dt.datetime | None = None

    # True when ESPN says the draft has not happened. The lineup checks are
    # skipped entirely rather than run against a roster that does not exist.
    pre_draft: bool = False

    @property
    def all_clear(self) -> bool:
        return not self.findings and not self.blind_spots and not self.pre_draft

    @property
    def status(self) -> str:
        """`problems` | `pre_draft` | `unverified` | `all_clear`.

        Findings outrank blind spots: something to fix beats something
        unverified, because the user can act on the first one now.
        """
        if self.findings:
            return "problems"
        if self.pre_draft:
            return "pre_draft"
        return "unverified" if self.blind_spots else "all_clear"


def _my_team(league: League):
    """The one team marked as the user's, or refuse.

    Never falls back to `teams[0]`. A SWID that has gone stale, or a cookie
    belonging to a second account, would otherwise check a stranger's roster
    and report it as yours -- silently, and with total confidence.
    """
    mine = [t for t in league.teams if t.is_user_team]
    if not mine:
        raise CheckError(
            "no team in this league is marked as yours; check the SWID in espn.yaml"
        )
    if len(mine) > 1:
        names = ", ".join(t.name for t in mine)
        raise CheckError(f"{len(mine)} teams are marked as yours ({names}); expected one")
    return mine[0]


def _blind_spots(
    league: League,
    week: WeekResolution,
    sources: Sequence[SourceHealth],
) -> tuple[str, ...]:
    """Everything that stopped this run from seeing the whole picture."""
    spots: list[str] = []

    if not league.roster_slots:
        spots.append(
            "empty slot check skipped: the league did not publish lineupSlotCounts, "
            "so we cannot know how many starters are required"
        )
    if week.is_derived:
        spots.append(
            f"week {week.week} was derived, not read from ESPN -- "
            "a wrong week checks the wrong lineup cleanly"
        )
    for source in sources:
        if source.stale:
            spots.append(
                f"{source.name} is stale; serving a cached copy"
                + (f" ({source.error})" if source.error else "")
            )
    # An unrecognized slot id means a starter may be sitting in what we read as
    # a bench slot, invisible to every check above.
    spots.extend(f"ESPN data: {note}" for note in league.diagnostics)
    return tuple(spots)


def _next_lock(
    team,
    schedule: Schedule,
    week: int,
    lock: LineupLock,
    now: dt.datetime,
) -> dt.datetime | None:
    """The next moment one of the user's starting slots stops being changeable."""
    upcoming = []
    for entry in team.roster:
        if entry.lineup_slot in BENCH_SLOTS:
            continue
        when = lock_time(schedule, entry.nfl_team, week, lock)
        if when is not None and when > now:
            upcoming.append(when)
    return min(upcoming) if upcoming else None


def build_check(
    league: League,
    schedule: Schedule,
    week: WeekResolution,
    now: dt.datetime,
    sources: Sequence[SourceHealth] = (),
    tz: dt.tzinfo = LEAGUE_TZ,
    look_ahead: bool = True,
) -> CheckResult:
    """Run the whole safety decision against already-fetched inputs.

    Raises `CheckError` only when the check cannot meaningfully run -- which is
    exactly the ambiguity about *whose* roster this is. Everything else that
    goes wrong becomes a blind spot, because a partial answer plus an honest
    account of what is missing beats no answer.
    """
    team = _my_team(league)
    waiver_deadline = next_waiver_deadline(league.waivers, now, tz)

    # `is False` and not `not`: an absent field is None, and an unknown draft
    # state must not silence the checks. Only ESPN saying so does.
    pre_draft = league.draft_completed is False

    findings = [] if pre_draft else find_problems(
        team,
        schedule,
        week.week,
        now,
        required_slots=league.roster_slots or None,
        waiver_deadline=waiver_deadline,
        look_ahead=look_ahead,
        lock=league.lineup_lock,
    )

    return CheckResult(
        week=week.week,
        week_source=week.source,
        team_name=team.name,
        team_abbrev=team.abbrev,
        findings=findings,
        actionable=actionable(findings, now),
        sources=tuple(sources),
        blind_spots=_blind_spots(league, week, sources),
        next_lock=_next_lock(team, schedule, week.week, league.lineup_lock, now),
        waiver_deadline=waiver_deadline,
        pre_draft=pre_draft,
    )
