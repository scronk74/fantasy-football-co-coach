"""Find starters who cannot score, and who on the bench could replace them.

Pure module: no I/O, no clock of its own -- `now` is passed in. Emits
structured findings, never prose (spec design rule 2).

**Everything here is a fact, not an estimate.** A player whose team is on bye
scores zero. A player ruled OUT scores zero. Neither conclusion depends on a
projection being any good, which is why this ships before the projection
aggregation work and why its alerts are allowed to interrupt the user.

Replacement suggestions are held to the same standard: this module says *"this
bench player is healthy and actually plays this week"*, never *"this bench
player will score more"*. The latter needs projections and belongs to a later
phase.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ffcoach.leagues.base import BENCH_SLOTS, LineupLock, RosterEntry, Team
from ffcoach.model.deadlines import fix_deadline
from ffcoach.sources.schedule import Schedule

# Used when a caller does not supply one: ESPN's default, per-player locking.
_DEFAULT_LOCK = LineupLock()

# Which bench positions may fill a starting slot.
_SLOT_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "QB": ("QB",),
    "RB": ("RB",),
    "WR": ("WR",),
    "TE": ("TE",),
    "FLEX": ("RB", "WR", "TE"),
    "K": ("K",),
    "DEF": ("DEF",),
}

# Lower sorts first. A bye is knowable days ahead; an OUT ruling often is not,
# so it is the more urgent surprise. An empty slot ranks with OUT: both are a
# certain zero in a slot that is still changeable.
_SEVERITY = {"empty_slot": 0, "out": 0, "bye": 1, "bye_next_week": 2}


@dataclass(frozen=True)
class LineupFinding:
    kind: str  # "empty_slot" | "out" | "bye" | "bye_next_week"
    player_name: str
    position: str
    lineup_slot: str
    nfl_team: str
    reason: str
    replacements: tuple[str, ...]
    kickoff: dt.datetime | None
    locked: bool
    # When this must actually be fixed by, which is not always kickoff -- see
    # model/deadlines.py. None means a claim is needed but the league never
    # published its waiver schedule.
    deadline: dt.datetime | None = None
    # When the slot itself stops being changeable. Equal to `kickoff` under
    # per-player locking; the week's *first* kickoff under a weekly lock, where
    # a Monday-night starter freezes on Thursday. Kept separate from `kickoff`
    # because under a weekly lock they are genuinely different facts: one is
    # when he plays, the other is when you lose the ability to bench him.
    locks_at: dt.datetime | None = None
    # True when no bench player can fill the slot, so the fix requires adding
    # someone rather than swapping.
    needs_waiver: bool = False

    @property
    def severity(self) -> int:
        return _SEVERITY.get(self.kind, 9)


def _eligible(slot: str, position: str) -> bool:
    return position in _SLOT_ELIGIBILITY.get(slot, (slot,))


def lock_time(
    schedule: Schedule, team: str, week: int, lock: LineupLock
) -> dt.datetime | None:
    """When a player in `team` stops being movable, honoring the league's rule.

    Under a weekly lock every slot freezes together at the week's first kickoff,
    so all deadlines collapse to that one moment (C5.3). Under the per-player
    default each player carries his own.
    """
    if lock.is_weekly:
        windows = schedule.lock_windows(week)
        return windows[0] if windows else None
    return schedule.kickoff(team, week)


def _reason(
    kind: str, player: RosterEntry | None, slot: str, replacements: tuple[str, ...]
) -> str:
    """One short sentence explaining the finding.

    Mirrors the clause-joining idiom in advisors/draft.py:_reason -- spec UX
    rule 4, no unexplained flag in either mode.
    """
    if kind == "empty_slot":
        head = f"Your {slot} slot is empty"
    elif kind == "bye_next_week":
        head = f"{player.nfl_team} is on bye next week"
    elif kind == "bye":
        head = f"{player.nfl_team} is on bye"
    else:
        status = (player.injury_status or "OUT").replace("_", " ").title()
        head = f"Listed {status}"

    if not replacements:
        if kind == "bye_next_week":
            return f"{head}, and nothing on your bench covers the slot. Claim someone."
        return f"{head}, and no healthy bench player fits this slot."
    if len(replacements) == 1:
        return f"{head}. {replacements[0]} is available and plays this week."
    listed = ", ".join(replacements[:2])
    return f"{head}. Available this week: {listed}."


def find_replacements(
    team: Team, slot: str, schedule: Schedule, week: int
) -> tuple[str, ...]:
    """Bench players who fit the slot, are healthy, and actually play.

    No projections involved -- purely "can this person score at all".
    """
    out: list[str] = []
    for entry in team.roster:
        if entry.is_starter or not _eligible(slot, entry.position):
            continue
        if entry.is_certainly_out:
            continue
        if schedule.is_on_bye(entry.nfl_team, week):
            continue
        out.append(entry.player_name)
    return tuple(out)


def find_empty_slots(
    team: Team,
    required_slots: dict[str, int],
    schedule: Schedule,
    week: int,
    waiver_deadline: dt.datetime | None = None,
    lock: LineupLock | None = None,
    now: dt.datetime | None = None,
) -> list[LineupFinding]:
    """Starting slots the league requires that hold no player.

    Found by *counting*, not by iterating the roster -- an empty slot has no
    roster entry to iterate, which is exactly why the first implementation
    could not see it. A slot with nobody in it is the most certain zero in
    fantasy football and the most elementary lineup failure there is.

    Bench and IR slots are excluded: an empty bench costs nothing.
    """
    lock = lock or _DEFAULT_LOCK
    filled: dict[str, int] = {}
    for entry in team.roster:
        if entry.is_starter:
            filled[entry.lineup_slot] = filled.get(entry.lineup_slot, 0) + 1

    findings: list[LineupFinding] = []
    for slot, required in sorted(required_slots.items()):
        if slot in BENCH_SLOTS:
            continue
        missing = required - filled.get(slot, 0)
        replacements = find_replacements(team, slot, schedule, week)
        # An empty slot has no player, so under per-player locking there is no
        # kickoff to freeze it -- it stays fixable all week. A weekly lock is
        # the exception: the empty slot freezes with everything else.
        locks_at = _weekly_lock(schedule, week, lock)
        deadline, needs_waiver = fix_deadline(
            locks_at,
            _replacement_kickoffs(team, replacements, schedule, week, lock),
            waiver_deadline,
        )
        for _ in range(max(0, missing)):
            findings.append(
                LineupFinding(
                    kind="empty_slot",
                    player_name="",
                    position=slot,
                    lineup_slot=slot,
                    nfl_team="",
                    reason=_reason("empty_slot", None, slot, replacements),
                    replacements=replacements,
                    kickoff=None,
                    locked=_is_locked(locks_at, now),
                    deadline=deadline,
                    locks_at=locks_at,
                    needs_waiver=needs_waiver,
                )
            )
    return findings


def _weekly_lock(
    schedule: Schedule, week: int, lock: LineupLock
) -> dt.datetime | None:
    """The week's shared freeze moment, or None when slots lock individually."""
    if not lock.is_weekly:
        return None
    windows = schedule.lock_windows(week)
    return windows[0] if windows else None


