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
        rows(), cfg(), generated_at="2026-08-20T12:00:00Z", unmatched=["X"], stale_seconds=None
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
        "rank", "name", "position", "team", "adp", "stdev", "bye", "value",
        "verdict", "verdict_text", "availability", "availability_text",
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
        rows(), cfg(), generated_at="2026-08-20T12:00:00Z", unmatched=[], stale_seconds=7200.0
    )
    assert p["stale"] is True
    assert p["stale_seconds"] == 7200.0


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
    return league_payload(sample_league(), generated_at="2026-08-20T12:00:00Z", stale_seconds=None)


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
        }
    ]


def test_league_payload_never_contains_a_dollar_figure():
    assert "$" not in json.dumps(league_json_payload())


def test_league_payload_marks_stale_data_with_its_age():
    p = league_payload(sample_league(), generated_at="2026-08-20T12:00:00Z", stale_seconds=900.0)
    assert p["stale"] is True
    assert p["stale_seconds"] == 900.0


def test_write_board_also_writes_a_league_payload(tmp_path):
    target = tmp_path / "web" / "data" / "league.json"
    write_board(league_json_payload(), target)
    assert json.loads(target.read_text())["teams"][0]["name"] == "Dynasty"
