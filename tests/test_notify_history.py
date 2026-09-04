"""Alert history: the memory that makes "two strikes" mean anything."""

from ffcoach.cache import Cache
from ffcoach.notify.history import AlertHistory


def test_an_unseen_key_has_no_count(tmp_path):
    h = AlertHistory(tmp_path / "a.sqlite3")
    assert h.counts() == {}


def test_recording_counts_one_per_key(tmp_path):
    h = AlertHistory(tmp_path / "a.sqlite3")
    h.record(["5:out:WR:Hurt Guy"])
    assert h.counts() == {"5:out:WR:Hurt Guy": 1}


def test_recording_the_same_key_twice_increments_rather_than_overwrites(tmp_path):
    h = AlertHistory(tmp_path / "a.sqlite3")
    h.record(["k"])
    h.record(["k"])
    assert h.counts()["k"] == 2


def test_counts_survive_a_new_connection(tmp_path):
    """The scheduler runs the check as a fresh process every time."""
    path = tmp_path / "a.sqlite3"
    AlertHistory(path).record(["k"])
    assert AlertHistory(path).counts()["k"] == 1


def test_history_shares_the_cache_file_without_disturbing_it(tmp_path):
    """D-041: one storage decision. The tables must not collide."""
    path = tmp_path / "shared.sqlite3"
    cache = Cache(path)
    cache.set("adp:ppr", "payload", 3600)
    AlertHistory(path).record(["k"])
    assert cache.get("adp:ppr") == "payload"
    assert AlertHistory(path).counts() == {"k": 1}


def test_an_alert_record_never_expires(tmp_path):
    """Cache entries expire by design; an alert record must not.

    A record that quietly aged out would hand an unfixed problem a fresh pair
    of strikes, which is the spam this whole policy exists to prevent.
    """
    path = tmp_path / "a.sqlite3"
    clock = [1000.0]
    h = AlertHistory(path, now=lambda: clock[0])
    h.record(["k"])
    clock[0] += 60 * 60 * 24 * 365
    assert AlertHistory(path, now=lambda: clock[0]).counts()["k"] == 1


def test_forget_drops_one_key(tmp_path):
    h = AlertHistory(tmp_path / "a.sqlite3")
    h.record(["a", "b"])
    h.forget("a")
    assert set(h.counts()) == {"b"}


def test_last_sent_records_when(tmp_path):
    h = AlertHistory(tmp_path / "a.sqlite3", now=lambda: 1234.0)
    h.record(["k"])
    assert h.last_sent("k") == 1234.0
    assert h.last_sent("never") is None


def test_records_carry_when_the_last_alert_went_out(tmp_path):
    """The repeat policy needs the timestamp, not only the count: a reminder
    must not fire on the scheduler run right after the first alert."""
    import datetime as dt

    h = AlertHistory(tmp_path / "a.sqlite3", now=lambda: 1_700_000_000.0)
    h.record(["k"])
    record = AlertHistory(tmp_path / "a.sqlite3").records()["k"]
    assert record.count == 1
    assert record.last_sent == dt.datetime.fromtimestamp(1_700_000_000.0, dt.UTC)


def test_records_are_timezone_aware(tmp_path):
    """A naive timestamp compared against an aware `now` raises at runtime."""
    h = AlertHistory(tmp_path / "a.sqlite3")
    h.record(["k"])
    assert h.records()["k"].last_sent.tzinfo is not None
