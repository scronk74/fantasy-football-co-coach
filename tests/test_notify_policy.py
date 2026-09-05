"""D3: when a real problem is allowed to buzz your phone a second time.

Two rules, and the interesting part of each is its exception.

Quiet hours defer rather than drop -- but they **yield to a deadline**, because
holding an alert past the moment it could have been acted on is the exact
failure this product exists to prevent.

Two strikes is a hard cap -- but the second strike is spent near the deadline
rather than on the next run, because a reminder fifteen minutes after the first
alert is noise and a reminder ninety minutes before kickoff is the product.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from ffcoach.advisors.lineup import LineupFinding
from ffcoach.model.deadlines import FixKind, FixPlan
from ffcoach.config import AlertPrefs
from ffcoach.notify.policy import (
    AlertRecord,
    QuietHours,
    alert_key,
    allowed_by_prefs,
    decide,
)

ET = ZoneInfo("America/New_York")


def at(month, day, hour, minute=0):
    return dt.datetime(2025, month, day, hour, minute, tzinfo=ET)


SUNDAY_1PM = at(10, 5, 13)


def finding(**over):
    base = dict(
        kind="out",
        player_name="Hurt Guy",
        position="WR",
        lineup_slot="WR",
        nfl_team="KC",
        reason="listed OUT",
        replacements=("Bench Guy",),
        kickoff=SUNDAY_1PM,
        locked=False,
        fix=FixPlan(FixKind.BENCH_SWAP, SUNDAY_1PM),
        locks_at=SUNDAY_1PM,
    )
    base.update(over)
    return LineupFinding(**base)


QUIET = QuietHours()  # 23:00 -> 08:00 ET, per D-018


def sent(decision):
    return [f.player_name for f in decision.send]


# --- the key that identifies "the same problem" across runs ---


def test_the_same_problem_in_the_same_week_has_the_same_key():
    assert alert_key(5, finding()) == alert_key(5, finding())


def test_the_same_problem_in_a_different_week_is_a_different_problem():
    """A bye in week 5 and a bye in week 12 both deserve their own alerts."""
    assert alert_key(5, finding()) != alert_key(12, finding())


def test_two_empty_slots_of_the_same_position_do_not_collide():
    """Two empty WR slots are two problems, and one key would silence the second.

    Nothing on a `LineupFinding` distinguishes them -- an empty slot has no
    player, no NFL team, and the same slot name -- so the ordinal is assigned
    across the batch, which is the only place the distinction exists.
    """
    a = finding(kind="empty_slot", player_name="", nfl_team="", lineup_slot="WR")
    b = finding(kind="empty_slot", player_name="", nfl_team="", lineup_slot="WR")
    d = decide([a, b], week=5, records={}, now=at(10, 1, 9), quiet=QUIET, tz=ET)
    assert len(d.send) == 2
    assert len(set(d.keys_sent)) == 2


def test_an_ordinal_only_applies_to_the_repeats():
    """The first of a kind keeps the plain key, so history stays comparable
    when a duplicate appears or disappears later in the season."""
    f = finding()
    d = decide([f], week=5, records={}, now=at(10, 1, 9), quiet=QUIET, tz=ET)
    assert d.keys_sent == (alert_key(5, f),)


def test_a_different_player_in_the_same_slot_is_a_different_problem():
    a, b = finding(), finding(player_name="Other Guy")
    assert alert_key(5, a) != alert_key(5, b)


# --- strike one: anything new goes out ---


def test_a_problem_never_alerted_is_sent():
    d = decide([finding()], week=5, records={}, now=at(10, 1, 9), quiet=QUIET, tz=ET)
    assert sent(d) == ["Hurt Guy"]


def test_sending_is_reported_with_the_key_so_the_caller_can_record_it():
    f = finding()
    d = decide([f], week=5, records={}, now=at(10, 1, 9), quiet=QUIET, tz=ET)
    assert d.keys_sent == (alert_key(5, f),)


# --- strike two: held until it is useful, then spent ---


def test_a_second_alert_is_held_while_the_deadline_is_far_away():
    """A reminder fifteen minutes after the first one is noise."""
    f = finding()
    d = decide([f], week=5, records={alert_key(5, f): AlertRecord(1)}, now=at(10, 1, 9),
               quiet=QUIET, tz=ET)
    assert d.send == []
    assert any("closer to the deadline" in r for r in d.held)


def test_a_second_alert_goes_out_inside_the_last_call_window():
    """Ninety minutes before kickoff, still unfixed, is the whole product."""
    f = finding()
    d = decide([f], week=5, records={alert_key(5, f): AlertRecord(1)}, now=at(10, 5, 11, 30),
               quiet=QUIET, tz=ET)
    assert sent(d) == ["Hurt Guy"]


def test_a_third_alert_never_goes_out():
    """D-019: told twice is told. The roster is the acknowledgment."""
    f = finding()
    d = decide([f], week=5, records={alert_key(5, f): AlertRecord(2)}, now=at(10, 5, 11, 30),
               quiet=QUIET, tz=ET)
    assert d.send == []
    assert any("twice" in r for r in d.held)


def test_a_problem_with_no_known_deadline_still_gets_its_first_alert():
    """An unknown deadline must not become an excuse to say nothing."""
    f = finding(fix=FixPlan(FixKind.UNKNOWN, None))
    d = decide([f], week=5, records={}, now=at(10, 1, 9), quiet=QUIET, tz=ET)
    assert sent(d) == ["Hurt Guy"]


def test_a_reminder_with_no_known_deadline_is_never_triggered_by_the_window():
    """No deadline means no last call. It gets one alert, not two."""
    f = finding(fix=FixPlan(FixKind.UNKNOWN, None))
    d = decide([f], week=5, records={alert_key(5, f): AlertRecord(1)}, now=at(10, 1, 9),
               quiet=QUIET, tz=ET)
    assert d.send == []


# --- quiet hours: deferred, not dropped ---


def test_quiet_hours_hold_an_alert_whose_deadline_is_still_ahead():
    f = finding()
    d = decide([f], week=5, records={}, now=at(10, 1, 2), quiet=QUIET, tz=ET)
    assert d.send == []
    assert any("08:00" in r for r in d.held)


def test_a_held_alert_goes_out_once_quiet_hours_end():
    """Deferred, not dropped: the next run after 08:00 sends it.

    No queue is needed -- the problem is still on the roster, so the check
    finds it again. That is D-019's "the roster is the acknowledgment" applied
    to deferral as well as to repeats.
    """
    f = finding()
    d = decide([f], week=5, records={}, now=at(10, 1, 8, 1), quiet=QUIET, tz=ET)
    assert sent(d) == ["Hurt Guy"]


def test_quiet_hours_yield_to_a_deadline_inside_them():
    """The exception that matters.

    A Monday-night game locks at 20:15, but a waiver claim can process at 03:00
    in a league configured that way. Holding until 08:00 would deliver the
    alert after the only moment it could have been acted on -- silence that
    looks exactly like a clean week.
    """
    f = finding(fix=FixPlan(FixKind.WAIVER_CLAIM, at(10, 1, 3)))
    d = decide([f], week=5, records={}, now=at(10, 1, 2), quiet=QUIET, tz=ET)
    assert sent(d) == ["Hurt Guy"]


def test_quiet_hours_do_not_burn_a_strike():
    """A held alert has not been sent, so it must not count as one.

    Counting it would silently spend strike one on a message nobody received.
    """
    f = finding()
    d = decide([f], week=5, records={}, now=at(10, 1, 2), quiet=QUIET, tz=ET)
    assert d.keys_sent == ()


def test_quiet_hours_wrap_past_midnight():
    for hour in (23, 0, 3, 7):
        assert QUIET.covers(at(10, 1, hour), ET), hour
    for hour in (8, 12, 22):
        assert not QUIET.covers(at(10, 1, hour), ET), hour


def test_quiet_hours_can_be_switched_off_entirely():
    off = QuietHours(enabled=False)
    f = finding()
    d = decide([f], week=5, records={}, now=at(10, 1, 2), quiet=off, tz=ET)
    assert sent(d) == ["Hurt Guy"]


# --- mixed batches ---


def test_a_reminder_waits_for_air_after_the_first_alert():
    """Found by a CLI test, not by reasoning.

    When a problem is first seen *inside* the last-call window, nothing stopped
    the reminder firing on the very next scheduler run -- two alerts fifteen
    minutes apart, then silence for the three hours that mattered.
    """
    f = finding()
    just_now = at(10, 5, 11, 20)
    d = decide([f], week=5,
               records={alert_key(5, f): AlertRecord(1, last_sent=just_now)},
               now=at(10, 5, 11, 30), quiet=QUIET, tz=ET)
    assert d.send == []
    assert any("only just alerted" in r for r in d.held)


def test_a_reminder_goes_out_once_enough_time_has_passed():
    f = finding()
    d = decide([f], week=5,
               records={alert_key(5, f): AlertRecord(1, last_sent=at(10, 5, 10, 0))},
               now=at(10, 5, 11, 30), quiet=QUIET, tz=ET)
    assert sent(d) == ["Hurt Guy"]


def test_a_batch_sends_the_new_and_holds_the_exhausted():
    fresh = finding(player_name="Fresh Guy")
    done = finding(player_name="Done Guy")
    d = decide([fresh, done], week=5, records={alert_key(5, done): AlertRecord(2)},
               now=at(10, 1, 9), quiet=QUIET, tz=ET)
    assert sent(d) == ["Fresh Guy"]
    assert len(d.held) == 1


# --- D4: what the user agreed to be interrupted about --------------------
#
# This runs *before* `decide`, and the order is the point: a kind you switched
# off must not spend a strike on its way to being suppressed.


def test_by_default_everything_is_allowed_through():
    findings = [finding(), finding(kind="bye", player_name="Bye Guy")]
    kept, held = allowed_by_prefs(findings, AlertPrefs(), at(10, 3, 11))
    assert kept == findings
    assert held == ()


def test_a_switched_off_kind_does_not_send():
    findings = [finding(), finding(kind="bye_next_week", player_name="Later Guy")]
    prefs = AlertPrefs(disabled_kinds=frozenset({"bye_next_week"}))
    kept, held = allowed_by_prefs(findings, prefs, at(10, 3, 11))
    assert [f.player_name for f in kept] == ["Hurt Guy"]
    assert len(held) == 1
    assert "switched off" in held[0]


def test_every_suppression_says_why():
    """The rule the whole module lives by: a message you did not get needs a
    visible cause, or the next silent week is unexplainable."""
    prefs = AlertPrefs(disabled_kinds=frozenset({"out"}))
    _, held = allowed_by_prefs([finding()], prefs, at(10, 3, 11))
    assert "Hurt Guy" in held[0]


def test_a_mute_holds_everything_and_names_when_it_lifts():
    prefs = AlertPrefs(mute_until=at(10, 5, 9))
    kept, held = allowed_by_prefs([finding(), finding()], prefs, at(10, 3, 11))
    assert kept == []
    assert len(held) == 1 and "muted until" in held[0]


def test_a_lapsed_mute_stops_holding_anything():
    prefs = AlertPrefs(mute_until=at(10, 3, 10))
    kept, _ = allowed_by_prefs([finding()], prefs, at(10, 3, 11))
    assert len(kept) == 1


def test_a_switched_off_kind_never_reaches_decide_and_so_spends_no_strike():
    """The reason D4 runs first. If a preference could consume a strike, a
    kind switched off in September would arrive with none left in November."""
    prefs = AlertPrefs(disabled_kinds=frozenset({"out"}))
    now = at(10, 3, 11)
    kept, _ = allowed_by_prefs([finding()], prefs, now)
    plan = decide(kept, 5, {}, now, QuietHours(enabled=False), ET)
    assert plan.keys_sent == ()
