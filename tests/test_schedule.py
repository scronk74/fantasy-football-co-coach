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
    a = fetch_schedule(2025, cache, client=client).text
    b = fetch_schedule(2025, cache, client=client).text
    assert a == b == raw
    assert len(calls) == 1


def test_fetch_falls_back_to_stale_cache_on_failure(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_schedule(2025, cache, client=client_returning(raw))
    cache.set(_cache_key(2025), raw, ttl_seconds=-1)
    got = fetch_schedule(2025, cache, client=client_returning("", status=500)).text
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


# --- a missing kickoff time is not a bye ---
#
# Rows without a `gametime` were dropped at parse, after which "this team has
# no row this week" meant bye. A Week 2 game whose time was still TBD made both
# teams read as on bye -- a data-quality gap reported as the most certain fact
# this product emits, at interrupt priority.

HEADER = "game_id,season,game_type,week,gameday,gametime,away_team,home_team\n"


def three_weeks(week_two_time: str) -> str:
    """KC/DEN play all three weeks; week 2's kickoff time is the variable.

    BUF/NYJ play weeks 1 and 3 only, so week 2 is their single bye and the
    season has three known weeks even when KC's week-2 row is degraded.
    """
    rows = [
        f"g{w},2025,REG,{w},2025-09-0{w},{t},DEN,KC\n"
        for w, t in ((1, "13:00"), (2, week_two_time), (3, "16:25"))
    ]
    rows += [f"b{w},2025,REG,{w},2025-09-0{w},13:00,NYJ,BUF\n" for w in (1, 3)]
    return HEADER + "".join(rows)


def test_a_game_with_no_listed_time_is_still_a_game():
    sched = parse_schedule(three_weeks(""), 2025)
    assert sched.status("KC", 2) == "playing"
    assert sched.is_on_bye("KC", 2) is False


def test_a_game_with_no_listed_time_reports_its_kickoff_as_unknown():
    sched = parse_schedule(three_weeks(""), 2025)
    assert sched.kickoff_known("KC", 2) is False
    assert sched.kickoff("KC", 2) is None


def test_a_week_with_no_row_at_all_is_still_a_bye():
    """The narrowing must not cost us the finding the product is built on."""
    sched = parse_schedule(three_weeks("13:00"), 2025)
    assert sched.status("BUF", 2) == "bye"
    assert sched.bye_week("BUF") == 2


def test_a_team_the_schedule_never_mentions_is_unknown_not_on_bye():
    """An ESPN abbreviation we failed to normalize must not become a bye."""
    sched = parse_schedule(three_weeks("13:00"), 2025)
    assert sched.status("SEA", 2) == "unknown"
    assert sched.is_on_bye("SEA", 2) is False


def test_an_unpublished_kickoff_contributes_no_lock_window():
    """A blank cell must not become a deadline."""
    sched = parse_schedule(three_weeks(""), 2025)
    assert sched.lock_windows(2) == []


def test_a_row_missing_a_team_is_dropped_not_kept_as_half_a_game():
    raw = HEADER + "g1,2025,REG,1,2025-09-01,13:00,,KC\ng2,2025,REG,2,2025-09-02,13:00,DEN,KC\n"
    sched = parse_schedule(raw, 2025)
    assert ("KC", 1) not in sched._by_team_week
    assert sched.status("KC", 2) == "playing"


def test_several_missing_weeks_read_as_unknown_rather_than_several_byes():
    """A truncated feed is not a bye, and only one missing week can be one.

    Without this, a download cut short after Week 3 turns every remaining week
    into a bye -- interrupt-priority alerts manufactured out of a broken
    transfer.
    """
    raw = HEADER + "".join(
        f"g{w},2025,REG,{w},2025-09-0{w},13:00,DEN,KC\n" for w in (1, 2)
    ) + "".join(f"b{w},2025,REG,{w},2025-09-0{w},13:00,NYJ,BUF\n" for w in (1, 2, 3, 4))
    sched = parse_schedule(raw, 2025)
    assert sched.status("KC", 3) == "unknown"
    assert sched.status("KC", 4) == "unknown"
    assert sched.bye_week("KC") is None


def test_a_non_numeric_week_is_dropped_rather_than_crashing():
    raw = HEADER + "g1,2025,REG,soon,2025-09-01,13:00,DEN,KC\ng2,2025,REG,2,2025-09-02,13:00,DEN,KC\n"
    assert parse_schedule(raw, 2025).weeks == {2}


def test_the_real_fixture_still_has_every_game_timed(schedule):
    """If nflverse starts shipping blanks, this is where we find out."""
    untimed = [g for g in schedule.games if g.kickoff is None]
    assert untimed == []
