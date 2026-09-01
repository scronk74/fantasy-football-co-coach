"""When a lineup problem must actually be fixed by.

The reframe this module exists for (D-014): the original design timed every
alert off kickoff, which is the wrong deadline whenever the fix is not a lineup
swap.

If a starter is out and **no bench player can replace him**, swapping is not an
option -- the fix is a waiver claim, and claims process on the league's schedule,
not at kickoff. An alert that arrives Sunday morning is comfortably before the
lineup locks and hopelessly after every useful replacement has been claimed.

So the deadline is not a property of the *problem*, it is a property of the
*available fix*:

    bench replacement exists  ->  act before your options start playing
    no bench replacement      ->  act before waivers next process

**The correction that produced `FixPlan`.** The first version of that second
rule returned `min(waiver_deadline, lock)` and a `needs_waiver=True` flag. The
clamp stopped the deadline printing *after* the slot froze, which was the
visible symptom -- but it fixed the number and left the advice false. A
Thursday-night starter is OUT, nothing on the bench fits, and waivers next
process Friday: clamping yields "claim someone by Thursday 8:15", which is a
plausible-looking instruction to do something that cannot happen. The claim
does not process until Friday no matter when it is submitted.

A time alone cannot express that. So the answer is a `FixPlan` -- *what kind of
action is still available*, and only then by when. When no claim can land in
time the honest answer is not an earlier deadline; it is that a claim is the
wrong instrument, and a free agent added directly is the only path left.

Pure module: no I/O, no clock of its own. `FixPlan` deliberately takes no
`now`: whether a deadline has *passed* is a separate question, asked by
`LineupFinding.is_actionable`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from ffcoach.leagues.base import WaiverSettings

# Monday=0, matching datetime.weekday().
_WEEKDAYS = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}

_SEARCH_DAYS = 8  # a week plus one, enough to find the next matching weekday


def next_waiver_deadline(
    waivers: WaiverSettings,
    now: dt.datetime,
    tz: dt.tzinfo,
) -> dt.datetime | None:
    """The next moment waivers process, or None if the league never says.

    Returning None rather than guessing a day matters: a fabricated deadline
    would be reported to the user as fact and could be days wrong. Callers
    treat None as "we know a claim is needed but not by when".
    """
    if not waivers.is_known:
        return None

    wanted = {_WEEKDAYS[d] for d in waivers.process_days if d in _WEEKDAYS}
    if not wanted:
        return None

    local = now.astimezone(tz)
    for offset in range(_SEARCH_DAYS):
        day = (local + dt.timedelta(days=offset)).date()
        if day.weekday() not in wanted:
            continue
        candidate = dt.datetime(
            day.year, day.month, day.day, waivers.process_hour, 0, tzinfo=tz
        )
        if candidate > local:
            return candidate
    return None


class FixKind(Enum):
    """What sort of action can still repair a lineup problem.

    Ordered from most to least certain. Every value is one we can actually
    derive from data on hand -- there is no `FREE_AGENT_ADD` here because
    nothing in this project fetches the free-agent pool, and a kind we can
    never emit would be a promise the code does not keep.
    """

    # A bench player fits the slot, is healthy, and plays. Certain, and we can
    # name him.
    BENCH_SWAP = "bench_swap"
    # Nobody on the bench fits, but waivers process before the slot locks, so
    # a claim submitted now can arrive in time.
    WAIVER_CLAIM = "waiver_claim"
    # Nobody on the bench fits and the next waiver run is after the lock. A
    # claim is the wrong instrument; only a free agent added directly can still
    # land, and we cannot see whether one exists. Says so rather than inventing
    # a deadline for the claim.
    ADD_BEFORE_LOCK = "add_before_lock"
    # Nobody on the bench fits and the league published no waiver schedule, so
    # we genuinely cannot say when a claim would process.
    UNKNOWN = "unknown"


# One primary verb per action, so the user never has to infer the transaction
# type from a sentence.
_VERBS = {
    FixKind.BENCH_SWAP: "Swap",
    FixKind.WAIVER_CLAIM: "Claim",
    FixKind.ADD_BEFORE_LOCK: "Add",
    FixKind.UNKNOWN: "Review",
}


@dataclass(frozen=True)
class FixPlan:
    """How a problem can be fixed, and by when."""

    kind: FixKind
    # None only when nothing in the data bounds it: no lock, no waiver run.
    deadline: dt.datetime | None = None

    @property
    def verb(self) -> str:
        return _VERBS[self.kind]

    @property
    def needs_waiver(self) -> bool:
        """True when the fix requires acquiring a player rather than swapping."""
        return self.kind is not FixKind.BENCH_SWAP

    @property
    def claim_lands_in_time(self) -> bool:
        """False when a waiver claim cannot possibly process before the lock."""
        return self.kind in (FixKind.BENCH_SWAP, FixKind.WAIVER_CLAIM)


def plan_fix(
    slot_locks_at: dt.datetime | None,
    replacement_locks: tuple[dt.datetime, ...],
    waiver_deadline: dt.datetime | None,
) -> FixPlan:
    """The best available action for one problem, and its real deadline.

    With at least one bench replacement, the deadline is the earliest moment
    your options start disappearing -- the first of the broken slot's own lock
    and the replacements' locks, after which that replacement is no longer
    startable.

    With no replacement someone must be acquired, and which acquisition is even
    possible depends on whether the waiver run beats the lock. That comparison
    is the whole reason this returns a kind rather than a timestamp.

    The arguments are lock times, not kickoffs: under a weekly lineup lock a
    player freezes at the week's first game rather than his own (C5).
    """
    if replacement_locks:
        candidates = [k for k in (slot_locks_at, *replacement_locks) if k is not None]
        return FixPlan(FixKind.BENCH_SWAP, min(candidates) if candidates else None)

    if waiver_deadline is None:
        return FixPlan(FixKind.UNKNOWN, slot_locks_at)

    # `>=` rather than `>`: a claim that processes at the exact moment the
    # lineup freezes has not made it into the lineup. Ties fail safe.
    if slot_locks_at is not None and waiver_deadline >= slot_locks_at:
        return FixPlan(FixKind.ADD_BEFORE_LOCK, slot_locks_at)

    return FixPlan(FixKind.WAIVER_CLAIM, waiver_deadline)
