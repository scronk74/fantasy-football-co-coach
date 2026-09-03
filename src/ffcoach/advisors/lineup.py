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

Two responsibilities that used to live here have moved out, because both were
being decided per-finding when they are properly decided per-roster or
per-model: who covers which opening is now `advisors/roster_plan.py`, and what
kind of action is even possible is now `model/deadlines.py`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ffcoach.advisors.roster_plan import Assignment, assign_replacements
from ffcoach.leagues.base import BENCH_SLOTS, IR_SLOT, LineupLock, RosterEntry, Team
from ffcoach.model.deadlines import FixKind, FixPlan, plan_fix
from ffcoach.sources.schedule import Schedule

# Used when a caller does not supply one: ESPN's default, per-player locking.
_DEFAULT_LOCK = LineupLock()

# Which bench positions may fill a starting slot.
#
# Hardcoded, and knowingly so: this is the one place league format is not read
# from config, which makes superflex and IDP leagues silently wrong. Left as-is
# because the slot *names* still come from ESPN and an unrecognized slot falls
# through to "only its own position fits" -- conservative, not fabricated. See
# the review reply for why this is a portability defect rather than a live one.
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
    # How this can be fixed and by when. Replaced a `(deadline, needs_waiver)`
    # pair that could describe an impossible transaction as a plausible one.
    fix: FixPlan = field(default_factory=lambda: FixPlan(FixKind.UNKNOWN))
    # When the slot itself stops being changeable. Equal to `kickoff` under
    # per-player locking for a player who actually plays; the week's *first*
    # kickoff under a weekly lock, where a Monday-night starter freezes on
    # Thursday. Kept separate from `kickoff` because under a weekly lock they
    # are genuinely different facts: one is when he plays, the other is when
    # you lose the ability to bench him.
    locks_at: dt.datetime | None = None
    # Healthy players sitting in an IR slot who fit. Not replacements: ESPN
    # will not start a player straight from IR, so activating one is a separate
    # prior action with its own roster-space consequences. Reported rather than
    # dropped so the option is not invisible.
    ir_candidates: tuple[str, ...] = ()
    # True when `locks_at` was inferred rather than read -- the game exists but
    # its kickoff time is not published yet, so we used the week's first game
    # and will alert earlier than strictly necessary.
    lock_is_estimated: bool = False

    @property
    def severity(self) -> int:
        return _SEVERITY.get(self.kind, 9)

    @property
    def deadline(self) -> dt.datetime | None:
        return self.fix.deadline

    @property
    def needs_waiver(self) -> bool:
        return self.fix.needs_waiver

    def is_actionable(self, now: dt.datetime | None = None) -> bool:
        """Whether the user can still do something about this.

        Three separate ways to be past helping, and the old check tested only
        the first: the slot is frozen, the fix's own deadline has gone by (a
        bench replacement whose game already kicked off is no longer a
        replacement), or no action of any kind remains.
        """
        if self.locked:
            return False
        if now is not None and self.deadline is not None and self.deadline <= now:
            return False
        return True


def _eligible(slot: str, position: str) -> bool:
    return position in _SLOT_ELIGIBILITY.get(slot, (slot,))


def lock_time(
    schedule: Schedule, team: str, week: int, lock: LineupLock
) -> dt.datetime | None:
    """When a player in `team` stops being movable, honoring the league's rule.

    Under a weekly lock every slot freezes together at the week's first kickoff,
    so all deadlines collapse to that one moment (C5.3). Under the per-player
    default each player carries his own. None when he has no game this week, or
    when the game's time is not published -- callers distinguish those with
    `Schedule.status`.
    """
    if lock.is_weekly:
        windows = schedule.lock_windows(week)
        return windows[0] if windows else None
    return schedule.kickoff(team, week)


def slot_lock(
    schedule: Schedule, team: str | None, week: int, lock: LineupLock
) -> tuple[dt.datetime | None, bool]:
    """`(when this slot stops being fixable, whether that was estimated)`.

    The occupant's own kickoff whenever there is one. The interesting cases are
    the two where there is not:

    * **An empty slot, or a starter on bye.** No kickoff belongs to it, and the
      old code therefore treated it as never locking -- so a Week 5 empty-slot
      finding was still reported as actionable in January. It is not frozen by
      any one game, but once the week's *last* kickoff passes, nothing anyone
      adds can put a point in it. That final kickoff is the true bound.
    * **A game whose time is still TBD.** The row exists but the clock does
      not. Falls back to the week's *first* kickoff and says so, matching the
      precedent set for an unrecognized lock setting: fail toward the earlier
      deadline, so we alert too soon rather than too late.
    """
    if lock.is_weekly:
        windows = schedule.lock_windows(week)
        return (windows[0] if windows else None), False

    windows = schedule.lock_windows(week)
    if team is None:
        return (windows[-1] if windows else None), False

    status = schedule.status(team, week)
    if status == "playing" and schedule.kickoff_known(team, week):
        return schedule.kickoff(team, week), False
    if status == "playing":
        return (windows[0] if windows else None), True
    # On bye, or a team the schedule does not know: the slot itself is still
    # changeable right up until the week's last game starts.
    return (windows[-1] if windows else None), False


