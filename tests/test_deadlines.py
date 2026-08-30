import datetime as dt

import pytest

from ffcoach.leagues.base import WaiverSettings
from ffcoach.model.deadlines import fix_deadline, next_waiver_deadline
from ffcoach.sources.schedule import EASTERN

# The live ESPN default league: six days a week at 11:00. Deliberately not
# "Wednesday morning" -- that assumption was wrong, which is why this is read
# from the league rather than hardcoded.
LIVE = WaiverSettings(
    process_days=("MONDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"),
    process_hour=11,
)
TUESDAY_ONLY = WaiverSettings(process_days=("TUESDAY",), process_hour=3)


def et(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=EASTERN)


# --- waiver schedule ---


def test_finds_the_next_processing_time():
    # Tue 2025-09-09 -> next Tuesday-only run is Tue the 16th at 03:00.
    got = next_waiver_deadline(TUESDAY_ONLY, et(2025, 9, 9, 8), EASTERN)
    assert got == et(2025, 9, 16, 3)


def test_same_day_before_the_hour_counts_as_today():
    got = next_waiver_deadline(TUESDAY_ONLY, et(2025, 9, 9, 1), EASTERN)
    assert got == et(2025, 9, 9, 3)


def test_a_multi_day_league_finds_the_nearest_day():
    # Thu 2025-09-11 13:00; next of MON/WED/THU/FRI/SAT/SUN at 11:00 is Friday.
    got = next_waiver_deadline(LIVE, et(2025, 9, 11, 13), EASTERN)
    assert got == et(2025, 9, 12, 11)


def test_returns_none_when_the_league_never_says():
    assert next_waiver_deadline(WaiverSettings(), et(2025, 9, 9), EASTERN) is None


def test_unknown_day_names_are_ignored_rather_than_guessed():
    bogus = WaiverSettings(process_days=("SOMEDAY",), process_hour=11)
    assert next_waiver_deadline(bogus, et(2025, 9, 9), EASTERN) is None


def test_result_is_always_in_the_future():
    now = et(2025, 9, 10, 11, 30)
    got = next_waiver_deadline(LIVE, now, EASTERN)
    assert got > now


# --- which deadline governs ---

KICK_EARLY = et(2025, 9, 14, 13)
KICK_LATE = et(2025, 9, 15, 20, 15)
WAIVER = et(2025, 9, 10, 11)


def test_a_bench_replacement_means_no_waiver_is_needed():
    deadline, needs = fix_deadline(KICK_LATE, (KICK_EARLY,), WAIVER)
    assert needs is False


def test_deadline_is_the_earliest_point_options_start_disappearing():
    deadline, _ = fix_deadline(KICK_LATE, (KICK_EARLY,), WAIVER)
    assert deadline == KICK_EARLY


def test_no_replacement_and_no_kickoff_falls_to_waivers():
    deadline, needs = fix_deadline(None, (), WAIVER)
    assert deadline == WAIVER
    assert needs is True


def test_no_replacement_prefers_the_waiver_deadline_over_kickoff():
    """A claim is required, so the claim window is the real constraint."""
    deadline, needs = fix_deadline(KICK_LATE, (), WAIVER)
    assert deadline == WAIVER
    assert needs is True


def test_no_replacement_and_unknown_waivers_falls_back_to_kickoff():
    deadline, needs = fix_deadline(KICK_LATE, (), None)
    assert deadline == KICK_LATE
    assert needs is True


def test_nothing_known_yields_no_deadline_rather_than_a_guess():
    deadline, needs = fix_deadline(None, (), None)
    assert deadline is None
    assert needs is True


def test_the_starters_own_kickoff_can_be_the_binding_deadline():
    """His slot locks before the replacement plays."""
    deadline, _ = fix_deadline(KICK_EARLY, (KICK_LATE,), WAIVER)
    assert deadline == KICK_EARLY


# --- the lock is a ceiling on every deadline ---
#
# A claim that processes after the slot freezes cannot be started that week.
# Before this clamp a locked slot advertised a future waiver deadline, which
# reads as "you still have time" at exactly the moment you have none.

LATE_WAIVER = et(2025, 9, 16, 11)  # after both kickoffs above


def test_a_waiver_run_after_the_lock_cannot_be_the_deadline():
    deadline, needs = fix_deadline(KICK_EARLY, (), LATE_WAIVER)
    assert deadline == KICK_EARLY
    assert needs is True


def test_the_deadline_never_lands_after_the_lock():
    for waiver in (WAIVER, LATE_WAIVER):
        deadline, _ = fix_deadline(KICK_EARLY, (), waiver)
        assert deadline <= KICK_EARLY


def test_a_waiver_run_before_the_lock_still_governs():
    """The clamp must not swallow the case it was built around."""
    deadline, _ = fix_deadline(KICK_LATE, (), WAIVER)
    assert deadline == WAIVER
