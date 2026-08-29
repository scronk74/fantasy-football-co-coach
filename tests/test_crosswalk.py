from pathlib import Path

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.sources.crosswalk import (
    CACHE_KEY,
    CrosswalkUnavailable,
    fetch_crosswalk,
    parse_crosswalk,
)

FIXTURE = Path(__file__).parent / "fixtures" / "db_playerids.csv"


@pytest.fixture
def raw():
    return FIXTURE.read_text()


@pytest.fixture
def crosswalk(raw):
    return parse_crosswalk(raw)


def client_returning(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_produces_entries(crosswalk):
    assert crosswalk.entries
    first = crosswalk.entries[0]
    assert first.name
    assert first.position in ("QB", "RB", "WR", "TE", "K")


def test_parse_maps_pk_position_to_k(crosswalk):
    kickers = [e for e in crosswalk.entries if e.position == "K"]
    assert kickers
    assert all(e.position != "PK" for e in crosswalk.entries)


def test_parse_treats_na_string_as_missing(crosswalk):
    # The live file uses the literal "NA" for absent ids. Taken at face
    # value it would collide every such player onto one bogus key.
    for entry in crosswalk.entries:
        assert "NA" not in [v for v in entry.ids.values() if v is not None]


def test_parse_rejects_a_file_without_a_name_column():
    with pytest.raises(CrosswalkUnavailable, match="parse"):
        parse_crosswalk("alpha,beta\n1,2\n")


def test_resolve_matches_an_exact_name(crosswalk):
    entry, confidence = crosswalk.resolve("Bijan Robinson", "RB", "ATL")
    assert entry is not None
    assert entry.name == "Bijan Robinson"
    assert confidence == "exact"


def test_resolve_uses_the_curated_alias_for_nicknames(crosswalk):
    # merge_name carries "andy borregales" for the formal "Andres Borregales".
    entry, confidence = crosswalk.resolve("Andy Borregales", "K", "NE")
    assert entry is not None
    assert entry.name == "Andres Borregales"
    assert confidence == "exact"


def test_resolve_falls_back_to_surname_and_flags_it_fuzzy(crosswalk):
    entry, confidence = crosswalk.resolve("Kenny Gainwell", "RB", "PIT")
    assert entry is not None
    assert entry.name == "Kenneth Gainwell"
    assert confidence == "fuzzy"


def test_resolve_disambiguates_junior_from_father_by_modern_id(crosswalk):
    # normalize_name strips the "Jr." suffix, so father and son collapse to
    # one key. Only the son carries a Sleeper id.
    entry, confidence = crosswalk.resolve("Marvin Harrison Jr.", "WR", "ARI")
    assert entry is not None
    assert entry.ids["sleeper_id"] == "11628"
    assert confidence == "exact"


def test_resolve_returns_unresolved_for_an_unknown_player(crosswalk):
    entry, confidence = crosswalk.resolve("Nobody At All", "WR", "ATL")
    assert entry is None
    assert confidence == "unresolved"


def test_resolve_never_matches_a_team_defense(crosswalk):
    # Team defenses are absent from this file entirely.
    entry, confidence = crosswalk.resolve("Ravens", "DEF", "BAL")
    assert entry is None
    assert confidence == "unresolved"


def test_by_id_looks_up_each_platform_id_space(crosswalk):
    entry, _ = crosswalk.resolve("Bijan Robinson", "RB", "ATL")
    for field in ("sleeper_id", "espn_id", "gsis_id", "mfl_id"):
        value = entry.ids.get(field)
        if value:
            assert crosswalk.by_id(field, value) is entry


def test_by_id_returns_none_for_an_unknown_id(crosswalk):
    assert crosswalk.by_id("sleeper_id", "does-not-exist") is None


def test_fetch_hits_network_once_then_serves_cache(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning(raw, calls=calls)
    a = fetch_crosswalk(cache, client=client)
    b = fetch_crosswalk(cache, client=client)
    assert a == b == raw
    assert len(calls) == 1


def test_fetch_falls_back_to_stale_cache_on_failure(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_crosswalk(cache, client=client_returning(raw))
    cache.set(CACHE_KEY, raw, ttl_seconds=-1)
    got = fetch_crosswalk(cache, client=client_returning("", status=500))
    assert got == raw


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(CrosswalkUnavailable, match="500"):
        fetch_crosswalk(cache, client=client_returning("", status=500))