def _reason(
    kind: str,
    player: RosterEntry | None,
    slot: str,
    replacements: tuple[str, ...],
    fix: FixPlan,
    ir_candidates: tuple[str, ...] = (),
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

    if replacements:
        if len(replacements) == 1:
            return f"{head}. {replacements[0]} is available and plays this week."
        listed = ", ".join(replacements[:2])
        return f"{head}. Available this week: {listed}."

    tail = "and no healthy bench player fits this slot"
    if ir_candidates:
        tail += f" ({ir_candidates[0]} would have to come off IR first)"

    if fix.kind is FixKind.ADD_BEFORE_LOCK:
        return (
            f"{head}, {tail}. Waivers do not process again before this locks, "
            "so a claim cannot arrive in time — add a free agent."
        )
    if fix.kind is FixKind.UNKNOWN:
        return f"{head}, {tail}, and the league publishes no waiver schedule."
    return f"{head}, {tail}. Claim someone."


def find_replacements(
    team: Team, slot: str, schedule: Schedule, week: int
) -> tuple[str, ...]:
    """Bench players who fit the slot, are healthy, and actually play.

    No projections involved -- purely "can this person score at all".

    IR is excluded even when its occupant is healthy: ESPN does not allow a
    player to be started out of an IR slot, so offering him as a direct swap
    describes a move the site will refuse. `find_ir_candidates` reports him
    separately.
    """
    out: list[str] = []
    for entry in team.roster:
        if entry.is_starter or entry.lineup_slot == IR_SLOT:
            continue
        if not _eligible(slot, entry.position):
            continue
        if entry.is_certainly_out:
            continue
        if schedule.status(entry.nfl_team, week) != "playing":
            continue
        out.append(entry.player_name)
    return tuple(out)


def find_ir_candidates(
    team: Team, slot: str, schedule: Schedule, week: int
) -> tuple[str, ...]:
    """Healthy IR occupants who fit the slot once activated.

    Rare but real: a player returns, ESPN keeps him in the IR slot until you
    move him, and he is a legitimate fix that costs an extra step (and, if the
    roster is full, a drop).
    """
    return tuple(
        e.player_name
        for e in team.roster
        if e.lineup_slot == IR_SLOT
        and _eligible(slot, e.position)
        and not e.is_certainly_out
        and schedule.status(e.nfl_team, week) == "playing"
    )


@dataclass(frozen=True)
class _Opening:
    """A slot needing a fix, before anyone has been allocated to it."""

    kind: str
    slot: str
    entry: RosterEntry | None
    candidates: tuple[str, ...]
    ir_candidates: tuple[str, ...]
    kickoff: dt.datetime | None
    locks_at: dt.datetime | None
    lock_is_estimated: bool


def _empty_openings(
    team: Team,
    required_slots: dict[str, int],
    schedule: Schedule,
    week: int,
    lock: LineupLock,
) -> list[_Opening]:
    """Starting slots the league requires that hold no player.

    Found by *counting*, not by iterating the roster -- an empty slot has no
    roster entry to iterate, which is exactly why the first implementation
    could not see it. A slot with nobody in it is the most certain zero in
    fantasy football and the most elementary lineup failure there is.

    Bench and IR slots are excluded: an empty bench costs nothing.
    """
    filled: dict[str, int] = {}
    for entry in team.roster:
        if entry.is_starter:
            filled[entry.lineup_slot] = filled.get(entry.lineup_slot, 0) + 1

    openings: list[_Opening] = []
    for slot, required in sorted(required_slots.items()):
        if slot in BENCH_SLOTS:
            continue
        missing = required - filled.get(slot, 0)
        if missing <= 0:
            continue
        locks_at, estimated = slot_lock(schedule, None, week, lock)
        for _ in range(missing):
            openings.append(
                _Opening(
                    kind="empty_slot",
                    slot=slot,
                    entry=None,
                    candidates=find_replacements(team, slot, schedule, week),
                    ir_candidates=find_ir_candidates(team, slot, schedule, week),
                    kickoff=None,
                    locks_at=locks_at,
                    lock_is_estimated=estimated,
                )
            )
    return openings


def _broken_openings(
    team: Team, schedule: Schedule, week: int, lock: LineupLock
) -> list[_Opening]:
    """Filled starting slots whose occupant cannot score."""
    openings: list[_Opening] = []
    for entry in team.roster:
        if not entry.is_starter:
            continue

        on_bye = schedule.status(entry.nfl_team, week) == "bye"
        if entry.is_certainly_out:
            kind = "out"
        elif on_bye:
            kind = "bye"
        else:
            continue

        locks_at, estimated = slot_lock(schedule, entry.nfl_team, week, lock)
        openings.append(
            _Opening(
                kind=kind,
                slot=entry.lineup_slot,
                entry=entry,
                candidates=find_replacements(team, entry.lineup_slot, schedule, week),
                ir_candidates=find_ir_candidates(team, entry.lineup_slot, schedule, week),
                kickoff=schedule.kickoff(entry.nfl_team, week),
                locks_at=locks_at,
                lock_is_estimated=estimated,
            )
        )
    return openings


def _to_findings(
    openings: list[_Opening],
    assignments: list[Assignment],
    team: Team,
    schedule: Schedule,
    week: int,
    lock: LineupLock,
    waiver_deadline: dt.datetime | None,
    now: dt.datetime | None,
) -> list[LineupFinding]:
    findings: list[LineupFinding] = []
    for opening, assignment in zip(openings, assignments, strict=True):
        offered = assignment.offered
        fix = plan_fix(
            opening.locks_at,
            _replacement_locks(team, offered, schedule, week, lock),
            waiver_deadline,
        )
        findings.append(
            LineupFinding(
                kind=opening.kind,
                player_name=opening.entry.player_name if opening.entry else "",
                position=opening.entry.position if opening.entry else opening.slot,
                lineup_slot=opening.slot,
                nfl_team=opening.entry.nfl_team if opening.entry else "",
                reason=_reason(
                    opening.kind,
                    opening.entry,
                    opening.slot,
                    offered,
                    fix,
                    opening.ir_candidates,
                ),
                replacements=offered,
                kickoff=opening.kickoff,
                locked=_is_locked(opening.locks_at, now),
                fix=fix,
                locks_at=opening.locks_at,
                ir_candidates=opening.ir_candidates,
                lock_is_estimated=opening.lock_is_estimated,
            )
        )
    return findings


def find_empty_slots(
    team: Team,
    required_slots: dict[str, int],
    schedule: Schedule,
    week: int,
    waiver_deadline: dt.datetime | None = None,
    lock: LineupLock | None = None,
    now: dt.datetime | None = None,
) -> list[LineupFinding]:
    """Empty starting slots on their own, with bench players allocated between them.

    Two empty WR slots and one healthy bench WR yield one fixable finding and
    one that needs an acquisition -- never two findings naming the same man.
    """
    lock = lock or _DEFAULT_LOCK
    openings = _empty_openings(team, required_slots, schedule, week, lock)
    assignments = assign_replacements([o.candidates for o in openings])
    return _to_findings(
        openings, assignments, team, schedule, week, lock, waiver_deadline, now
    )


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
        if not entry.is_starter or schedule.status(entry.nfl_team, ahead) != "bye":
            continue
        # Who could cover this slot *next* week, not this one.
        if find_replacements(team, entry.lineup_slot, schedule, ahead):
            continue
        fix = plan_fix(None, (), waiver_deadline)
        findings.append(
            LineupFinding(
                kind="bye_next_week",
                player_name=entry.player_name,
                position=entry.position,
                lineup_slot=entry.lineup_slot,
                nfl_team=entry.nfl_team,
                reason=_reason("bye_next_week", entry, entry.lineup_slot, (), fix),
                replacements=(),
                kickoff=None,
                locked=False,
                fix=fix,
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

    Empty slots and broken starters compete for the same bench, so they are
    collected first and allocated together. Findings whose slot has already
    locked are still returned, flagged `locked`, so callers can report them
    without alerting. Silently dropping them would make a missed player
    indistinguishable from a clean lineup.
    """
    lock = lock or _DEFAULT_LOCK

    openings: list[_Opening] = []
    if required_slots:
        openings.extend(_empty_openings(team, required_slots, schedule, week, lock))
    openings.extend(_broken_openings(team, schedule, week, lock))

    assignments = assign_replacements([o.candidates for o in openings])
    findings = _to_findings(
        openings, assignments, team, schedule, week, lock, waiver_deadline, now
    )

    if look_ahead:
        findings.extend(find_upcoming_byes(team, schedule, week, waiver_deadline))

    findings.sort(key=lambda f: (f.locked, f.severity, f.player_name))
    return findings


def _replacement_locks(
    team: Team,
    names: tuple[str, ...],
    schedule: Schedule,
    week: int,
    lock: LineupLock,
) -> tuple[dt.datetime, ...]:
    """When each replacement stops being startable.

    Under a weekly lock these all collapse to the same moment, which is exactly
    what makes `plan_fix`'s `min()` produce one shared deadline.
    """
    by_name = {e.player_name: e for e in team.roster}
    locks = []
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            continue
        when = lock_time(schedule, entry.nfl_team, week, lock)
        if when is not None:
            locks.append(when)
    return tuple(locks)


def actionable(
    findings: list[LineupFinding], now: dt.datetime | None = None
) -> list[LineupFinding]:
    """Only what the user can still do something about.

    Pass `now` to also drop findings whose deadline has gone by. Without it
    this answers the weaker question "is the slot still unlocked", which is
    what it always answered and is not enough on its own.
    """
    return [f for f in findings if f.is_actionable(now)]
