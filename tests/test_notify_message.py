"""What a `CheckResult` becomes on a lock screen.

The governing rule: **only something the user can still act on is allowed to
interrupt**. A clean week sends nothing, and that silence is the system
working (D-016).
"""

import datetime as dt
from zoneinfo import ZoneInfo

from ffcoach.advisors.lineup import LineupFinding
from ffcoach.check import CheckResult, SourceHealth
from ffcoach.model.deadlines import FixKind, FixPlan
from ffcoach.notify.message import notification_for

ET = ZoneInfo("America/New_York")
SUNDAY = dt.datetime(2025, 10, 5, 17, 0, tzinfo=dt.UTC)  # 1:00 PM ET
FRIDAY = dt.datetime(2025, 10, 3, 15, 0, tzinfo=dt.UTC)  # 11:00 AM ET


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


# --- what must never be sent ---


def test_a_clean_week_sends_nothing():
    """Zero interrupts in a clean week is the system working, not a bug."""
    assert notification_for(result(), ET) is None


def test_a_pre_draft_run_sends_nothing():
    assert notification_for(result(pre_draft=True), ET) is None


def test_findings_that_are_all_locked_send_nothing():
    """D-011 keeps them in the report. Nothing can be done, so nothing buzzes."""
    gone = finding(locked=True)
    assert notification_for(result(findings=[gone], actionable=[]), ET) is None


def test_blind_spots_alone_do_not_send():
    """Deliberate, and the reason is recorded as D-057.

    A stale ESPN fetch can persist for every run of a day. Without D3's repeat
    policy, sending on blind spots alone is a spam machine -- and a channel you
    mute is worse than one that occasionally stays quiet. They ride *inside* an
    alert instead, so if you are being told something anyway you also learn
    what was uncertain.
    """
    assert notification_for(result(blind_spots=("ESPN league is stale",)), ET) is None


# --- what is sent ---


def test_one_actionable_finding_interrupts():
    f = finding()
    note = notification_for(result(findings=[f], actionable=[f]), ET)
    assert note is not None
    assert note.tier == "interrupt"
    assert note.is_interrupt


def test_the_title_counts_the_fixes_and_names_the_week():
    f = finding()
    note = notification_for(result(findings=[f], actionable=[f]), ET)
    assert "1 lineup fix" in note.title
    assert "week 5" in note.title


def test_the_title_pluralizes():
    a, b = finding(), finding(player_name="Other Guy")
    note = notification_for(result(findings=[a, b], actionable=[a, b]), ET)
    assert "2 lineup fixes" in note.title


def test_every_line_states_the_player_the_problem_and_the_deadline():
    """UX rule 4 survives the trip to a phone: no unexplained flags."""
    f = finding()
    note = notification_for(result(findings=[f], actionable=[f]), ET)
    assert "Hurt Guy" in note.body
    assert "OUT" in note.body
    assert "Swap by" in note.body
    assert "Sun 1:00 PM" in note.body


def test_the_replacement_is_named_so_the_fix_needs_no_second_screen():
    f = finding()
    note = notification_for(result(findings=[f], actionable=[f]), ET)
    assert "Bench Guy" in note.body


def test_a_claim_says_so_rather_than_implying_a_swap():
    """D-046: the kind of fix comes before the time."""
    f = finding(replacements=(), fix=FixPlan(FixKind.WAIVER_CLAIM, FRIDAY))
    note = notification_for(result(findings=[f], actionable=[f]), ET)
    assert "Claim by Fri 11:00 AM" in note.body


def test_an_empty_slot_reads_as_a_slot_not_a_missing_player():
    f = finding(kind="empty_slot", player_name="", nfl_team="", lineup_slot="TE",
                reason="Your TE slot is empty.", replacements=())
    note = notification_for(result(findings=[f], actionable=[f]), ET)
    assert "TE slot is empty" in note.body
    assert "()" not in note.body


def test_locked_findings_are_left_out_of_the_message_entirely():
    live, gone = finding(), finding(player_name="Late Guy", locked=True)
    note = notification_for(result(findings=[live, gone], actionable=[live]), ET)
    assert "Late Guy" not in note.body
    assert "1 lineup fix" in note.title


def test_a_long_list_is_truncated_with_a_pointer_to_the_full_check():
    """A lock screen shows a few lines. Ten findings truncated silently would
    hide the ones that did not fit."""
    many = [finding(player_name=f"Guy {i}") for i in range(9)]
    note = notification_for(result(findings=many, actionable=many), ET)
    assert "9 lineup fixes" in note.title
    assert "more" in note.body
    assert "ffcoach check" in note.body


def test_blind_spots_ride_along_inside_an_alert_that_was_sending_anyway():
    f = finding()
    note = notification_for(
        result(findings=[f], actionable=[f],
               blind_spots=("ESPN league is stale; serving a cached copy",)),
        ET,
    )
    assert "could not check" in note.body.lower()
    assert "stale" in note.body


def test_no_dollar_sign_reaches_a_phone():
    """UX rule 3."""
    f = finding()
    note = notification_for(
        result(findings=[f], actionable=[f], blind_spots=("x",)), ET
    )
    assert "$" not in note.title + note.body


def test_an_at_risk_finding_reaches_the_phone_as_its_own_kind():
    """The alert E6 exists for: a decision, ninety minutes before the lock."""
    note = notification_for(
        result(
            findings=[finding(kind="at_risk")],
            actionable=[finding(kind="at_risk")],
        ),
        ET,
    )
    assert "RISK" in note.body
    assert note.tier == "interrupt"
