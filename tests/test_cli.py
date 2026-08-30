import json
from pathlib import Path

import pytest

from ffcoach.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
LEAGUE = """
name: Test League
season: 2026
teams: 12
scoring: ppr
my_pick: 7
roster: {QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DEF: 1, BN: 6}
"""


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "league.yaml").write_text(LEAGUE)
    cache_db = tmp_path / "c.sqlite3"

    from ffcoach.cache import Cache
    from ffcoach.sources.ffcalc import _cache_key
    from ffcoach.sources.sleeper import CACHE_KEY

    cache = Cache(cache_db)
    cache.set(_cache_key("ppr", 12, 2026), (FIXTURES / "ffc_ppr_12.json").read_text(), 3600)
    cache.set(CACHE_KEY, (FIXTURES / "sleeper_players.json").read_text(), 3600)
    return tmp_path


def test_build_writes_the_board(workspace):
    out = workspace / "web" / "data" / "board.json"
    code = main([
        "build",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["players"]
    assert payload["league"]["next_pick"] == 18


def test_build_ranks_players_from_one(workspace):
    out = workspace / "board.json"
    main([
        "build",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
        "--out", str(out),
    ])
    ranks = [r["rank"] for r in json.loads(out.read_text())["players"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_missing_config_exits_nonzero_with_a_clear_message(tmp_path, capsys):
    code = main([
        "build",
        "--config", str(tmp_path / "absent.yaml"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "b.json"),
    ])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_doctor_reports_config_and_cache(workspace, capsys):
    code = main([
        "doctor",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "Test League" in out
    assert "ppr" in out


def test_unknown_command_exits_nonzero(capsys):
    with pytest.raises(SystemExit):
        main(["nonsense"])


def test_league_writes_teams_from_fixture(tmp_path):
    out = tmp_path / "web" / "data" / "league.json"
    code = main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert len(payload["teams"]) == 2


def test_league_fixture_mode_needs_no_espn_config(tmp_path):
    # No espn.yaml exists at all in this tmp_path -- fixture mode must not
    # require one.
    out = tmp_path / "league.json"
    code = main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
        "--espn-config", str(tmp_path / "does-not-exist.yaml"),
    ])
    assert code == 0


def test_league_missing_espn_config_exits_nonzero_without_fixture(tmp_path):
    code = main([
        "league",
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "league.json"),
        "--espn-config", str(tmp_path / "absent-espn.yaml"),
    ])
    assert code == 1


def test_league_takes_the_week_from_espn(tmp_path):
    """The fixture carries scoringPeriodId=5.

    ESPN's number short-circuits before any schedule fetch, so this needs no
    network and no cached schedule.
    """
    out = tmp_path / "league.json"
    code = main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
        "--season", "2025",
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["week"] == 5
    assert payload["week_source"] == "espn"


def test_league_payload_carries_roster_slots(tmp_path):
    """Needed by the empty-slot check; must survive to the browser."""
    out = tmp_path / "league.json"
    main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
        "--season", "2025",
    ])
    slots = json.loads(out.read_text())["league"]["roster_slots"]
    assert slots["RB"] == 2
    assert slots["FLEX"] == 1


def test_league_refuses_rather_than_guessing_the_week(tmp_path):
    """No week from ESPN and no schedule available: exit nonzero, never default."""
    stripped = json.loads((FIXTURES / "espn_league.json").read_text())
    stripped.pop("scoringPeriodId", None)
    stripped.get("status", {}).pop("currentMatchupPeriod", None)
    fixture = tmp_path / "no_week.json"
    fixture.write_text(json.dumps(stripped))

    cache_db = tmp_path / "c.sqlite3"
    from ffcoach.cache import Cache
    from ffcoach.sources.schedule import _cache_key
    # Seed an empty schedule so nothing reaches the network.
    Cache(cache_db).set(_cache_key(2025), "game_id,season,game_type,week,gameday\n", 3600)

    code = main([
        "league",
        "--fixture", str(fixture),
        "--cache", str(cache_db),
        "--out", str(tmp_path / "league.json"),
        "--season", "2025",
    ])
    assert code == 1


def test_league_missing_fixture_file_exits_nonzero(tmp_path):
    code = main([
        "league",
        "--fixture", str(tmp_path / "nope.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "league.json"),
    ])
    assert code == 1
