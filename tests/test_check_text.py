"""The terminal rendering of a check.

Two binding UX rules reach this file. Status is never carried by colour
(there is no ANSI here at all), and every finding states its reason inline.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from ffcoach.check import CheckResult, SourceHealth
from ffcoach.advisors.lineup import LineupFinding
from ffcoach.model.deadlines import FixKind, FixPlan
from ffcoach.report.check_text import render_check

ET = ZoneInfo("America/New_York")
SUNDAY = dt.datetime(2025, 10, 5, 13, 0, tzinfo=dt.UTC)


def finding(**over):
    base = dict(
        kind="out",
        player_name="Hurt Guy",
        position="WR",
        lineup_slot="WR",
        nfl_team="KC",
        reason="Hurt Guy is listed OUT. Bench Guy is available and plays this week.",
        replacements=("Bench Guy",),
        kickoff=SUNDAY,
        locked=False,
        fix=FixPlan(FixKind.BENCH_SWAP, SUNDAY),
        locks_at=SUNDAY,
    )
    base.update(over)
    return LineupFinding(**base)


def result(**over):
    base = dict(
        week=5,
        week_source="espn",
        team_name="Team 11",
        findings=[],
        actionable=[],
        sources=(SourceHealth("ESPN league", 0.0, False),),
    )
    base.update(over)
    return CheckResult(**base)


def text(res, **kw):
    return "\n".join(render_check(res, ET, **kw))


def test_no_output_carries_an_ansi_escape():
    """UX rule 5. A colour-coded status is invisible to a screen reader."""
    f = finding()
    out = text(result(findings=[f], actionable=[f]))
    assert "\x1b" not in out


def test_an_all_clear_says_so_in_words():
    out = text(result())
    assert "All clear" in out


def test_an_unverified_run_never_reads_as_reassurance():
    """The whole point of C7: silence is not an all-clear."""
    out = text(result(blind_spots=("empty slot check skipped: no lineupSlotCounts",)))
    assert "All clear" not in out
    assert "could not see everything" in out
    assert "Could not check everything (1)" in out
    assert "lineupSlotCounts" in out


def test_every_finding_states_its_reason():
    f = finding()
    out = text(result(findings=[f], actionable=[f]))
    assert "listed OUT" in out


def test_a_finding_names_its_fix_verb_and_deadline():
    f = finding()
    out = text(result(findings=[f], actionable=[f]))
    assert "Swap by Sun Oct 5" in out


def test_a_locked_finding_says_it_is_too_late_rather_than_a_deadline():
    """D-011: reported, never dropped -- but not dressed up as actionable."""
    f = finding(locked=True)
    out = text(result(findings=[f], actionable=[]))
    assert "LOCKED, too late" in out
    assert "Swap by" not in out


def test_an_empty_slot_does_not_render_as_missing_data():
    f = finding(kind="empty_slot", player_name="", nfl_team="", lineup_slot="TE",
                reason="Your TE slot is empty.", replacements=())
    out = text(result(findings=[f], actionable=[f]))
    assert "no one in this slot" in out
    assert "()" not in out


def test_a_partly_locked_week_says_how_many_are_still_fixable():
    live, gone = finding(), finding(player_name="Late Guy", locked=True)
    out = text(result(findings=[live, gone], actionable=[live]))
    assert "2 to fix" in out
    assert "1 still fixable, 1 past the deadline" in out


def test_an_estimated_deadline_admits_it_is_estimated():
    f = finding(lock_is_estimated=True)
    out = text(result(findings=[f], actionable=[f]))
    assert "estimate" in out


def test_ir_candidates_are_offered_with_their_prerequisite():
    f = finding(replacements=(), ir_candidates=("Stashed Guy",))
    out = text(result(findings=[f], actionable=[f]))
    assert "Stashed Guy" in out
    assert "activate first" in out


def test_a_clean_week_still_names_the_next_deadline():
    """"Nothing is wrong" and "nothing is wrong yet" are different sentences."""
    out = text(result(next_lock=SUNDAY, waiver_deadline=SUNDAY))
    assert "Next slot freezes:" in out
    assert "Waivers next process:" in out


def test_source_ages_are_reported_in_human_units():
    out = text(result(sources=(SourceHealth("ESPN league", 0.0, False),
                               SourceHealth("NFL schedule", 7200.0, False))))
    assert "ESPN league live" in out
    assert "NFL schedule 2h old" in out


def test_no_dollar_sign_is_ever_emitted():
    """UX rule 3: the league uses waiver priority, not a budget."""
    f = finding()
    out = text(result(findings=[f], actionable=[f], blind_spots=("x",),
                      next_lock=SUNDAY, waiver_deadline=SUNDAY))
    assert "$" not in out


def test_the_league_name_heads_the_report_when_given():
    out = text(result(), league_name="Cronk Fantasy Football League")
    assert out.startswith("Cronk Fantasy Football League — week 5")


def test_a_pre_draft_run_explains_itself_rather_than_claiming_all_clear():
    out = text(result(pre_draft=True))
    assert "Draft has not happened yet" in out
    assert "All clear" not in out


def test_an_at_risk_finding_is_labelled_as_doubt_not_as_certainty():
    """The label is this tool's read; the reason carries ESPN's own word.

    Printing "QUESTIONABLE" as the label would put ESPN's designation in the
    column that everywhere else holds a conclusion, and the two are not the
    same claim.
    """
    lines = text(
        result(
            findings=[
                finding(
                    kind="at_risk",
                    reason="Still listed Questionable and his slot locks shortly.",
                )
            ]
        )
    )
    assert "RISK" in lines
    assert "Still listed Questionable" in lines
