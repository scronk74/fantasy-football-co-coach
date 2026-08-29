import datetime as dt
from pathlib import Path

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.leagues.espn import _PRO_TEAM_ABBREVIATIONS
from ffcoach.sources.schedule import (
    ScheduleUnavailable,
    _cache_key,
    fetch_schedule,
    normalize_team,
    parse_schedule,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nfl_schedule_2025.csv"


@pytest.fixture
def raw():
    return FIXTURE.read_text()


@pytest.fixture
def schedule(raw):
    return parse_schedule(raw, 2025)


def client_returning(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_loads_all_regular_season_teams(schedule):
    assert len(schedule.teams) == 32


def test_every_team_has_exactly_one_bye(schedule):
    missing = [t for t in schedule.teams if schedule.bye_week(t) is None]
    assert missing == []


def test_team_abbreviations_match_the_espn_spelling(schedule):
    """nflverse writes LA/WAS, ESPN writes LAR/WSH.

    Unhandled, Rams and Commanders starters would silently never match a
    schedule row and never alert on a bye.
    """
    espn_teams = {v for v in _PRO_TEAM_ABBREVIATIONS.values() if v != "FA"}
    assert schedule.teams == espn_teams


def test_normalize_team_maps_the_two_disagreements():
    assert normalize_team("LA") == "LAR"
    assert normalize_team("WAS") == "WSH"


def test_normalize_team_leaves_agreeing_codes_alone():
    for code in ("KC", "BAL", "SF", "NYJ"):
        assert normalize_team(code) == code


def test_normalize_team_is_case_insensitive():
    assert normalize_team("la") == "LAR"
    assert normalize_team(" kc ") == "KC"


def test_bye_week_accepts_the_espn_spelling(schedule):
    # The caller only ever has ESPN spellings; both must resolve.
    assert schedule.bye_week("LAR") is not None
    assert schedule.bye_week("WSH") is not None


def test_is_on_bye_is_true_only_in_the_bye_week(schedule):
    team = "KC"
    bye = schedule.bye_week(team)
    assert schedule.is_on_bye(team, bye) is True
    other = next(w for w in sorted(schedule.weeks) if w != bye)
    assert schedule.is_on_bye(team, other) is False


def test_is_on_bye_is_false_for_an_unknown_team(schedule):
    # Team defenses and free agents must not be reported as on bye.
    assert schedule.is_on_bye("FA", 5) is False
    assert schedule.is_on_bye("", 5) is False


def test_kickoff_is_timezone_aware(schedule):
    kick = schedule.kickoff("KC", 1)
    assert kick is not None
    assert kick.tzinfo is not None
    assert kick.utcoffset() is not None


def test_kickoff_returns_none_in_a_bye_week(schedule):
    team = "KC"
    assert schedule.kickoff(team, schedule.bye_week(team)) is None


def test_a_week_has_several_distinct_lock_windows(schedule):
    """The core reason alerts are timed per player rather than per week."""
    windows = schedule.lock_windows(8)
    assert len(windows) >= 4
    assert windows == sorted(windows)


def test_lock_windows_are_empty_for_an_unplayed_week(schedule):
    assert schedule.lock_windows(99) == []


def test_thursday_and_monday_games_are_separate_windows(schedule):
    windows = schedule.lock_windows(8)
    weekdays = {w.astimezone(windows[0].tzinfo).weekday() for w in windows}
    # Thursday=3, Sunday=6, Monday=0
    assert 3 in weekdays
    assert 0 in weekdays


def test_parse_ignores_other_seasons(raw):
    schedule = parse_schedule(raw, 2025)
    assert all(g.week <= 18 for g in schedule.games)


def test_parse_rejects_an_unknown_season(raw):
    with pytest.raises(ScheduleUnavailable, match="no regular-season games"):
        parse_schedule(raw, 1999)


def test_parse_rejects_a_file_without_the_expected_columns():
    with pytest.raises(ScheduleUnavailable, match="parse"):
        parse_schedule("alpha,beta\n1,2\n", 2025)


def test_each_game_produces_a_row_for_both_teams(schedule):
    week_one = [g for g in schedule.games if g.week == 1]
    # Every team plays at most once, and both sides are indexed.
    assert len(week_one) == len({g.team for g in week_one})


def test_opponent_is_the_other_team(schedule):
    game = next(g for g in schedule.games if g.week == 1)
    mirror = next(
        g for g in schedule.games if g.week == 1 and g.team == game.opponent
    )
    assert mirror.opponent == game.team
    assert mirror.kickoff == game.kickoff


def test_fetch_hits_network_once_then_serves_cache(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning(raw, calls=calls)
    a = fetch_schedule(2025, cache, client=client)
    b = fetch_schedule(2025, cache, client=client)
    assert a == b == raw
    assert len(calls) == 1


def test_fetch_falls_back_to_stale_cache_on_failure(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_schedule(2025, cache, client=client_returning(raw))
    cache.set(_cache_key(2025), raw, ttl_seconds=-1)
    got = fetch_schedule(2025, cache, client=client_returning("", status=500))
    assert got == raw


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(ScheduleUnavailable, match="500"):
        fetch_schedule(2025, cache, client=client_returning("", status=500))


def test_kickoff_times_are_plausible_nfl_slots(schedule):
    """Guards against a timezone or parse error shifting every game."""
    hours = {schedule.kickoff(g.team, g.week).hour for g in schedule.games[:200]}
    assert hours
    assert all(9 <= h <= 23 for h in hours), sorted(hours)


def test_known_kickoff_matches_the_source_row(schedule):
    # 2025_01_DAL_PHI: 2025-09-04 20:20 Eastern.
    kick = schedule.kickoff("PHI", 1)
    assert kick.date() == dt.date(2025, 9, 4)
    assert (kick.hour, kick.minute) == (20, 20)
