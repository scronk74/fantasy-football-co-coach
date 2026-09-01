from pathlib import Path

import pytest

from ffcoach.leagues.base import LockMode
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


def test_parse_reads_lineup_slot_counts(raw):
    league = parse_league(raw)
    assert league.roster_slots["QB"] == 1
    assert league.roster_slots["RB"] == 2
    assert league.roster_slots["FLEX"] == 1


def test_parse_drops_slots_the_league_does_not_use(raw):
    """ESPN lists every slot in the game, most with a count of zero."""
    league = parse_league(raw)
    assert all(count > 0 for count in league.roster_slots.values())


def test_starting_slots_exclude_bench_and_ir(raw):
    league = parse_league(raw)
    assert "BN" in league.roster_slots
    assert "BN" not in league.starting_slots
    assert "IR" not in league.starting_slots


def test_parse_takes_the_week_from_espn(raw):
    league = parse_league(raw)
    assert league.current_week == 5


def test_current_week_is_none_when_espn_omits_it():
    league = parse_league('{"seasonId": 2026, "settings": {}, "teams": []}')
    assert league.current_week is None


def test_roster_slots_are_empty_when_settings_are_absent():
    """No settings means the empty-slot check is skipped, never guessed."""
    league = parse_league('{"seasonId": 2026, "settings": {}, "teams": []}')
    assert league.roster_slots == {}


def test_parse_reads_waiver_settings(raw):
    w = parse_league(raw).waivers
    assert w.is_known
    assert "WEDNESDAY" in w.process_days
    assert w.process_hour == 11


def test_waiver_budget_flag_is_read(raw):
    """Spec UX rule 5: no dollar figure unless the league actually uses one."""
    assert parse_league(raw).waivers.uses_budget is False


def test_waivers_are_unknown_rather_than_assumed_when_absent():
    w = parse_league('{"seasonId": 2026, "settings": {}, "teams": []}').waivers
    assert w.is_known is False
    assert w.process_days == ()


def test_parse_reads_the_per_player_lock_verified_live(raw):
    """`INDIVIDUAL_GAME` is the one value confirmed against a real league."""
    lock = parse_league(raw).lineup_lock
    assert lock.mode is LockMode.PER_PLAYER
    assert lock.is_weekly is False
    assert lock.assumed is False
    assert lock.note is None  # read and understood: nothing to log


def test_absent_lock_setting_defaults_to_per_player_and_says_so():
    lock = parse_league('{"seasonId": 2026, "settings": {}, "teams": []}').lineup_lock
    assert lock.mode is LockMode.PER_PLAYER
    assert lock.assumed is True
    assert "assuming" in lock.note


def test_an_unfamiliar_lock_value_is_read_as_weekly():
    """ESPN offers two lock rules. Not the default one means the other.

    This is what makes the setting knowable without ever having seen a
    weekly-lock league: only the default's spelling had to be verified.
    """
    raw = (
        '{"seasonId": 2026, "teams": [], "settings": {"rosterSettings":'
        ' {"lineupLocktimeType": "FIRST_GAME_OF_WEEK"}}}'
    )
    lock = parse_league(raw).lineup_lock
    assert lock.is_weekly is True
    assert lock.unrecognized is True
    assert lock.raw == "FIRST_GAME_OF_WEEK"
    assert "fails safe" in lock.note


def test_unfamiliar_lock_value_fails_toward_the_earlier_deadline():
    """Guessing weekly alerts too early; guessing per-player alerts too late."""
    raw = '{"seasonId": 2026, "teams": [], "settings": {"rosterSettings": {"lineupLocktimeType": "SOMETHING_NEW"}}}'
    assert parse_league(raw).lineup_lock.mode is LockMode.WEEKLY


def test_parse_rejects_malformed_json():
    with pytest.raises(EspnUnavailable, match="parse"):
        parse_league("<html>nope</html>")


def test_parse_defaults_owner_to_unknown_when_owners_list_is_empty():
    league = parse_league('{"seasonId": 2026, "settings": {}, "teams": [{"id": 1, "owners": []}]}')
    assert league.teams[0].owner == "Unknown"


# --- valid JSON of the wrong shape ---
#
# Only syntax errors used to become EspnUnavailable. Anything else escaped as a
# bare AttributeError or ValueError -- a stack trace no caller could catch, so
# no stale fallback could run and the CLI's friendly error never printed. Each
# case below was confirmed reachable before the guards existed.

