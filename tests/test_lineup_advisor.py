import datetime as dt
from pathlib import Path

import pytest

from ffcoach.advisors.lineup import actionable, find_problems, find_replacements
from ffcoach.leagues.base import LineupLock, LockMode, RosterEntry, Team
from ffcoach.model.deadlines import FixKind
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


# --- empty starting slots ---
#
# An empty slot is a guaranteed zero and the most elementary lineup failure
# there is. It was invisible to the first implementation because that iterated
# roster entries, and an empty slot has no entry to iterate.

STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}


def test_an_unfilled_starting_slot_is_found(schedule, week):
    team = team_with(entry("Only Back", "RB", "KC", slot="RB"))
    found = find_problems(team, schedule, week, EARLY, required_slots={"RB": 2})
    assert [f.kind for f in found] == ["empty_slot"]
    assert found[0].lineup_slot == "RB"


def test_each_missing_slot_produces_its_own_finding(schedule, week):
    team = team_with(entry("Only Back", "RB", "KC", slot="RB"))
    found = find_problems(team, schedule, week, EARLY, required_slots={"RB": 3})
    assert len(found) == 2


def test_a_fully_filled_lineup_reports_no_empty_slots(schedule, week):
    team = team_with(
        entry("QB1", "QB", "KC", slot="QB"),
        entry("RB1", "RB", "KC", slot="RB"),
        entry("RB2", "RB", "BUF", slot="RB"),
    )
    found = find_problems(
        team, schedule, week, EARLY, required_slots={"QB": 1, "RB": 2}
    )
    assert found == []


def test_an_empty_bench_slot_is_not_a_problem(schedule, week):
    """Only starting slots can cost points."""
    team = team_with(entry("QB1", "QB", "KC", slot="QB"))
    found = find_problems(
        team, schedule, week, EARLY, required_slots={"QB": 1, "BN": 6, "IR": 1}
    )
    assert found == []


def test_empty_slot_names_an_eligible_bench_replacement(schedule, week):
    team = team_with(entry("A Back", "RB", "BUF", slot="BN"))
    found = find_problems(team, schedule, week, EARLY, required_slots={"RB": 1})
    assert found[0].replacements == ("A Back",)
    assert "A Back" in found[0].reason


def test_empty_flex_accepts_any_flex_eligible_bench_player(schedule, week):
    team = team_with(entry("An End", "TE", "BUF", slot="BN"))
    found = find_problems(team, schedule, week, EARLY, required_slots={"FLEX": 1})
    assert found[0].replacements == ("An End",)


def test_empty_slot_reason_says_the_slot_is_empty(schedule, week):
    team = team_with()
    found = find_problems(team, schedule, week, EARLY, required_slots={"QB": 1})
    assert "empty" in found[0].reason.lower()


def test_empty_slot_sorts_with_out_not_after_bye(schedule, week):
    """Same severity as OUT (D-012), which sorts ahead of bye."""
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Bye Guy", "WR", bye, slot="WR"))
    found = find_problems(
        team, schedule, week, EARLY, required_slots={"WR": 1, "QB": 1}
    )
    kinds = [f.kind for f in found]
    assert kinds.index("empty_slot") < kinds.index("bye")


def test_an_empty_slot_stays_changeable_while_the_week_is_still_running(schedule, week):
    """No player means no kickoff of its own, so it is not frozen at 1pm."""
    team = team_with()
    found = find_problems(team, schedule, week, EARLY, required_slots={"QB": 1})
    assert found[0].locked is False


def test_an_empty_slot_does_not_stay_fixable_after_the_week_ends(schedule, week):
    """The bug this replaced: "no kickoff" was read as "never locks".

    An empty Week 5 slot reported itself as actionable on New Year's Day,
    because nothing bounded a slot that had no player to lock it. Once the
    week's last game starts, nothing anyone adds can score in it.
    """
    late = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    found = find_problems(team_with(), schedule, week, late, required_slots={"QB": 1})
    assert found[0].locks_at == schedule.lock_windows(week)[-1]
    assert found[0].locked is True
    assert found[0].is_actionable(late) is False


