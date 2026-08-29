import datetime as dt
from pathlib import Path

import pytest

from ffcoach.advisors.lineup import actionable, find_problems, find_replacements
from ffcoach.leagues.base import RosterEntry, Team
from ffcoach.sources.schedule import parse_schedule

SCHEDULE = Path(__file__).parent / "fixtures" / "nfl_schedule_2025.csv"


@pytest.fixture(scope="module")
def schedule():
    return parse_schedule(SCHEDULE.read_text(), 2025)


def entry(name, position="WR", team="KC", slot=None, injury=None):
    return RosterEntry(
        player_name=name,
        position=position,
        nfl_team=team,
        lineup_slot=slot if slot is not None else position,
        injury_status=injury,
    )


def team_with(*entries):
    return Team(
        team_id="1",
        name="T",
        owner="Steve",
        wins=0,
        losses=0,
        ties=0,
        points_for=0.0,
        points_against=0.0,
        roster=tuple(entries),
        is_user_team=True,
    )


# Byes do not start until week 5 in a real NFL season, so the test week is
# derived from the schedule rather than assumed.
EARLY = dt.datetime(2025, 9, 1, 9, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def week(schedule):
    """A week that has at least one bye team and in which KC and BUF play."""
    for candidate in sorted(schedule.weeks):
        if not any(schedule.bye_week(t) == candidate for t in schedule.teams):
            continue
        if schedule.is_on_bye("KC", candidate) or schedule.is_on_bye("BUF", candidate):
            continue
        return candidate
    raise AssertionError("no suitable week in fixture")


def bye_team_for(schedule, week):
    return next(t for t in schedule.teams if schedule.bye_week(t) == week)


# --- the clean case, which must produce nothing ---


def test_a_healthy_lineup_produces_no_findings(schedule, week):
    team = team_with(entry("Healthy Guy", "WR", "KC"))
    assert find_problems(team, schedule, week, EARLY) == []


def test_bench_problems_are_ignored(schedule, week):
    """Only starters can cost points."""
    bye = bye_team_for(schedule, week)
    team = team_with(
        entry("Benched", "WR", bye, slot="BN"),
        entry("Also Benched", "RB", "KC", slot="BN", injury="OUT"),
    )
    assert find_problems(team, schedule, week, EARLY) == []


# --- bye detection ---


def test_starter_on_bye_is_found(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Bye Guy", "WR", bye))
    found = find_problems(team, schedule, week, EARLY)
    assert [f.kind for f in found] == ["bye"]
    assert found[0].player_name == "Bye Guy"


def test_bye_reason_names_the_team(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Bye Guy", "WR", bye))
    assert bye in find_problems(team, schedule, week, EARLY)[0].reason


def test_a_rams_starter_on_bye_is_found(schedule):
    """Regression: nflverse writes LA, ESPN writes LAR.

    Unhandled, this player would never match a schedule row and never alert.
    """
    bye = schedule.bye_week("LAR")
    team = team_with(entry("Rams Guy", "WR", "LAR"))
    found = find_problems(team, schedule, bye, EARLY)
    assert [f.kind for f in found] == ["bye"]


def test_a_commanders_starter_on_bye_is_found(schedule):
    bye = schedule.bye_week("WSH")
    team = team_with(entry("Commanders Guy", "RB", "WSH"))
    found = find_problems(team, schedule, bye, EARLY)
    assert [f.kind for f in found] == ["bye"]


# --- injury detection ---


@pytest.mark.parametrize("status", ["OUT", "INJURY_RESERVE", "SUSPENSION", "IR"])
def test_certainly_out_statuses_are_found(schedule, week, status):
    team = team_with(entry("Hurt Guy", "WR", "KC", injury=status))
    found = find_problems(team, schedule, week, EARLY)
    assert [f.kind for f in found] == ["out"]


@pytest.mark.parametrize("status", ["QUESTIONABLE", "DOUBTFUL", "ACTIVE", None])
def test_uncertain_statuses_are_not_reported_as_out(schedule, week, status):
    """Questionable is the inactives sweep's job, not this one's."""
    team = team_with(entry("Maybe Guy", "WR", "KC", injury=status))
    assert find_problems(team, schedule, week, EARLY) == []


def test_injury_status_case_and_underscores_are_tolerated(schedule, week):
    team = team_with(entry("Hurt Guy", "WR", "KC", injury="injury_reserve"))
    assert [f.kind for f in find_problems(team, schedule, week, EARLY)] == ["out"]


def test_out_takes_precedence_over_bye(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Both", "WR", bye, injury="OUT"))
    found = find_problems(team, schedule, week, EARLY)
    assert [f.kind for f in found] == ["out"]


# --- replacements ---


def test_replacement_suggests_an_eligible_healthy_bench_player(schedule, week):
    team = team_with(
        entry("Starter", "WR", "KC", injury="OUT"),
        entry("Backup", "WR", "BUF", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY)
    assert found[0].replacements == ("Backup",)
    assert "Backup" in found[0].reason


def test_replacement_excludes_a_bench_player_who_is_out(schedule, week):
    team = team_with(
        entry("Starter", "WR", "KC", injury="OUT"),
        entry("Hurt Backup", "WR", "BUF", slot="BN", injury="OUT"),
    )
    assert find_problems(team, schedule, week, EARLY)[0].replacements == ()


def test_replacement_excludes_a_bench_player_on_bye(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(
        entry("Starter", "WR", "KC", injury="OUT"),
        entry("Bye Backup", "WR", bye, slot="BN"),
    )
    assert find_problems(team, schedule, week, EARLY)[0].replacements == ()


def test_replacement_excludes_a_wrong_position_bench_player(schedule, week):
    team = team_with(
        entry("Starter", "WR", "KC", injury="OUT"),
        entry("A Kicker", "K", "BUF", slot="BN"),
    )
    assert find_problems(team, schedule, week, EARLY)[0].replacements == ()


def test_flex_accepts_rb_wr_and_te(schedule, week):
    team = team_with(
        entry("Flex Starter", "WR", "KC", slot="FLEX", injury="OUT"),
        entry("A Back", "RB", "BUF", slot="BN"),
        entry("An End", "TE", "BUF", slot="BN"),
        entry("A Kicker", "K", "BUF", slot="BN"),
    )
    names = find_problems(team, schedule, week, EARLY)[0].replacements
    assert set(names) == {"A Back", "An End"}


def test_reason_says_so_when_no_replacement_exists(schedule, week):
    team = team_with(entry("Starter", "WR", "KC", injury="OUT"))
    assert "no healthy bench player" in find_problems(team, schedule, week, EARLY)[0].reason


def test_find_replacements_is_usable_directly(schedule, week):
    team = team_with(entry("Backup", "RB", "BUF", slot="BN"))
    assert find_replacements(team, "RB", schedule, week) == ("Backup",)


# --- locking and ordering ---


def test_a_finding_past_kickoff_is_marked_locked(schedule, week):
    late = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    team = team_with(entry("Hurt Guy", "WR", "KC", injury="OUT"))
    assert find_problems(team, schedule, week, late)[0].locked is True


def test_a_finding_before_kickoff_is_not_locked(schedule, week):
    team = team_with(entry("Hurt Guy", "WR", "KC", injury="OUT"))
    assert find_problems(team, schedule, week, EARLY)[0].locked is False


def test_locked_findings_are_reported_but_not_actionable(schedule, week):
    late = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    team = team_with(entry("Hurt Guy", "WR", "KC", injury="OUT"))
    found = find_problems(team, schedule, week, late)
    assert len(found) == 1
    assert actionable(found) == []


def test_out_sorts_before_bye(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(
        entry("Bye Guy", "WR", bye),
        entry("Hurt Guy", "RB", "KC", injury="OUT"),
    )
    assert [f.kind for f in find_problems(team, schedule, week, EARLY)] == ["out", "bye"]


def test_actionable_findings_sort_before_locked_ones(schedule, week):
    """A team whose game already kicked off vs one that has not."""
    team = team_with(
        entry("Early Guy", "WR", "KC", injury="OUT"),
        entry("Later Guy", "RB", "BUF", injury="OUT"),
    )
    kicks = {t: schedule.kickoff(t, week) for t in ("KC", "BUF")}
    between = min(kicks.values()) + dt.timedelta(minutes=1)
    found = find_problems(team, schedule, week, between)
    assert [f.locked for f in found] == sorted(f.locked for f in found)


def test_a_finding_carries_its_kickoff(schedule, week):
    team = team_with(entry("Hurt Guy", "WR", "KC", injury="OUT"))
    assert find_problems(team, schedule, week, EARLY)[0].kickoff is not None


def test_bye_finding_has_no_kickoff(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Bye Guy", "WR", bye))
    assert find_problems(team, schedule, week, EARLY)[0].kickoff is None


def test_a_bye_finding_is_never_locked(schedule, week):
    """No kickoff means the slot stays changeable all week."""
    bye = bye_team_for(schedule, week)
    late = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    team = team_with(entry("Bye Guy", "WR", bye))
    assert find_problems(team, schedule, week, late)[0].locked is False


def test_no_finding_ever_emits_a_dollar_figure(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(
        entry("Bye Guy", "WR", bye),
        entry("Hurt Guy", "RB", "KC", injury="OUT"),
    )
    for finding in find_problems(team, schedule, week, EARLY):
        assert "$" not in finding.reason
