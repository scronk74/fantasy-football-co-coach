from ffcoach.cache import Cache


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make(tmp_path, clock):
    return Cache(tmp_path / "c.sqlite3", now=clock)


def test_returns_none_for_missing_key(tmp_path):
    assert make(tmp_path, FakeClock()).get("nope") is None


def test_round_trips_a_value(tmp_path):
    c = make(tmp_path, FakeClock())
    c.set("k", "hello", ttl_seconds=60)
    assert c.get("k") == "hello"


def test_expires_after_ttl(tmp_path):
    clock = FakeClock()
    c = make(tmp_path, clock)
    c.set("k", "hello", ttl_seconds=60)
    clock.advance(59)
    assert c.get("k") == "hello"
    clock.advance(2)
    assert c.get("k") is None


def test_get_stale_survives_expiry(tmp_path):
    clock = FakeClock()
    c = make(tmp_path, clock)
    c.set("k", "hello", ttl_seconds=10)
    clock.advance(500)
    assert c.get("k") is None
    value, age = c.get_stale("k")
    assert value == "hello"
    assert age == 500


def test_set_overwrites_and_resets_age(tmp_path):
    clock = FakeClock()
    c = make(tmp_path, clock)
    c.set("k", "old", ttl_seconds=10)
    clock.advance(5)
    c.set("k", "new", ttl_seconds=10)
    assert c.get("k") == "new"
    assert c.age_seconds("k") == 0


def test_persists_across_instances(tmp_path):
    clock = FakeClock()
    make(tmp_path, clock).set("k", "durable", ttl_seconds=60)
    assert make(tmp_path, clock).get("k") == "durable"


def test_age_of_missing_key_is_none(tmp_path):
    assert make(tmp_path, FakeClock()).age_seconds("nope") is None