def test_omitting_required_slots_skips_the_check_entirely(schedule, week):
    """Without slot counts we genuinely cannot know, so we claim nothing."""
    team = team_with(entry("Only Back", "RB", "KC", slot="RB"))
    assert find_problems(team, schedule, week, EARLY) == []


def test_a_player_in_a_slot_the_league_does_not_use_is_ignored(schedule, week):
    team = team_with(entry("Oddity", "QB", "KC", slot="OP"))
    found = find_problems(team, schedule, week, EARLY, required_slots={"QB": 1})
    assert [f.kind for f in found] == ["empty_slot"]


def test_an_out_starter_still_counts_as_filling_his_slot(schedule, week):
    """He is in the slot; the problem is that he is out, not that it is empty."""
    team = team_with(entry("Hurt Guy", "RB", "KC", slot="RB", injury="OUT"))
    found = find_problems(team, schedule, week, EARLY, required_slots={"RB": 1})
    assert [f.kind for f in found] == ["out"]


# --- action deadlines (C4) ---
#
# The reframe: the deadline belongs to the available *fix*, not to the problem.
# The same injury is a lineup swap when the bench covers it and a waiver claim
# when it does not -- and those have very different deadlines.

WAIVER = dt.datetime(2025, 9, 10, 11, tzinfo=dt.UTC)


def test_the_same_problem_yields_different_deadlines_by_bench_depth(schedule, week):
    """The heart of C4 — identical injury, opposite deadlines."""
    covered = team_with(
        entry("Hurt Guy", "RB", "KC", injury="OUT"),
        entry("Backup", "RB", "BUF", slot="BN"),
    )
    stranded = team_with(entry("Hurt Guy", "RB", "KC", injury="OUT"))

    a = find_problems(covered, schedule, week, EARLY, waiver_deadline=WAIVER)[0]
    b = find_problems(stranded, schedule, week, EARLY, waiver_deadline=WAIVER)[0]

    assert a.needs_waiver is False
    assert b.needs_waiver is True
    assert a.deadline != b.deadline
    assert b.deadline == WAIVER


