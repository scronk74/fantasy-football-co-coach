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


# --- `ffcoach check` (C7.2): the whole safety decision, offline ---

SWID = "{ABCDEF12-3456-7890-ABCD-EF1234567890}"


@pytest.fixture
def checkable(tmp_path):
    """A cache holding the NFL schedule, so `check` needs no network."""
    from ffcoach.cache import Cache
    from ffcoach.sources.schedule import _cache_key

    db = tmp_path / "c.sqlite3"
    cache = Cache(db)
    cache.set(_cache_key(2025), (FIXTURES / "nfl_schedule_2025.csv").read_text(), 3600)
    return db


def run_check(db, *extra):
    return main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(db),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T09:00-04:00",
        *extra,
    ])


def test_check_runs_end_to_end_with_no_cookies_and_no_network(checkable, capsys):
    """The point of C7: the safety decision is exercisable offline.

    Before this, `find_problems()` appeared exactly once under `src/` -- at its
    own definition. Nothing ran the detection this whole stage built.
    """
    code = run_check(checkable)
    out = capsys.readouterr().out
    assert code == 2  # actionable problems exist in the fixture roster
    assert "week 5 (from espn)" in out
    assert "to fix" in out


def test_check_reports_the_empty_slots_the_fixture_roster_has(checkable, capsys):
    code = run_check(checkable)
    out = capsys.readouterr().out
    assert code == 2
    assert "EMPTY" in out
    assert "no one in this slot" in out


def test_check_names_the_next_lock_and_the_waiver_deadline(checkable, capsys):
    run_check(checkable)
    out = capsys.readouterr().out
    assert "Next slot freezes:" in out
    assert "Waivers next process:" in out


def test_check_exits_nonzero_when_no_team_is_marked_as_yours(checkable, capsys):
    """Never falls back to teams[0] -- that reports a stranger's roster as yours."""
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--now", "2025-10-01T09:00-04:00",
    ])
    assert code == 1
    assert "no team" in capsys.readouterr().err


def test_check_refuses_a_naive_now_rather_than_assuming_utc(checkable, capsys):
    """Reading a naive instant as UTC shifts every deadline by hours."""
    code = run_check(checkable, )
    assert code == 2
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T09:00",
    ])
    assert code == 1
    assert "timezone" in capsys.readouterr().err


def test_check_refuses_an_unparseable_now(checkable, capsys):
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "next tuesday",
    ])
    assert code == 1
    assert "ISO-8601" in capsys.readouterr().err


def test_check_refuses_rather_than_reporting_undated_findings(tmp_path, capsys):
    """No usable schedule means no kickoffs, no byes and no deadlines.

    Every finding this tool makes is timed off one, so an answer without a
    schedule would read like a clean lineup rather than an unknown one.

    The cached body here is a well-formed CSV that is not a schedule -- the
    same shape as a captive portal or a truncated download, and the case that
    a status-code check alone would wave through.
    """
    from ffcoach.cache import Cache
    from ffcoach.sources.schedule import _cache_key

    db = tmp_path / "c.sqlite3"
    Cache(db).set(_cache_key(2025), "not,a,schedule\n1,2,3\n", 3600)

    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(db),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T09:00-04:00",
    ])
    assert code == 1
    assert "no NFL schedule" in capsys.readouterr().err


def test_a_check_after_every_kickoff_is_not_reported_as_actionable(checkable, capsys):
    """January. Nothing is fixable, and the exit code must not say otherwise."""
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2026-01-01T09:00-05:00",
    ])
    out = capsys.readouterr().out
    assert code != 2
    assert "LOCKED, too late" in out


# --- D1: delivery ---

NOTIFY_YAML = """
channel: ntfy
ntfy:
  topic: "a-long-unguessable-topic-name"
"""


def test_check_dry_run_prints_the_message_it_would_have_sent(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    out = capsys.readouterr().out
    assert code == 2
    assert "[interrupt]" in out
    assert "lineup fixes — week 5" in out


def test_a_dry_run_still_validates_the_channel_config(checkable, tmp_path, capsys):
    """A dry run that skips validation "succeeds" against a broken topic."""
    conf = tmp_path / "notify.yaml"
    conf.write_text("channel: ntfy\nntfy: {topic: ''}\n")
    code = run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    assert code == 1
    assert "topic is required" in capsys.readouterr().err


def test_notify_without_a_config_file_exits_nonzero(checkable, tmp_path, capsys):
    code = run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(tmp_path / "nope.yaml")
    )
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_a_run_with_nothing_to_send_says_so_rather_than_staying_quiet(
    checkable, tmp_path, capsys
):
    """"Nothing sent" and "failed to send" must never look alike."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2026-01-01T09:00-05:00",   # every kickoff is past
        "--notify", "--dry-run",
        "--notify-config", str(conf),
    ])
    out = capsys.readouterr().out
    assert code == 3
    assert "Nothing to send" in out


def test_notify_test_needs_the_flag(tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    assert main(["notify", "--notify-config", str(conf)]) == 1
    assert "notify --test" in capsys.readouterr().err


def test_a_guessable_topic_is_refused(checkable, tmp_path, capsys):
    """A public ntfy topic has no auth; `ffcoach` is not a secret."""
    conf = tmp_path / "notify.yaml"
    conf.write_text("channel: ntfy\nntfy: {topic: 'ffcoach'}\n")
    code = run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    assert code == 1
    assert "guessable" in capsys.readouterr().err
