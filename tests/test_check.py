"""C7: the composition step. Everything below C7 was tested and unreachable.

`find_problems()` appeared exactly once under `src/` -- at its own definition.
These tests exist to make the whole safety decision runnable offline, which is
the only way it can be trusted before it is wired to anything that pushes.
"""

import datetime as dt
from pathlib import Path

import pytest

from ffcoach.check import CheckError, SourceHealth, build_check
from ffcoach.leagues.base import League, LineupLock, RosterEntry, Team
from ffcoach.model.week import WeekResolution
from ffcoach.sources.schedule import parse_schedule

SCHEDULE = Path(__file__).parent / "fixtures" / "nfl_schedule_2025.csv"

# The league processes waivers six days a week at 11:00 -- read from ESPN, not
# assumed. Real settings, so the deadlines these tests assert are real ones.
WAIVERS = ("MONDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


@pytest.fixture(scope="module")
def schedule():
    return parse_schedule(SCHEDULE.read_text(), 2025)


@pytest.fixture(scope="module")
def week(schedule):
    """A week with at least one bye team in which KC and BUF both play."""
    for candidate in sorted(schedule.weeks):
        if not any(schedule.bye_week(t) == candidate for t in schedule.teams):
            continue
        if schedule.is_on_bye("KC", candidate) or schedule.is_on_bye("BUF", candidate):
            continue
        return candidate
    raise AssertionError("no suitable week in fixture")


def entry(name, position="WR", team="KC", slot=None, injury=None):
    return RosterEntry(
        player_name=name,
        position=position,
        nfl_team=team,
        lineup_slot=slot if slot is not None else position,
        injury_status=injury,
    )


def team(name="Mine", mine=True, *entries):
    return Team(
        team_id=name,
        name=name,
        owner="Steve",
        wins=0,
        losses=0,
        ties=0,
        points_for=0.0,
        points_against=0.0,
        roster=tuple(entries),
        is_user_team=mine,
    )


def league(*teams, slots=None, waivers=WAIVERS, diagnostics=()):
    from ffcoach.leagues.base import WaiverSettings

    return League(
        name="L",
        season=2025,
        teams=tuple(teams),
        roster_slots=slots if slots is not None else {"WR": 1, "BN": 4},
        waivers=WaiverSettings(process_days=waivers, process_hour=11),
        lineup_lock=LineupLock(),
        diagnostics=tuple(diagnostics),
    )


def espn_week(w):
    return WeekResolution(week=w, source="espn")


EARLY = dt.datetime(2025, 9, 1, 9, 0, tzinfo=dt.UTC)
LIVE = (SourceHealth("ESPN league", 0.0, False), SourceHealth("NFL schedule", 0.0, False))


# --- C7.3: exactly one user team, or an explicit error ---


def test_the_check_runs_against_the_one_team_marked_as_yours(schedule, week):
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    theirs = team("Theirs", False, entry("Someone Else", "WR", "KC"))
    result = build_check(league(theirs, mine), schedule, espn_week(week), EARLY, LIVE)
    assert result.team_name == "Mine"


def test_no_team_marked_as_yours_is_an_error_not_a_default(schedule, week):
    """Picking one would check a stranger's roster and report it as yours.

    This is the SWID going stale or a cookie belonging to another account --
    both real, both silent if the check quietly takes teams[0].
    """
    theirs = team("Theirs", False, entry("Someone", "WR", "KC"))
    with pytest.raises(CheckError, match="no team"):
        build_check(league(theirs), schedule, espn_week(week), EARLY, LIVE)


def test_several_teams_marked_as_yours_is_an_error(schedule, week):
    a = team("A", True, entry("One", "WR", "KC"))
    b = team("B", True, entry("Two", "WR", "KC"))
    with pytest.raises(CheckError, match="2 teams"):
        build_check(league(a, b), schedule, espn_week(week), EARLY, LIVE)


# --- C7.4: an all-clear is stated, never implied by silence ---


def test_a_clean_week_says_so_explicitly(schedule, week):
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    result = build_check(league(mine), schedule, espn_week(week), EARLY, LIVE)
    assert result.findings == []
    assert result.status == "all_clear"
    assert result.all_clear is True


def test_a_problem_week_reports_findings(schedule, week):
    hurt = entry("Hurt Guy", "WR", "KC", injury="OUT")
    mine = team("Mine", True, hurt)
    result = build_check(league(mine), schedule, espn_week(week), EARLY, LIVE)
    assert result.status == "problems"
    assert [f.player_name for f in result.findings] == ["Hurt Guy"]
    assert result.all_clear is False


# --- the point of C7: silence is not an all-clear ---


def test_a_skipped_check_is_never_reported_as_all_clear(schedule, week):
    """No `lineupSlotCounts` means the empty-slot check did not run at all.

    Without this, the most elementary failure in fantasy football -- a slot
    with nobody in it -- produces the same output as a clean lineup. Absence
    of a finding is not evidence of a healthy roster; only a positive check is.
    """
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    result = build_check(
        league(mine, slots={}), schedule, espn_week(week), EARLY, LIVE
    )
    assert result.findings == []
    assert result.all_clear is False
    assert result.status == "unverified"
    assert any("empty slot" in b for b in result.blind_spots)


def test_stale_source_data_blocks_an_all_clear(schedule, week):
    """A week-old roster is a week-old lineup. It may be clean and irrelevant."""
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    stale = (SourceHealth("ESPN league", 604800.0, True, "connection refused"),)
    result = build_check(league(mine), schedule, espn_week(week), EARLY, stale)
    assert result.findings == []
    assert result.status == "unverified"
    assert any("ESPN league" in b for b in result.blind_spots)


def test_a_derived_week_blocks_an_all_clear(schedule, week):
    """Checking the wrong week cleanly is not the same as a clean week."""
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    derived = WeekResolution(week=week, source="derived")
    result = build_check(league(mine), schedule, derived, EARLY, LIVE)
    assert result.status == "unverified"
    assert any("week" in b for b in result.blind_spots)


def test_an_espn_diagnostic_blocks_an_all_clear(schedule, week):
    """An unrecognized slot id means a starter may be miscategorized as bench."""
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    result = build_check(
        league(mine, diagnostics=("unknown lineupSlotId 27",)),
        schedule, espn_week(week), EARLY, LIVE,
    )
    assert result.status == "unverified"
    assert any("27" in b for b in result.blind_spots)


def test_findings_outrank_blind_spots_in_the_status(schedule, week):
    """Something to fix beats something unverified: the user acts on the fix."""
    mine = team("Mine", True, entry("Hurt Guy", "WR", "KC", injury="OUT"))
    result = build_check(
        league(mine, slots={}), schedule, espn_week(week), EARLY, LIVE
    )
    assert result.blind_spots
    assert result.status == "problems"


# --- C7.1: what the result carries ---


def test_the_result_carries_week_provenance(schedule, week):
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    result = build_check(league(mine), schedule, espn_week(week), EARLY, LIVE)
    assert result.week == week
    assert result.week_source == "espn"


def test_the_result_carries_per_source_health(schedule, week):
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    result = build_check(league(mine), schedule, espn_week(week), EARLY, LIVE)
    assert [s.name for s in result.sources] == ["ESPN league", "NFL schedule"]


def test_the_result_names_when_the_next_slot_freezes(schedule, week):
    """A clean week still has a deadline, and the user should see it."""
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    result = build_check(league(mine), schedule, espn_week(week), EARLY, LIVE)
    assert result.next_lock == schedule.kickoff("KC", week)


def test_next_lock_ignores_kickoffs_that_have_already_passed(schedule, week):
    mine = team("Mine", True, entry("Healthy Guy", "WR", "KC"))
    after = schedule.kickoff("KC", week) + dt.timedelta(hours=1)
    result = build_check(league(mine), schedule, espn_week(week), after, LIVE)
    assert result.next_lock is None


def test_actionable_findings_are_separated_from_locked_ones(schedule, week):
    """D-011: a locked finding is reported, never dropped -- but it is not an
    alert, because there is nothing left to do about it."""
    mine = team("Mine", True, entry("Hurt Guy", "WR", "KC", injury="OUT"))
    after = schedule.kickoff("KC", week) + dt.timedelta(hours=1)
    result = build_check(league(mine), schedule, espn_week(week), after, LIVE)
    assert len(result.findings) == 1
    assert result.actionable == []


def test_a_finding_carries_its_fix_plan(schedule, week):
    """The fix kind, not just a time -- D-046."""
    mine = team(
        "Mine", True,
        entry("Hurt Guy", "WR", "KC", injury="OUT"),
        entry("Bench Guy", "WR", "BUF", slot="BN"),
    )
    result = build_check(league(mine), schedule, espn_week(week), EARLY, LIVE)
    finding = result.findings[0]
    assert finding.fix.verb == "Swap"
    assert "Bench Guy" in finding.replacements


# --- the fourth state, found by running this for real ---


def test_before_the_draft_an_empty_roster_is_not_a_lineup_problem(schedule, week):
    """Found on 2026-09-03, four days before the real draft.

    Every starting slot was legitimately empty and the check produced nine
    confident "claim someone by Friday" findings for a roster the draft would
    fill on Monday. Nine wrong alerts on the first night is how a notification
    channel becomes something you mute.
    """
    mine = team("Mine", True)  # no roster at all
    lg = league(mine, slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "BN": 7})
    from dataclasses import replace

    result = build_check(
        replace(lg, draft_completed=False), schedule, espn_week(week), EARLY, LIVE
    )
    assert result.findings == []
    assert result.status == "pre_draft"
    assert result.all_clear is False


def test_after_the_draft_the_checks_run_normally(schedule, week):
    from dataclasses import replace

    mine = team("Mine", True, entry("Hurt Guy", "WR", "KC", injury="OUT"))
    lg = replace(league(mine), draft_completed=True)
    result = build_check(lg, schedule, espn_week(week), EARLY, LIVE)
    assert result.status == "problems"


def test_an_unknown_draft_state_does_not_silence_the_checks(schedule, week):
    """`None` means ESPN did not say. Only ESPN saying `False` suppresses.

    Treating absence as "not drafted" would mute every alert for the season
    the first time ESPN renamed the field.
    """
    mine = team("Mine", True, entry("Hurt Guy", "WR", "KC", injury="OUT"))
    lg = league(mine)
    assert lg.draft_completed is None
    result = build_check(lg, schedule, espn_week(week), EARLY, LIVE)
    assert result.status == "problems"