import json


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda p: [], "top-level list"),
        (lambda p: {**p, "settings": []}, "settings as a list"),
        (lambda p: {**p, "teams": {}}, "teams as an object"),
        (lambda p: {**p, "members": "nope"}, "members as a string"),
        (lambda p: {**p, "seasonId": "twenty-six"}, "non-numeric season"),
    ],
)
def test_wrong_shapes_raise_the_modules_own_exception(raw, mutate, why):
    payload = json.dumps(mutate(json.loads(raw)))
    with pytest.raises(EspnUnavailable):
        parse_league(payload)


def test_a_non_numeric_record_raises_rather_than_escaping_as_valueerror(raw):
    payload = json.loads(raw)
    payload["teams"][0]["record"]["overall"]["wins"] = "oops"
    with pytest.raises(EspnUnavailable):
        parse_league(json.dumps(payload))


def test_a_missing_settings_block_is_tolerated_not_fatal(raw):
    """Absent is different from malformed: we lose settings, not the league."""
    payload = json.loads(raw)
    del payload["settings"]
    league = parse_league(json.dumps(payload))
    assert league.teams
    assert league.roster_slots == {}


# --- an unrecognized id must never become a plausible default ---


def first_entry(payload):
    return payload["teams"][0]["roster"]["entries"][0]


def test_an_unknown_lineup_slot_is_not_silently_benched(raw):
    """The dangerous default. A renamed slot id used to become "BN", so a real
    starter was skipped by every check and the run looked clean."""
    payload = json.loads(raw)
    first_entry(payload)["lineupSlotId"] = 9999
    league = parse_league(json.dumps(payload))
    entry = league.teams[0].roster[0]
    assert entry.lineup_slot == "UNKNOWN"
    assert entry.is_starter is True, "an unknown slot must still be evaluated"


def test_an_unknown_lineup_slot_produces_a_diagnostic(raw):
    payload = json.loads(raw)
    first_entry(payload)["lineupSlotId"] = 9999
    notes = parse_league(json.dumps(payload)).diagnostics
    assert any("lineupSlotId" in n and "9999" in n for n in notes)


def test_an_unknown_pro_team_is_not_silently_a_free_agent(raw):
    """"FA" matches no schedule row, so the player looked like someone with
    nothing to worry about."""
    payload = json.loads(raw)
    first_entry(payload)["playerPoolEntry"]["player"]["proTeamId"] = 4242
    league = parse_league(json.dumps(payload))
    assert league.teams[0].roster[0].nfl_team == "UNKNOWN"
    assert any("proTeamId" in n for n in league.diagnostics)


def test_a_real_free_agent_is_still_read_as_FA(raw):
    """proTeamId 0 genuinely means free agent; only unknown ids change."""
    payload = json.loads(raw)
    first_entry(payload)["playerPoolEntry"]["player"]["proTeamId"] = 0
    assert parse_league(json.dumps(payload)).teams[0].roster[0].nfl_team == "FA"


def test_a_clean_fixture_produces_no_diagnostics(raw):
    assert parse_league(raw).diagnostics == ()


# --- waiver settings we cannot use are discarded, not clamped ---


def set_waiver_hour(payload, hour):
    payload.setdefault("settings", {}).setdefault("acquisitionSettings", {})[
        "waiverProcessHour"
    ] = hour
    return payload


def test_an_out_of_range_waiver_hour_makes_the_schedule_unknown(raw):
    """Hour 25 used to parse and then blow up building a datetime much later.

    Clamping to 23 would be worse: a confident deadline derived from a value
    known to be wrong.
    """
    league = parse_league(json.dumps(set_waiver_hour(json.loads(raw), 25)))
    assert league.waivers.is_known is False
    assert any("waiverProcessHour" in n for n in league.diagnostics)


def test_a_non_numeric_waiver_hour_makes_the_schedule_unknown(raw):
    league = parse_league(json.dumps(set_waiver_hour(json.loads(raw), "noon")))
    assert league.waivers.is_known is False


def test_a_valid_waiver_hour_still_reads_normally(raw):
    league = parse_league(json.dumps(set_waiver_hour(json.loads(raw), 11)))
    assert league.waivers.process_hour == 11
