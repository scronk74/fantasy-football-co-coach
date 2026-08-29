import datetime as dt
from pathlib import Path

import pytest

from ffcoach.model.week import (
    MAX_WEEK,
    WeekUnavailable,
    derive_week,
    resolve_week,
)
from ffcoach.sources.schedule import parse_schedule

SCHEDULE = Path(__file__).parent / "fixtures" / "nfl_schedule_2025.csv"


@pytest.fixture(scope="module")
def schedule():
    return parse_schedule(SCHEDULE.read_text(), 2025)


BEFORE_SEASON = dt.datetime(2025, 8, 1, tzinfo=dt.UTC)
AFTER_SEASON = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)


# --- ESPN is preferred ---


def test_espn_week_is_used_when_valid(schedule):
    got = resolve_week(7, schedule, BEFORE_SEASON)
    assert got.week == 7
    assert got.source == "espn"
    assert got.is_derived is False


def test_espn_week_wins_even_when_derivation_disagrees(schedule):
    """ESPN is authoritative; the league's own number is the one that matters."""
    got = resolve_week(12, schedule, BEFORE_SEASON)
    assert got.week == 12
    assert got.source == "espn"


# --- fallback ---


def test_falls_back_to_derivation_when_espn_is_missing(schedule):
    got = resolve_week(None, schedule, BEFORE_SEASON)
    assert got.week == 1
    assert got.source == "derived"
    assert got.is_derived is True


def test_the_fallback_says_so(schedule):
    """A derived week must never be presented as fact."""
    got = resolve_week(None, schedule, BEFORE_SEASON)
    assert "derived" in got.note
    assert "ESPN" in got.note


def test_espn_source_note_names_espn(schedule):
    assert "ESPN" in resolve_week(3, schedule, BEFORE_SEASON).note


# --- derivation behavior ---


def test_derives_week_one_before_the_season(schedule):
    assert derive_week(schedule, BEFORE_SEASON) == 1


def test_derivation_returns_none_after_the_season(schedule):
    assert derive_week(schedule, AFTER_SEASON) is None


def test_current_week_holds_while_its_games_are_being_played(schedule):
    """Mid-window, the week in progress is still current."""
    windows = schedule.lock_windows(5)
    during = windows[0] + dt.timedelta(hours=1)
    assert derive_week(schedule, during) == 5


def test_week_rolls_over_once_its_last_game_ends(schedule):
    last = max(schedule.lock_windows(5))
    after = last + dt.timedelta(hours=5)
    assert derive_week(schedule, after) == 6


def test_week_has_not_rolled_over_during_the_final_game(schedule):
    last = max(schedule.lock_windows(5))
    mid_game = last + dt.timedelta(hours=1)
    assert derive_week(schedule, mid_game) == 5


# --- guards: an error, never a default ---


@pytest.mark.parametrize("bad", [0, -1, 99, MAX_WEEK + 1])
def test_out_of_range_espn_weeks_are_rejected(schedule, bad):
    """A bogus week must not be trusted just because ESPN sent it."""
    got = resolve_week(bad, schedule, BEFORE_SEASON)
    assert got.source == "derived"


def test_raises_when_no_week_can_be_established(schedule):
    with pytest.raises(WeekUnavailable, match="could not establish"):
        resolve_week(None, schedule, AFTER_SEASON)


def test_the_error_explains_why_guessing_is_refused(schedule):
    with pytest.raises(WeekUnavailable) as exc:
        resolve_week(None, schedule, AFTER_SEASON)
    assert "guess" in str(exc.value).lower()


def test_never_silently_defaults_to_week_one(schedule):
    """The dangerous failure: quietly evaluating a week nobody is playing."""
    with pytest.raises(WeekUnavailable):
        resolve_week(0, schedule, AFTER_SEASON)