def _is_locked(locks_at: dt.datetime | None, now: dt.datetime | None) -> bool:
    return locks_at is not None and now is not None and locks_at <= now


def find_upcoming_byes(
    team: Team,
    schedule: Schedule,
    week: int,
    waiver_deadline: dt.datetime | None,
) -> list[LineupFinding]:
    """Starters on bye *next* week with nothing on the bench to cover them.

    Reacting during the bye week is structurally too late: by then every useful
    replacement has been claimed. This is the look-ahead that makes the waiver
    deadline actionable (D-014).

    Only reported when the bench cannot cover it. A bye you can absorb with a
    bench player is not a problem worth a message.
    """
    findings: list[LineupFinding] = []
    ahead = week + 1

    for entry in team.roster:
        if not entry.is_starter or not schedule.is_on_bye(entry.nfl_team, ahead):
            continue
        # Who could cover this slot *next* week, not this one.
        cover = find_replacements(team, entry.lineup_slot, schedule, ahead)
        if cover:
            continue
        findings.append(
            LineupFinding(
                kind="bye_next_week",
                player_name=entry.player_name,
                position=entry.position,
                lineup_slot=entry.lineup_slot,
                nfl_team=entry.nfl_team,
                reason=_reason("bye_next_week", entry, entry.lineup_slot, ()),
                replacements=(),
                kickoff=None,
                locked=False,
                deadline=waiver_deadline,
                needs_waiver=True,
            )
        )
    return findings