def test_a_covered_problem_is_deadlined_by_kickoff_not_waivers(schedule, week):
    team = team_with(
        entry("Hurt Guy", "RB", "KC", injury="OUT"),
        entry("Backup", "RB", "BUF", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY, waiver_deadline=WAIVER)[0]
    assert found.deadline in (
        schedule.kickoff("KC", week),
        schedule.kickoff("BUF", week),
    )


def test_an_uncovered_problem_needs_a_claim(schedule, week):
    team = team_with(entry("Hurt Guy", "RB", "KC", injury="OUT"))
    found = find_problems(team, schedule, week, EARLY, waiver_deadline=WAIVER)[0]
    assert found.needs_waiver is True


def test_an_empty_slot_with_no_bench_cover_needs_a_claim(schedule, week):
    team = team_with()
    found = find_problems(
        team, schedule, week, EARLY, required_slots={"QB": 1}, waiver_deadline=WAIVER
    )[0]
    assert found.needs_waiver is True
    assert found.deadline == WAIVER


def test_an_empty_slot_the_bench_covers_does_not_need_a_claim(schedule, week):
    team = team_with(entry("A Back", "RB", "BUF", slot="BN"))
    found = find_problems(
        team, schedule, week, EARLY, required_slots={"RB": 1}, waiver_deadline=WAIVER
    )[0]
    assert found.needs_waiver is False


def test_an_unknown_waiver_schedule_is_reported_as_unknown_not_guessed(schedule, week):
    """No waiver schedule published, so we never name a claim window.

    The deadline that remains is the week's own bound, which is a fact about
    the NFL calendar rather than an invented league setting.
    """
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Bye Guy", "WR", bye))
    found = find_problems(team, schedule, week, EARLY)[0]
    assert found.fix.kind is FixKind.UNKNOWN
    assert found.deadline == schedule.lock_windows(week)[-1]
    assert found.needs_waiver is True


# --- bye look-ahead (C4.3) ---


def test_next_week_bye_with_no_cover_is_flagged_early(schedule):
    """Reacting during the bye week is too late; the claim window is now."""
    bye = schedule.bye_week("KC")
    team = team_with(entry("Chiefs Guy", "WR", "KC"))
    found = find_problems(
        team, schedule, bye - 1, EARLY, waiver_deadline=WAIVER, look_ahead=True
    )
    kinds = [f.kind for f in found]
    assert "bye_next_week" in kinds
    ahead = next(f for f in found if f.kind == "bye_next_week")
    assert ahead.needs_waiver is True
    assert ahead.deadline == WAIVER


def test_next_week_bye_the_bench_covers_is_not_flagged(schedule):
    """A bye you can absorb is not worth a message."""
    bye = schedule.bye_week("KC")
    team = team_with(
        entry("Chiefs Guy", "WR", "KC"),
        entry("Cover Guy", "WR", "BUF", slot="BN"),
    )
    found = find_problems(
        team, schedule, bye - 1, EARLY, waiver_deadline=WAIVER, look_ahead=True
    )
    assert [f for f in found if f.kind == "bye_next_week"] == []


def test_look_ahead_is_off_by_default(schedule):
    bye = schedule.bye_week("KC")
    team = team_with(entry("Chiefs Guy", "WR", "KC"))
    found = find_problems(team, schedule, bye - 1, EARLY, waiver_deadline=WAIVER)
    assert [f for f in found if f.kind == "bye_next_week"] == []


def test_next_week_bye_sorts_after_this_weeks_problems(schedule):
    bye = schedule.bye_week("KC")
    team = team_with(
        entry("Chiefs Guy", "WR", "KC"),
        entry("Hurt Guy", "RB", "BUF", injury="OUT"),
    )
    found = find_problems(
        team, schedule, bye - 1, EARLY, waiver_deadline=WAIVER, look_ahead=True
    )
    kinds = [f.kind for f in found]
    assert kinds.index("out") < kinds.index("bye_next_week")


def test_next_week_bye_reason_says_next_week(schedule):
    bye = schedule.bye_week("KC")
    team = team_with(entry("Chiefs Guy", "WR", "KC"))
    found = find_problems(
        team, schedule, bye - 1, EARLY, waiver_deadline=WAIVER, look_ahead=True
    )
    ahead = next(f for f in found if f.kind == "bye_next_week")
    assert "next week" in ahead.reason.lower()
    assert "$" not in ahead.reason


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


def test_a_bye_starters_slot_stays_changeable_during_his_off_week(schedule, week):
    """He has no kickoff of his own, so nothing freezes the slot at 1pm."""
    bye = bye_team_for(schedule, week)
    team = team_with(entry("Bye Guy", "WR", bye))
    assert find_problems(team, schedule, week, EARLY)[0].locked is False


def test_a_bye_starter_stops_being_actionable_once_the_week_is_over(schedule, week):
    """Same defect as the empty slot: no kickoff was read as never locking."""
    bye = bye_team_for(schedule, week)
    late = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    found = find_problems(team_with(entry("Bye Guy", "WR", bye)), schedule, week, late)[0]
    assert found.locked is True
    assert found.is_actionable(late) is False


def test_no_finding_ever_emits_a_dollar_figure(schedule, week):
    bye = bye_team_for(schedule, week)
    team = team_with(
        entry("Bye Guy", "WR", bye),
        entry("Hurt Guy", "RB", "KC", injury="OUT"),
    )
    for finding in find_problems(team, schedule, week, EARLY):
        assert "$" not in finding.reason


# --- weekly lineup lock (C5) ---
#
# Some ESPN leagues freeze every slot at the week's first kickoff instead of
# per player. Under that rule the per-player timing this advisor was built on
# is not merely imprecise, it is wrong: a Sunday alert about a Monday-night
# starter is useless because he locked on Thursday.

WEEKLY = LineupLock(mode=LockMode.WEEKLY, raw="FIRST_GAME_OF_WEEK")
PER_PLAYER = LineupLock(mode=LockMode.PER_PLAYER, raw="INDIVIDUAL_GAME")


@pytest.fixture(scope="module")
def late_team(schedule, week):
    """A team whose game is not the week's first -- the case that diverges."""
    first = schedule.lock_windows(week)[0]
    for t in sorted(schedule.teams):
        kick = schedule.kickoff(t, week)
        if kick is not None and kick > first:
            return t
    raise AssertionError("no later game in fixture week")


def test_weekly_lock_freezes_a_late_starter_at_the_weeks_first_kickoff(
    schedule, week, late_team
):
    first = schedule.lock_windows(week)[0]
    team = team_with(entry("Late Guy", "WR", late_team, injury="OUT"))
    found = find_problems(team, schedule, week, EARLY, lock=WEEKLY)[0]
    assert found.locks_at == first


def test_per_player_lock_freezes_him_at_his_own_kickoff(schedule, week, late_team):
    team = team_with(entry("Late Guy", "WR", late_team, injury="OUT"))
    found = find_problems(team, schedule, week, EARLY, lock=PER_PLAYER)[0]
    assert found.locks_at == schedule.kickoff(late_team, week)
    assert found.locks_at > schedule.lock_windows(week)[0]


def test_weekly_lock_reports_him_locked_once_the_first_game_has_started(
    schedule, week, late_team
):
    """The whole point: he is unmovable well before he plays."""
    just_after_first = schedule.lock_windows(week)[0] + dt.timedelta(minutes=1)
    team = team_with(entry("Late Guy", "WR", late_team, injury="OUT"))
    found = find_problems(team, schedule, week, just_after_first, lock=WEEKLY)[0]
    assert found.locked is True
    assert found.kickoff > just_after_first  # he has not even played yet


def test_the_same_moment_is_still_actionable_under_per_player_locking(
    schedule, week, late_team
):
    just_after_first = schedule.lock_windows(week)[0] + dt.timedelta(minutes=1)
    team = team_with(entry("Late Guy", "WR", late_team, injury="OUT"))
    found = find_problems(team, schedule, week, just_after_first, lock=PER_PLAYER)[0]
    assert found.locked is False


def test_weekly_lock_keeps_the_real_kickoff_separate_from_the_lock(
    schedule, week, late_team
):
    """`kickoff` is when he plays; `locks_at` is when you lose the choice."""
    team = team_with(entry("Late Guy", "WR", late_team, injury="OUT"))
    found = find_problems(team, schedule, week, EARLY, lock=WEEKLY)[0]
    assert found.kickoff == schedule.kickoff(late_team, week)
    assert found.locks_at < found.kickoff


def test_weekly_lock_collapses_every_deadline_to_one_moment(schedule, week, late_team):
    first = schedule.lock_windows(week)[0]
    early_team = next(t for t in schedule.teams if schedule.kickoff(t, week) == first)
    team = team_with(
        entry("Late Guy", "WR", late_team, injury="OUT"),
        entry("Early Guy", "RB", early_team, injury="OUT"),
    )
    deadlines = {f.deadline for f in find_problems(team, schedule, week, EARLY, lock=WEEKLY)}
    assert deadlines == {first}


def test_per_player_locking_leaves_those_two_deadlines_different(
    schedule, week, late_team
):
    first = schedule.lock_windows(week)[0]
    early_team = next(t for t in schedule.teams if schedule.kickoff(t, week) == first)
    team = team_with(
        entry("Late Guy", "WR", late_team, injury="OUT"),
        entry("Early Guy", "RB", early_team, injury="OUT"),
    )
    found = find_problems(team, schedule, week, EARLY, lock=PER_PLAYER)
    assert len({f.deadline for f in found}) == 2


def test_an_empty_slot_locks_at_the_first_game_under_a_weekly_lock(schedule, week):
    """Weekly locking freezes an empty slot with everything else, on Thursday.

    Per-player locking leaves it open longer -- but not forever: it still ends
    at the week's last kickoff, because after that no addition can score.
    """
    team = team_with(entry("Bench Guy", "RB", "KC", slot="BN"))
    args = (team, schedule, week, EARLY)
    weekly = find_problems(*args, required_slots={"RB": 1}, lock=WEEKLY)[0]
    per_player = find_problems(*args, required_slots={"RB": 1}, lock=PER_PLAYER)[0]
    windows = schedule.lock_windows(week)
    assert weekly.locks_at == windows[0]
    assert per_player.locks_at == windows[-1]
    assert weekly.locks_at < per_player.locks_at


def test_omitting_the_lock_behaves_exactly_like_espns_default(schedule, week, late_team):
    team = team_with(entry("Late Guy", "WR", late_team, injury="OUT"))
    assert find_problems(team, schedule, week, EARLY) == find_problems(
        team, schedule, week, EARLY, lock=PER_PLAYER
    )


# --- one bench player cannot fix two slots (D-045) ---
#
# Every card below was individually true before this and the set was jointly
# impossible: two findings naming the same man, so fixing either left the other
# exactly as broken.


def test_two_broken_starters_are_not_both_offered_the_same_replacement(schedule, week):
    team = team_with(
        entry("Hurt One", "WR", "KC", slot="WR", injury="OUT"),
        entry("Hurt Two", "WR", "BUF", slot="WR", injury="OUT"),
        entry("Only Sub", "WR", "KC", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY)
    named = [f.replacements for f in found]
    assert sum("Only Sub" in r for r in named) == 1
    assert () in named, "the uncovered slot must say so rather than share him"


def test_the_uncovered_slot_becomes_an_acquisition_not_a_swap(schedule, week):
    team = team_with(
        entry("Hurt One", "WR", "KC", slot="WR", injury="OUT"),
        entry("Hurt Two", "WR", "BUF", slot="WR", injury="OUT"),
        entry("Only Sub", "WR", "KC", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY, waiver_deadline=WAIVER)
    kinds = {f.fix.kind for f in found}
    assert FixKind.BENCH_SWAP in kinds
    assert kinds - {FixKind.BENCH_SWAP}, "one slot still needs someone acquired"


def test_an_empty_slot_and_a_broken_starter_compete_for_the_same_bench(schedule, week):
    """They are collected together precisely so they cannot both be told yes."""
    team = team_with(
        entry("Hurt Guy", "RB", "KC", slot="RB", injury="OUT"),
        entry("Only Back", "RB", "BUF", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY, required_slots={"RB": 2})
    assert sum("Only Back" in f.replacements for f in found) == 1


def test_a_deep_bench_still_covers_every_opening(schedule, week):
    """The allocation must not invent scarcity that is not there."""
    team = team_with(
        entry("Hurt One", "WR", "KC", slot="WR", injury="OUT"),
        entry("Hurt Two", "WR", "BUF", slot="WR", injury="OUT"),
        entry("Sub One", "WR", "KC", slot="BN"),
        entry("Sub Two", "WR", "BUF", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY)
    assert all(f.replacements for f in found)
    assert len({f.replacements[0] for f in found}) == 2


def test_the_scarce_position_is_served_before_flex(schedule, week):
    """FLEX could take the only RB and leave the RB slot with nothing."""
    team = team_with(
        entry("Hurt Back", "RB", "KC", slot="RB", injury="OUT"),
        entry("Hurt Flex", "WR", "BUF", slot="FLEX", injury="OUT"),
        entry("Sub Back", "RB", "KC", slot="BN"),
        entry("Sub Wide", "WR", "BUF", slot="BN"),
    )
    found = {f.lineup_slot: f for f in find_problems(team, schedule, week, EARLY)}
    assert found["RB"].replacements[0] == "Sub Back"
    assert found["FLEX"].replacements[0] == "Sub Wide"


# --- IR is a prerequisite, not a bench slot ---


def test_a_healthy_player_on_ir_is_not_offered_as_a_direct_swap(schedule, week):
    """ESPN refuses to start a player out of an IR slot, so naming him as the
    replacement describes a move the site will not allow."""
    team = team_with(
        entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"),
        entry("Back From IR", "WR", "BUF", slot="IR"),
    )
    found = find_problems(team, schedule, week, EARLY)[0]
    assert found.replacements == ()


def test_a_healthy_player_on_ir_is_reported_rather_than_dropped(schedule, week):
    """Nothing is dropped silently: he is a real option, at an extra step."""
    team = team_with(
        entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"),
        entry("Back From IR", "WR", "BUF", slot="IR"),
    )
    found = find_problems(team, schedule, week, EARLY)[0]
    assert found.ir_candidates == ("Back From IR",)
    assert "IR" in found.reason


def test_a_genuinely_injured_ir_player_is_not_reported_as_available(schedule, week):
    team = team_with(
        entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"),
        entry("Still Hurt", "WR", "BUF", slot="IR", injury="INJURY_RESERVE"),
    )
    assert find_problems(team, schedule, week, EARLY)[0].ir_candidates == ()


# --- a claim that cannot land is not offered as a claim ---


def test_a_waiver_run_after_the_lock_is_not_presented_as_a_claim(schedule, week):
    """The correction to C5's clamp, end to end through the advisor."""
    kick = schedule.kickoff("KC", week)
    late_waiver = kick + dt.timedelta(days=1)
    team = team_with(entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"))
    found = find_problems(
        team, schedule, week, EARLY, waiver_deadline=late_waiver
    )[0]
    assert found.fix.kind is FixKind.ADD_BEFORE_LOCK
    assert found.fix.claim_lands_in_time is False
    assert found.deadline == kick
    assert "cannot arrive in time" in found.reason


def test_a_waiver_run_before_the_lock_is_still_a_claim(schedule, week):
    kick = schedule.kickoff("KC", week)
    team = team_with(entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"))
    found = find_problems(
        team, schedule, week, EARLY, waiver_deadline=kick - dt.timedelta(days=1)
    )[0]
    assert found.fix.kind is FixKind.WAIVER_CLAIM
    assert "Claim someone" in found.reason


# --- actionable() now asks the whole question ---


def test_a_finding_whose_replacement_already_played_is_not_actionable(schedule, week):
    """It used to check only `locked`. The slot can be open while every option
    that could fill it has kicked off."""
    team = team_with(
        entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"),
        entry("Early Sub", "WR", "KC", slot="BN"),
    )
    found = find_problems(team, schedule, week, EARLY)
    after = found[0].deadline + dt.timedelta(minutes=1)
    assert found[0].is_actionable(EARLY) is True
    assert actionable(found, after) == []


def test_actionable_without_a_clock_still_answers_the_old_weaker_question(schedule, week):
    team = team_with(entry("Hurt Guy", "WR", "KC", slot="WR", injury="OUT"))
    found = find_problems(team, schedule, week, EARLY)
    assert actionable(found) == found


# --- E6: the inactives sweep ---------------------------------------------
#
# The one check whose existence depends on the clock. Every test here is about
# *when*, because that is the entire feature: the same roster produces nothing
# on Wednesday and a finding ninety minutes before kickoff.


def at_risk_roster(injury="QUESTIONABLE"):
    # The backup plays the same game as the starter deliberately. A backup on
    # another team may have kicked off already, and by then he is not a
    # replacement -- which is its own test, below.
    return team_with(
        entry("Doubtful Starter", "WR", "KC", injury=injury),
        entry("Backup WR", "WR", "KC", slot="BN"),
    )


def kickoff_for(schedule, week, team="KC"):
    return schedule.kickoff(team, week)


def only_at_risk(findings):
    return [f for f in findings if f.kind == "at_risk"]


def test_a_questionable_starter_is_not_a_finding_days_early(schedule, week):
    """Most Questionable players play. Benching one on Wednesday loses points."""
    findings = find_problems(at_risk_roster(), schedule, week, EARLY)
    assert only_at_risk(findings) == []


def test_a_questionable_starter_becomes_a_finding_inside_the_window(schedule, week):
    kickoff = kickoff_for(schedule, week)
    now = kickoff - dt.timedelta(minutes=80)
    findings = only_at_risk(find_problems(at_risk_roster(), schedule, week, now))
    assert len(findings) == 1
    assert findings[0].player_name == "Doubtful Starter"


def test_the_window_opens_at_ninety_minutes_and_not_before(schedule, week):
    """The NFL publishes inactives 90 minutes out; earlier there is no answer."""
    kickoff = kickoff_for(schedule, week)
    outside = kickoff - dt.timedelta(minutes=91)
    inside = kickoff - dt.timedelta(minutes=89)
    assert only_at_risk(find_problems(at_risk_roster(), schedule, week, outside)) == []
    assert only_at_risk(find_problems(at_risk_roster(), schedule, week, inside))


def test_nothing_is_reported_once_the_slot_has_locked(schedule, week):
    """A decision you can no longer make is not a decision."""
    kickoff = kickoff_for(schedule, week)
    at_lock = only_at_risk(find_problems(at_risk_roster(), schedule, week, kickoff))
    after = only_at_risk(
        find_problems(at_risk_roster(), schedule, week, kickoff + dt.timedelta(minutes=5))
    )
    assert at_lock == []
    assert after == []


def test_a_zero_window_turns_the_sweep_off(schedule, week):
    kickoff = kickoff_for(schedule, week)
    now = kickoff - dt.timedelta(minutes=30)
    findings = find_problems(
        at_risk_roster(), schedule, week, now, window=dt.timedelta(0)
    )
    assert only_at_risk(findings) == []


def test_an_out_starter_is_reported_once_not_twice(schedule, week):
    """`out` and `at_risk` must not both fire for the same man."""
    kickoff = kickoff_for(schedule, week)
    now = kickoff - dt.timedelta(minutes=30)
    findings = find_problems(at_risk_roster(injury="OUT"), schedule, week, now)
    kinds = [f.kind for f in findings if f.player_name == "Doubtful Starter"]
    assert kinds == ["out"]


def test_a_questionable_starter_on_bye_is_reported_as_a_bye(schedule, week):
    """The bye is certain; the injury no longer decides anything."""
    bye_team = bye_team_for(schedule, week)
    team = team_with(entry("On Bye", "WR", bye_team, injury="QUESTIONABLE"))
    # A bye slot locks at the week's *last* kickoff, so anchor on that.
    last = schedule.lock_windows(week)[-1]
    findings = find_problems(team, schedule, week, last - dt.timedelta(minutes=30))
    kinds = [f.kind for f in findings if f.player_name == "On Bye"]
    assert kinds == ["bye"]


def test_a_questionable_bench_player_is_never_a_finding(schedule, week):
    """He is not in the lineup, so his status costs nothing."""
    kickoff = kickoff_for(schedule, week)
    team = team_with(entry("Benched", "WR", "KC", slot="BN", injury="QUESTIONABLE"))
    findings = find_problems(
        team, schedule, week, kickoff - dt.timedelta(minutes=30)
    )
    assert only_at_risk(findings) == []


def test_the_finding_names_the_status_and_points_at_the_inactives_report(schedule, week):
    """UX rule 4, and honesty about what this tool can actually see.

    Nothing here fetches an inactives list. The reason must say what ESPN
    still reports and leave the ruling to the source that has it.
    """
    kickoff = kickoff_for(schedule, week)
    finding = only_at_risk(
        find_problems(at_risk_roster(), schedule, week, kickoff - dt.timedelta(minutes=30))
    )[0]
    assert "Questionable" in finding.reason
    assert "Backup WR" in finding.reason


def test_the_deadline_is_his_own_kickoff_and_the_fix_is_a_swap(schedule, week):
    kickoff = kickoff_for(schedule, week)
    finding = only_at_risk(
        find_problems(at_risk_roster(), schedule, week, kickoff - dt.timedelta(minutes=30))
    )[0]
    assert finding.fix.kind is FixKind.BENCH_SWAP
    assert finding.replacements == ("Backup WR",)
    assert finding.deadline <= kickoff
    assert finding.is_actionable(kickoff - dt.timedelta(minutes=30)) is True


def test_it_is_still_reported_when_the_bench_cannot_cover_it(schedule, week):
    """Deliberately not suppressed.

    A waiver claim cannot process inside ninety minutes, but an ESPN free agent
    can be added instantly, so there is a real action left. `plan_fix` already
    says exactly that, which is why this needs no special case -- and silence
    here would be indistinguishable from a healthy lineup.
    """
    kickoff = kickoff_for(schedule, week)
    team = team_with(entry("Alone", "WR", "KC", injury="QUESTIONABLE"))
    finding = only_at_risk(
        find_problems(
            team,
            schedule,
            week,
            kickoff - dt.timedelta(minutes=30),
            waiver_deadline=kickoff + dt.timedelta(days=1),
        )
    )[0]
    assert finding.fix.kind is FixKind.ADD_BEFORE_LOCK
    assert "claim cannot arrive in time" in finding.reason


def test_an_out_starter_gets_the_last_bench_player_before_a_doubtful_one(schedule, week):
    """The allocation tiebreak, end to end.

    One healthy bench WR, two broken WR slots -- one certainly out, one merely
    Questionable. The certain zero must get him.
    """
    kickoff = kickoff_for(schedule, week)
    team = team_with(
        entry("Ruled Out", "WR", "KC", slot="WR", injury="OUT"),
        entry("Maybe Playing", "WR", "KC", slot="FLEX", injury="QUESTIONABLE"),
        entry("Only Backup", "WR", "KC", slot="BN"),
    )
    findings = find_problems(
        team, schedule, week, kickoff - dt.timedelta(minutes=30)
    )
    by_player = {f.player_name: f for f in findings}
    assert by_player["Ruled Out"].replacements == ("Only Backup",)
    assert by_player["Maybe Playing"].replacements == ()


def test_at_risk_sorts_above_a_bye(schedule, week):
    """Its slot freezes sooner, which is what the ordering is for."""
    kickoff = kickoff_for(schedule, week)
    bye_team = bye_team_for(schedule, week)
    team = team_with(
        entry("On Bye", "RB", bye_team, slot="RB"),
        entry("Maybe Playing", "WR", "KC", slot="WR", injury="QUESTIONABLE"),
    )
    findings = find_problems(
        team, schedule, week, kickoff - dt.timedelta(minutes=30)
    )
    assert [f.player_name for f in findings] == ["Maybe Playing", "On Bye"]


def test_under_a_weekly_lock_the_window_tracks_the_lock_not_the_kickoff(schedule, week):
    """A Sunday starter froze on Thursday; ninety minutes before his own game
    is ninety minutes too late to tell anyone."""
    weekly = LineupLock(mode=LockMode.WEEKLY)
    first = schedule.lock_windows(week)[0]
    kickoff = kickoff_for(schedule, week)
    if kickoff <= first + dt.timedelta(hours=2):
        pytest.skip("fixture has no team playing well after the week's first game")

    at_his_kickoff = find_problems(
        at_risk_roster(), schedule, week, kickoff - dt.timedelta(minutes=30), lock=weekly
    )
    at_the_lock = find_problems(
        at_risk_roster(), schedule, week, first - dt.timedelta(minutes=30), lock=weekly
    )
    assert only_at_risk(at_his_kickoff) == []
    assert only_at_risk(at_the_lock)


def test_a_backup_whose_game_already_started_is_not_a_replacement(schedule, week):
    """Found by a test, and only visible once a check ran mid-week.

    The starter plays Monday night; the backup played Sunday afternoon. Naming
    him is a move ESPN will refuse, and it turns a finding the user could still
    act on -- add a free agent before kickoff -- into one that reads as already
    too late.
    """
    kickoff = kickoff_for(schedule, week)
    early = kickoff_for(schedule, week, "BUF")
    assert early < kickoff, "fixture no longer has BUF playing before KC"

    team = team_with(
        entry("Doubtful Starter", "WR", "KC", injury="QUESTIONABLE"),
        entry("Already Played", "WR", "BUF", slot="BN"),
    )
    finding = only_at_risk(
        find_problems(
            team,
            schedule,
            week,
            kickoff - dt.timedelta(minutes=30),
            waiver_deadline=kickoff + dt.timedelta(days=1),
        )
    )[0]
    assert finding.replacements == ()
    assert finding.fix.kind is FixKind.ADD_BEFORE_LOCK
    assert finding.is_actionable(kickoff - dt.timedelta(minutes=30)) is True


def test_the_same_backup_counts_before_his_own_game(schedule, week):
    """The filter is the clock, not the team."""
    early = kickoff_for(schedule, week, "BUF")
    team = team_with(
        entry("Doubtful Starter", "WR", "KC", injury="QUESTIONABLE"),
        entry("Not Yet Played", "WR", "BUF", slot="BN"),
    )
    assert find_replacements(
        team, "WR", schedule, week, early - dt.timedelta(hours=1)
    ) == ("Not Yet Played",)
    assert find_replacements(
        team, "WR", schedule, week, early + dt.timedelta(hours=1)
    ) == ()


def test_replacements_ignore_the_clock_when_not_given_one(schedule, week):
    """`find_upcoming_byes` asks about next week, where this week's clock is
    meaningless -- so the filter has to be opt-in."""
    team = team_with(
        entry("Doubtful Starter", "WR", "KC", injury="QUESTIONABLE"),
        entry("Some Backup", "WR", "BUF", slot="BN"),
    )
    assert find_replacements(team, "WR", schedule, week) == ("Some Backup",)
