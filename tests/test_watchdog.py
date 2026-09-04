"""E3: noticing that the tool itself has stopped working.

D-023's case is exact: expired ESPN cookies produce no alert, which is
indistinguishable from "nothing is wrong". Every other silent failure has the
same shape -- a check that errors sends nothing, and sending nothing is what a
clean week looks like.

This module answers the on-host half. It cannot answer the off-host half: a
process on a dead machine reports nothing about the machine being dead. That
is `notify/heartbeat.py`, and the split is deliberate rather than incidental.
"""

import datetime as dt

from ffcoach.watchdog import WatchdogConfig, assess

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC)
CONF = WatchdogConfig()


def run(hours_ago, ok=True):
    return {"at": (NOW - dt.timedelta(hours=hours_ago)).isoformat(), "ok": ok}


# --- the healthy cases, which must stay silent ---


def test_a_recent_success_trips_nothing():
    assert assess([run(0.2)], NOW, CONF) is None


def test_one_failure_after_a_recent_success_is_not_an_outage():
    """Transient failures happen. A single one is not evidence of anything."""
    assert assess([run(0.1, ok=False), run(0.3)], NOW, CONF) is None


def test_two_failures_still_wait():
    assert assess([run(0.1, ok=False), run(0.2, ok=False), run(0.3)], NOW, CONF) is None


def test_an_empty_log_trips_nothing():
    """Nothing has ever run. That is a fresh install, not an outage."""
    assert assess([], NOW, CONF) is None


# --- the case D-023 names ---


def test_three_consecutive_failures_trip_it():
    """Expired cookies: launchd fires, the check errors, nothing is sent.

    The count is what makes this unambiguous. It needs no assumption about how
    often the scheduler runs, which is the weakness of a pure time threshold.
    """
    records = [run(0.1, ok=False), run(0.3, ok=False), run(0.5, ok=False), run(1.0)]
    alert = assess(records, NOW, CONF)
    assert alert is not None
    assert alert.consecutive_failures == 3
    assert "3 runs in a row" in alert.reason


def test_the_failure_streak_stops_at_the_last_success():
    records = [run(0.1, ok=False), run(0.2, ok=False), run(0.3), run(0.4, ok=False)]
    assert assess(records, NOW, CONF) is None


# --- the silence case ---


def test_a_long_silence_trips_it_even_with_no_failures():
    """A scheduler that was unloaded logs nothing at all -- no failures to count."""
    alert = assess([run(20)], NOW, CONF)
    assert alert is not None
    assert alert.consecutive_failures == 0
    assert "20h" in alert.reason or "20 h" in alert.reason


def test_silence_is_measured_from_the_last_success_not_the_last_run():
    """A machine erroring every fifteen minutes since Thursday is not alive.

    Measuring from the last *run* would read constant failure as health, which
    is the exact mistake `doctor` was built to avoid.
    """
    records = [run(h, ok=False) for h in (0.1, 0.2, 0.3)] + [run(30)]
    alert = assess(records, NOW, CONF)
    assert alert is not None
    assert alert.since_success == dt.timedelta(hours=30)


def test_a_log_with_no_success_at_all_reports_that_plainly():
    alert = assess([run(20, ok=False), run(25, ok=False)], NOW, CONF)
    assert alert is not None
    assert alert.last_success is None
    assert "never" in alert.reason


def test_the_silence_threshold_is_configurable():
    """The right value depends on the schedule, which this module cannot know."""
    generous = WatchdogConfig(max_silence=dt.timedelta(hours=48))
    assert assess([run(20)], NOW, generous) is None


# --- the alert must not repeat every fifteen minutes ---


def test_the_key_is_stable_while_the_outage_persists():
    a = assess([run(13)], NOW, CONF)
    b = assess([run(13.5)], NOW + dt.timedelta(minutes=30), CONF)
    assert a.key == b.key


def test_the_key_escalates_as_the_outage_lengthens():
    """One alert per threshold crossed, so a long outage is re-raised without
    being repeated every scheduler cycle."""
    short = assess([run(13)], NOW, CONF)
    long = assess([run(30)], NOW, CONF)
    assert short.key != long.key


def test_a_failure_streak_and_a_silence_are_different_alerts():
    streak = assess([run(0.1, ok=False)] * 3 + [run(1)], NOW, CONF)
    silence = assess([run(20)], NOW, CONF)
    assert streak.key != silence.key


# --- corrupt or partial data must not manufacture an outage ---


def test_a_record_with_no_timestamp_is_skipped_rather_than_trusted():
    alert = assess([{"ok": True}, run(0.2)], NOW, CONF)
    assert alert is None


def test_an_unparseable_timestamp_does_not_crash_or_trip():
    assert assess([{"at": "not a date", "ok": True}, run(0.2)], NOW, CONF) is None


def test_a_naive_timestamp_is_read_as_utc_rather_than_raising():
    """Old lines, or a hand-edited file. Comparing naive to aware raises."""
    naive = {"at": (NOW - dt.timedelta(hours=1)).replace(tzinfo=None).isoformat(),
             "ok": True}
    assert assess([naive], NOW, CONF) is None