def find_problems(
    team: Team,
    schedule: Schedule,
    week: int,
    now: dt.datetime,
    required_slots: dict[str, int] | None = None,
    waiver_deadline: dt.datetime | None = None,
    look_ahead: bool = False,
    lock: LineupLock | None = None,
) -> list[LineupFinding]:
    """Starters who cannot score this week, most urgent first.

    `required_slots` maps lineup slot to how many the league starts, and comes
    from ESPN's `rosterSettings.lineupSlotCounts` (falling back to
    `LeagueConfig.roster`). When it is omitted the empty-slot check is skipped
    entirely rather than guessed at: without slot counts we genuinely cannot
    know how many starters the league requires, and inventing a number would
    manufacture findings or, worse, false silence.

    Findings whose kickoff has already passed are still returned, flagged
    `locked`, so callers can report them without alerting. Silently dropping
    them would make a missed player indistinguishable from a clean lineup.
    """
    lock = lock or _DEFAULT_LOCK
    findings: list[LineupFinding] = []

    if required_slots:
        findings.extend(
            find_empty_slots(
                team, required_slots, schedule, week, waiver_deadline, lock, now
            )
        )

    for entry in team.roster:
        if not entry.is_starter:
            continue

        on_bye = schedule.is_on_bye(entry.nfl_team, week)
        if entry.is_certainly_out:
            kind = "out"
        elif on_bye:
            kind = "bye"
        else:
            continue

        kickoff = schedule.kickoff(entry.nfl_team, week)
        locks_at = lock_time(schedule, entry.nfl_team, week, lock)
        replacements = find_replacements(team, entry.lineup_slot, schedule, week)
        deadline, needs_waiver = fix_deadline(
            locks_at,
            _replacement_kickoffs(team, replacements, schedule, week, lock),
            waiver_deadline,
        )

        findings.append(
            LineupFinding(
                kind=kind,
                player_name=entry.player_name,
                position=entry.position,
                lineup_slot=entry.lineup_slot,
                nfl_team=entry.nfl_team,
                reason=_reason(kind, entry, entry.lineup_slot, replacements),
                replacements=replacements,
                kickoff=kickoff,
                locked=_is_locked(locks_at, now),
                deadline=deadline,
                locks_at=locks_at,
                needs_waiver=needs_waiver,
            )
        )

    if look_ahead:
        findings.extend(find_upcoming_byes(team, schedule, week, waiver_deadline))

    findings.sort(key=lambda f: (f.locked, f.severity, f.player_name))
    return findings


def _replacement_kickoffs(
    team: Team,
    names: tuple[str, ...],
    schedule: Schedule,
    week: int,
    lock: LineupLock,
) -> tuple[dt.datetime, ...]:
    """When each replacement stops being startable.

    Under a weekly lock these all collapse to the same moment, which is exactly
    what makes `fix_deadline`'s `min()` produce one shared deadline.
    """
    by_name = {e.player_name: e for e in team.roster}
    kicks = []
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            continue
        kick = lock_time(schedule, entry.nfl_team, week, lock)
        if kick is not None:
            kicks.append(kick)
    return tuple(kicks)


def actionable(findings: list[LineupFinding]) -> list[LineupFinding]:
    """Only what the user can still do something about."""
    return [f for f in findings if not f.locked]
