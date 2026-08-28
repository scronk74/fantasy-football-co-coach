from pathlib import Path

import pytest

from ffcoach.leagues.espn_client import EspnUnavailable
from ffcoach.leagues.espn import parse_league

FIXTURE = Path(__file__).parent / "fixtures" / "espn_league.json"
MY_SWID = "{ABCDEF12-3456-7890-ABCD-EF1234567890}"


@pytest.fixture
def raw():
    return FIXTURE.read_text()


def test_parse_returns_league_name_and_season(raw):
    league = parse_league(raw)
    assert league.name == "The League"
    assert league.season == 2026


def test_parse_returns_all_teams(raw):
    league = parse_league(raw)
    assert len(league.teams) == 2
    assert {t.name for t in league.teams} == {"Dynasty", "Disasters"}


def test_parse_computes_record_fields(raw):
    league = parse_league(raw)
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    assert dynasty.wins == 5
    assert dynasty.losses == 3
    assert dynasty.ties == 0
    assert dynasty.points_for == 650.4
    assert dynasty.points_against == 601.2
    assert dynasty.record == "5-3"


def test_parse_identifies_user_team_by_swid(raw):
    league = parse_league(raw, my_swid=MY_SWID)
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    disasters = next(t for t in league.teams if t.name == "Disasters")
    assert dynasty.is_user_team is True
    assert disasters.is_user_team is False


def test_parse_matches_swid_case_and_brace_insensitively(raw):
    # Same GUID, no braces, different case -- should still match.
    league = parse_league(raw, my_swid="abcdef12-3456-7890-abcd-ef1234567890")
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    assert dynasty.is_user_team is True


def test_parse_leaves_teams_unowned_when_no_swid_given(raw):
    league = parse_league(raw)
    assert all(t.is_user_team is False for t in league.teams)


def test_parse_resolves_owner_display_name_from_members(raw):
    league = parse_league(raw)
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    assert dynasty.owner == "Steve"


def test_parse_maps_qb_rb_wr_and_def_positions(raw):
    league = parse_league(raw)
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    by_name = {e.player_name: e for e in dynasty.roster}
    assert by_name["Patrick Mahomes"].position == "QB"
    assert by_name["Bijan Robinson"].position == "RB"
    assert by_name["Amon-Ra St. Brown"].position == "WR"
    assert by_name["Ravens"].position == "DEF"


def test_parse_maps_lineup_slots_including_flex_bench_and_ir(raw):
    league = parse_league(raw)
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    by_name = {e.player_name: e for e in dynasty.roster}
    assert by_name["Amon-Ra St. Brown"].lineup_slot == "FLEX"
    assert by_name["Bench Guy"].lineup_slot == "BN"
    assert by_name["Hurt Guy"].lineup_slot == "IR"
    assert by_name["Bench Guy"].is_starter is False
    assert by_name["Patrick Mahomes"].is_starter is True


def test_parse_maps_pro_team_ids_to_abbreviations(raw):
    league = parse_league(raw)
    dynasty = next(t for t in league.teams if t.name == "Dynasty")
    by_name = {e.player_name: e for e in dynasty.roster}
    assert by_name["Ravens"].nfl_team == "BAL"
    assert by_name["Patrick Mahomes"].nfl_team == "KC"


def test_parse_handles_an_empty_roster(raw):
    league = parse_league(raw)
    disasters = next(t for t in league.teams if t.name == "Disasters")
    assert disasters.roster == ()


def test_parse_rejects_malformed_json():
    with pytest.raises(EspnUnavailable, match="parse"):
        parse_league("<html>nope</html>")


def test_parse_defaults_owner_to_unknown_when_owners_list_is_empty():
    league = parse_league('{"seasonId": 2026, "settings": {}, "teams": [{"id": 1, "owners": []}]}')
    assert league.teams[0].owner == "Unknown"
