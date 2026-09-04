import json

from ffcoach.advisors.draft import build_board
from ffcoach.config import LeagueConfig
from ffcoach.leagues.base import League, RosterEntry, Team
from ffcoach.model.players import Player
from ffcoach.report.build import SCHEMA_VERSION, board_payload, league_payload, write_board


def cfg():
    return LeagueConfig(
        name="T",
        season=2026,
        teams=12,
        scoring="ppr",
        my_pick=7,
        roster={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 6},
    )


def rows():
    players = [
        Player("A", "RB", "ATL", 1.0, 1.0, 11, 10, None, "1"),
        Player("B", "WR", "CIN", 20.0, 4.0, 6, 10, "Questionable", "2"),
    ]
    return build_board(players, cfg())


def payload():
    return board_payload(
        rows(), cfg(), generated_at="2026-08-20T12:00:00Z", unmatched=["X"]
    )


def test_payload_declares_schema_version():
    assert payload()["schema_version"] == SCHEMA_VERSION


def test_payload_includes_league_context_the_page_needs():
    league = payload()["league"]
    assert league["teams"] == 12
    assert league["scoring"] == "ppr"
    assert league["my_pick"] == 7
    assert league["next_pick"] == 18


def test_payload_never_contains_a_dollar_figure():
    assert "$" not in json.dumps(payload())


def test_every_row_has_the_documented_keys():
    expected = {
        "rank", "name", "position", "team", "adp", "stdev", "bye",
        "availability", "availability_text",
        "tier", "tier_break_after", "injury_status", "reason",
    }
    for row in payload()["players"]:
        assert set(row) == expected


def test_payload_reports_unmatched_players():
    assert payload()["unmatched"] == ["X"]


def test_payload_marks_fresh_data_as_not_stale():
    assert payload()["stale"] is False


def test_payload_marks_stale_data_with_its_age():
    p = board_payload(
        rows(), cfg(), generated_at="2026-08-20T12:00:00Z", unmatched=[], age_seconds=7200.0, stale=True
    )
    assert p["stale"] is True
    assert p["age_seconds"] == 7200.0


def test_write_board_creates_parent_directories(tmp_path):
    target = tmp_path / "web" / "data" / "board.json"
    write_board(payload(), target)
    assert json.loads(target.read_text())["schema_version"] == SCHEMA_VERSION


def sample_league():
    entry = RosterEntry(player_name="A Player", position="RB", nfl_team="ATL", lineup_slot="RB")
    team = Team(
        team_id="1",
        name="Dynasty",
        owner="Steve",
        wins=5,
        losses=3,
        ties=0,
        points_for=650.4,
        points_against=601.2,
        roster=(entry,),
        is_user_team=True,
    )
    return League(name="The League", season=2026, teams=(team,))


def league_json_payload():
    return league_payload(sample_league(), generated_at="2026-08-20T12:00:00Z")


def test_league_payload_declares_schema_version():
    assert league_json_payload()["schema_version"] == SCHEMA_VERSION


def test_league_payload_includes_league_context():
    league = league_json_payload()["league"]
    assert league["name"] == "The League"
    assert league["season"] == 2026


def test_league_payload_includes_team_fields():
    team = league_json_payload()["teams"][0]
    assert team["name"] == "Dynasty"
    assert team["owner"] == "Steve"
    assert team["record"] == "5-3"
    assert team["is_user_team"] is True


def test_league_payload_includes_roster_entries():
    roster = league_json_payload()["teams"][0]["roster"]
    assert roster == [
        {
            "player_name": "A Player",
            "position": "RB",
            "nfl_team": "ATL",
            "lineup_slot": "RB",
            "is_starter": True,
            "injury_status": None,
        }
    ]


def test_league_payload_never_contains_a_dollar_figure():
    assert "$" not in json.dumps(league_json_payload())


def test_league_payload_marks_stale_data_with_its_age():
    p = league_payload(sample_league(), generated_at="2026-08-20T12:00:00Z", age_seconds=900.0, stale=True)
    assert p["stale"] is True
    assert p["age_seconds"] == 900.0


def test_write_board_also_writes_a_league_payload(tmp_path):
    target = tmp_path / "web" / "data" / "league.json"
    write_board(league_json_payload(), target)
    assert json.loads(target.read_text())["teams"][0]["name"] == "Dynasty"


# --- F1: the payload the Week page reads ---


def check_result(**over):
    import datetime as dt

    from ffcoach.advisors.lineup import LineupFinding
    from ffcoach.check import CheckResult, SourceHealth
    from ffcoach.model.deadlines import FixKind, FixPlan

    sunday = dt.datetime(2025, 10, 5, 17, 0, tzinfo=dt.UTC)
    finding = LineupFinding(
        kind="out", player_name="Hurt Guy", position="WR", lineup_slot="WR",
        nfl_team="KC", reason="listed OUT", replacements=("Bench Guy",),
        kickoff=sunday, locked=False, fix=FixPlan(FixKind.BENCH_SWAP, sunday),
        locks_at=sunday,
    )
    base = dict(
        week=5, week_source="espn", team_name="Team 11",
        findings=[finding], actionable=[finding],
        sources=(SourceHealth("ESPN league", 0.0, False),),
        next_lock=sunday, waiver_deadline=sunday,
    )
    base.update(over)
    return CheckResult(**base)


def payload_for(**over):
    from ffcoach.report.build import check_payload

    return check_payload(
        check_result(**over), league_name="L",
        generated_at="2025-10-01T09:00:00+00:00", timezone="America/New_York",
    )


def test_the_check_payload_carries_the_status_not_just_the_findings():
    """The page cannot tell "nothing wrong" from "we could not see everything"
    out of an empty list alone -- that is D-054's whole point."""
    p = payload_for(findings=[], actionable=[], blind_spots=("x",))
    assert p["status"] == "unverified"
    assert p["all_clear"] is False
    assert p["blind_spots"] == ["x"]


def test_each_finding_carries_its_verb_rather_than_only_its_kind():
    """D-046: "Claim" and "Swap" are different instructions, and a time alone
    cannot express the difference."""
    assert payload_for()["findings"][0]["verb"] == "Swap"


def test_actionability_is_decided_in_python_not_in_the_browser():
    """Comparing a deadline to "now" in JavaScript answers a slightly different
    question on every reload."""
    p = payload_for()
    assert p["findings"][0]["actionable"] is True


def test_the_payload_names_the_timezone_its_times_are_in():
    """Every timestamp carries an offset, but the page renders in the league's
    zone, not the browser's -- see D-065."""
    assert payload_for()["timezone"] == "America/New_York"


def test_the_check_payload_never_contains_a_dollar_figure():
    assert "$" not in json.dumps(payload_for())


def test_the_check_payload_is_json_serialisable():
    """It is written straight to disk; a datetime would blow up at write time."""
    json.dumps(payload_for())
