"""The health payload: live state, and no secrets in it."""

import datetime as dt
import json

from ffcoach.config import new_topic, write_notify_config
from ffcoach.health import health_payload

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC)


def notify_file(tmp_path, name="notify.yaml", **extra):
    p = tmp_path / name
    write_notify_config(p, new_topic(), force=True)
    text = p.read_text()
    for key, value in extra.items():
        text = text.replace(f'{key}: ""', f'{key}: "{value}"', 1)
    p.write_text(text)
    return p


def log_file(tmp_path, *records):
    p = tmp_path / "runs.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records))
    return p


def run(hours_ago, ok=True, **extra):
    return {"at": (NOW - dt.timedelta(hours=hours_ago)).isoformat(),
            "command": "check", "ok": ok, **extra}


# --- the property that matters most ---


def test_no_secret_reaches_the_payload(tmp_path):
    """This JSON is served over the LAN under `serve --lan`, and is the thing
    someone screenshots when asking for help."""
    notify = notify_file(tmp_path, url="https://hc-ping.com/abc-123-secret")
    topic = notify.read_text().split('topic: "')[1].split('"')[0]

    blob = json.dumps(health_payload(log_file(tmp_path), notify, NOW))
    assert topic not in blob
    assert "hc-ping.com" not in blob
    assert "abc-123-secret" not in blob
    # ...but whether each is configured is exactly what the panel needs.
    payload = json.loads(blob)
    assert payload["alerts"]["configured"] is True
    assert payload["heartbeat"]["configured"] is True


def test_a_missing_notify_config_is_reported_not_swallowed(tmp_path):
    payload = health_payload(log_file(tmp_path), tmp_path / "absent.yaml", NOW)
    assert payload["alerts"]["configured"] is False
    assert "not found" in payload["alerts"]["reason"]


# --- unknown is not healthy ---


def test_an_undetermined_agent_state_stays_none(tmp_path):
    """`None` renders as unknown. A panel that says "yes" because it failed to
    ask is the failure this page exists to catch."""
    payload = health_payload(log_file(tmp_path), notify_file(tmp_path), NOW,
                             agent_loaded=None)
    assert payload["scheduler"]["loaded"] is None


def test_the_agent_state_is_carried_through_when_known(tmp_path):
    notify = notify_file(tmp_path)
    for value in (True, False):
        payload = health_payload(log_file(tmp_path), notify, NOW,
                                 agent_loaded=value)
        assert payload["scheduler"]["loaded"] is value


# --- last run vs last success ---


def test_the_last_run_and_the_last_success_are_both_reported(tmp_path):
    log = log_file(tmp_path, run(30), run(2, ok=False), run(1, ok=False))
    payload = health_payload(log, notify_file(tmp_path), NOW)
    assert payload["last_run"]["ok"] is False
    assert payload["last_success"]["age_seconds"] == 30 * 3600


def test_never_having_succeeded_is_null_rather_than_absent(tmp_path):
    log = log_file(tmp_path, run(1, ok=False))
    payload = health_payload(log, notify_file(tmp_path), NOW)
    assert payload["last_success"] is None


def test_an_empty_log_reports_no_run_rather_than_failing(tmp_path):
    payload = health_payload(log_file(tmp_path), notify_file(tmp_path), NOW)
    assert payload["last_run"] is None


def test_an_unparseable_timestamp_yields_an_unknown_age_not_a_crash(tmp_path):
    log = log_file(tmp_path, {"at": "not a date", "ok": True})
    payload = health_payload(log, notify_file(tmp_path), NOW)
    assert payload["last_run"]["age_seconds"] is None


# --- the watchdog, surfaced ---


def test_a_failing_installation_trips_the_watchdog_in_the_payload(tmp_path):
    log = log_file(tmp_path, run(0.1, ok=False), run(0.2, ok=False), run(0.3, ok=False))
    payload = health_payload(log, notify_file(tmp_path), NOW)
    assert payload["watchdog"]["tripped"] is True
    assert "3 runs in a row" in payload["watchdog"]["reason"]


def test_a_healthy_installation_does_not_trip_it(tmp_path):
    payload = health_payload(log_file(tmp_path, run(0.2)), notify_file(tmp_path), NOW)
    assert payload["watchdog"]["tripped"] is False


# --- the host guard, surfaced ---


def test_the_alerting_host_is_reported(tmp_path):
    notify = notify_file(tmp_path, scheduler_host="some-other-box")
    payload = health_payload(log_file(tmp_path), notify, NOW)
    assert payload["scheduler"]["host"] == "some-other-box"
    assert payload["scheduler"]["is_this_machine"] is False


def test_an_unrecorded_host_means_this_machine_may_alert(tmp_path):
    payload = health_payload(log_file(tmp_path), notify_file(tmp_path), NOW)
    assert payload["scheduler"]["host"] is None
    assert payload["scheduler"]["is_this_machine"] is True


def test_setup_steps_travel_into_the_payload(tmp_path):
    payload = health_payload(
        log_file(tmp_path), notify_file(tmp_path), NOW,
        setup_steps=[(False, "espn.yaml", "copy espn.example.yaml")],
    )
    assert payload["setup"] == [
        {"done": False, "what": "espn.yaml", "fix": "copy espn.example.yaml"}
    ]


def test_the_payload_is_json_serialisable(tmp_path):
    json.dumps(health_payload(log_file(tmp_path, run(1)), notify_file(tmp_path), NOW))
