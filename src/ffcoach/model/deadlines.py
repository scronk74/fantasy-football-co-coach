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

Pure module: no I/O, no clock of its own.
"""

from __future__ import annotations

import datetime as dt

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


def fix_deadline(
    slot_locks_at: dt.datetime | None,
    replacement_locks: tuple[dt.datetime, ...],
    waiver_deadline: dt.datetime | None,
) -> tuple[dt.datetime | None, bool]:
    """`(deadline, needs_waiver)` for one problem.

    With at least one bench replacement, the deadline is the earliest moment
    your options start disappearing -- the first of the broken slot's own lock
    and the replacements' locks, after which that replacement is no longer
    startable.

    With no replacement, a claim is required and the waiver schedule governs --
    **but never past the lock.** A claim that processes Friday cannot be started
    in a lineup that froze Thursday, so the lock is a hard ceiling on every
    deadline. Without that clamp a locked slot advertises a future deadline and
    reads as "you still have time" precisely when you have none.

    The arguments are lock times, not kickoffs: under a weekly lineup lock a
    player freezes at the week's first game rather than his own (C5).
    """
    if replacement_locks or slot_locks_at is not None:
        if not replacement_locks and slot_locks_at is not None:
            # Nobody to swap in, but the slot itself still locks. A claim is
            # needed; the waiver deadline governs if it lands before the lock.
            if waiver_deadline is not None:
                return min(waiver_deadline, slot_locks_at), True
            return slot_locks_at, True
        candidates = [k for k in (slot_locks_at, *replacement_locks) if k is not None]
        if candidates:
            return min(candidates), False

    return waiver_deadline, True
