"""E1: one JSON line per run, so a quiet Sunday can be diagnosed.

Nothing recorded anything before this. A silent Sunday morning was
indistinguishable between "your lineup is clean" and "the cookies expired at
6am and every run since has been erroring" -- which is the same failure the
dead-man's switch (E3) exists to catch, and E3 cannot be built without the
question "when did a run last succeed?" having an answer.
"""

import datetime as dt
import json

import pytest

from ffcoach.runlog import RunLog


def log(tmp_path, **kw):
    return RunLog(tmp_path / "runs.jsonl", **kw)


def test_a_run_appends_exactly_one_line(tmp_path):
    rl = log(tmp_path)
    rl.append({"command": "check", "ok": True})
    rl.append({"command": "check", "ok": True})
    assert len(rl.path.read_text().strip().splitlines()) == 2


def test_each_line_is_valid_json_on_its_own(tmp_path):
    """Greppable at 9am on a Sunday means line-oriented, not a JSON array."""
    rl = log(tmp_path)
    rl.append({"command": "check", "findings": 2})
    for line in rl.path.read_text().strip().splitlines():
        assert json.loads(line)["command"] == "check"


def test_every_record_is_stamped_even_if_the_caller_forgets(tmp_path):
    rl = log(tmp_path, now=lambda: dt.datetime(2026, 9, 4, 12, 0, tzinfo=dt.UTC))
    rl.append({"command": "check"})
    record = rl.tail(1)[0]
    assert record["at"] == "2026-09-04T12:00:00+00:00"


def test_the_file_and_its_parent_are_created_on_demand(tmp_path):
    rl = RunLog(tmp_path / "nested" / "deep" / "runs.jsonl")
    rl.append({"command": "check"})
    assert rl.path.exists()


# --- reading it back ---


def test_tail_returns_the_most_recent_first(tmp_path):
    rl = log(tmp_path)
    for i in range(5):
        rl.append({"command": "check", "n": i})
    assert [r["n"] for r in rl.tail(3)] == [4, 3, 2]


def test_tail_of_an_absent_file_is_empty_rather_than_an_error(tmp_path):
    """`doctor` runs before the first check ever has."""
    assert log(tmp_path).tail(5) == []


def test_a_corrupt_line_does_not_poison_the_whole_log(tmp_path):
    """A half-written line from a killed process must not blind `doctor`."""
    rl = log(tmp_path)
    rl.append({"command": "check", "n": 1})
    with rl.path.open("a") as fh:
        fh.write('{"command": "check", "n"\n')
    rl.append({"command": "check", "n": 2})
    assert [r["n"] for r in rl.tail(5)] == [2, 1]


def test_last_success_skips_failed_runs(tmp_path):
    """The question E3 asks. A failed run is not a heartbeat."""
    rl = log(tmp_path, now=lambda: dt.datetime(2026, 9, 4, 12, 0, tzinfo=dt.UTC))
    rl.append({"command": "check", "ok": True, "n": 1})
    rl.append({"command": "check", "ok": False, "n": 2})
    assert rl.last_success()["n"] == 1


def test_last_success_is_none_when_nothing_has_ever_worked(tmp_path):
    rl = log(tmp_path)
    rl.append({"command": "check", "ok": False})
    assert rl.last_success() is None


# --- redaction: the log is the thing people paste into issues ---


def test_a_secret_never_reaches_the_log(tmp_path):
    """The ntfy topic IS the credential, and so are the ESPN cookies."""
    rl = log(tmp_path, secrets=("my-secret-topic",))
    rl.append({"command": "check", "error": "failed to POST to my-secret-topic"})
    text = rl.path.read_text()
    assert "my-secret-topic" not in text
    assert "***" in text


def test_redaction_reaches_nested_values(tmp_path):
    rl = log(tmp_path, secrets=("SWID-123",))
    rl.append({"sources": [{"name": "ESPN", "error": "bad cookie SWID-123"}]})
    assert "SWID-123" not in rl.path.read_text()


def test_an_empty_secret_does_not_redact_everything(tmp_path):
    """A missing credential is `""`, and scrubbing it would eat the whole line."""
    rl = log(tmp_path, secrets=("", None))
    rl.append({"command": "check"})
    assert rl.tail(1)[0]["command"] == "check"


# --- a logging failure must never take down the check ---


def test_a_write_failure_is_reported_but_does_not_raise(tmp_path, capsys):
    """The check succeeding matters more than the line about it."""
    rl = RunLog(tmp_path / "runs.jsonl")
    rl.path.parent.chmod(0o500)
    try:
        rl.append({"command": "check"})  # must not raise
    finally:
        rl.path.parent.chmod(0o700)
    assert "could not write" in capsys.readouterr().err


def test_an_unserializable_value_is_stringified_rather_than_dropped(tmp_path):
    """A datetime in the record must not silently lose the whole line."""
    rl = log(tmp_path)
    rl.append({"deadline": dt.datetime(2026, 9, 9, 20, 20, tzinfo=dt.UTC)})
    assert "2026-09-09" in rl.tail(1)[0]["deadline"]
