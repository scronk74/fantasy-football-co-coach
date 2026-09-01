import datetime as dt

import pytest

from ffcoach.leagues.base import WaiverSettings
from ffcoach.model.deadlines import FixKind, next_waiver_deadline, plan_fix
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


# --- which fix is available, and by when ---

KICK_EARLY = et(2025, 9, 14, 13)
KICK_LATE = et(2025, 9, 15, 20, 15)
WAIVER = et(2025, 9, 10, 11)


def test_a_bench_replacement_means_no_waiver_is_needed():
    plan = plan_fix(KICK_LATE, (KICK_EARLY,), WAIVER)
    assert plan.kind is FixKind.BENCH_SWAP
    assert plan.needs_waiver is False


def test_deadline_is_the_earliest_point_options_start_disappearing():
    assert plan_fix(KICK_LATE, (KICK_EARLY,), WAIVER).deadline == KICK_EARLY


def test_no_replacement_and_no_lock_falls_to_waivers():
    plan = plan_fix(None, (), WAIVER)
    assert plan.kind is FixKind.WAIVER_CLAIM
    assert plan.deadline == WAIVER


def test_no_replacement_prefers_the_waiver_deadline_over_kickoff():
    """A claim is required, so the claim window is the real constraint."""
    plan = plan_fix(KICK_LATE, (), WAIVER)
    assert plan.kind is FixKind.WAIVER_CLAIM
    assert plan.deadline == WAIVER


def test_unknown_waiver_schedule_is_reported_as_unknown_not_as_a_claim():
    plan = plan_fix(KICK_LATE, (), None)
    assert plan.kind is FixKind.UNKNOWN
    assert plan.deadline == KICK_LATE


def test_nothing_known_yields_no_deadline_rather_than_a_guess():
    plan = plan_fix(None, (), None)
    assert plan.kind is FixKind.UNKNOWN
    assert plan.deadline is None


def test_the_starters_own_kickoff_can_be_the_binding_deadline():
    """His slot locks before the replacement plays."""
    assert plan_fix(KICK_EARLY, (KICK_LATE,), WAIVER).deadline == KICK_EARLY


# --- a claim that cannot land in time is not a claim ---
#
# The predecessor of this section clamped the deadline to `min(waiver, lock)`
# and kept saying a claim was the fix. That produced "claim someone by Thursday
# 8:15" for a claim that could not process until Friday: a plausible time
# attached to an impossible action. The kind, not the number, is what had to
# change.

LATE_WAIVER = et(2025, 9, 16, 11)  # after both kickoffs above


def test_a_waiver_run_after_the_lock_is_not_offered_as_a_claim():
    plan = plan_fix(KICK_EARLY, (), LATE_WAIVER)
    assert plan.kind is FixKind.ADD_BEFORE_LOCK
    assert plan.claim_lands_in_time is False
    assert plan.verb == "Add"


def test_the_deadline_never_lands_after_the_lock():
    for waiver in (WAIVER, LATE_WAIVER):
        assert plan_fix(KICK_EARLY, (), waiver).deadline <= KICK_EARLY


def test_a_waiver_run_before_the_lock_still_governs():
    """The narrowing must not swallow the case the module was built around."""
    plan = plan_fix(KICK_LATE, (), WAIVER)
    assert plan.kind is FixKind.WAIVER_CLAIM
    assert plan.deadline == WAIVER


def test_a_waiver_run_exactly_at_the_lock_is_too_late():
    """A claim processing as the lineup freezes did not make the lineup."""
    assert plan_fix(KICK_EARLY, (), KICK_EARLY).kind is FixKind.ADD_BEFORE_LOCK


def test_every_kind_carries_a_verb():
    """No card may leave the user to infer the transaction type from prose."""
    assert {plan.verb for plan in (
        plan_fix(KICK_LATE, (KICK_EARLY,), WAIVER),
        plan_fix(KICK_LATE, (), WAIVER),
        plan_fix(KICK_EARLY, (), LATE_WAIVER),
        plan_fix(KICK_LATE, (), None),
    )} == {"Swap", "Claim", "Add", "Review"}
