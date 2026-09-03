import json
from pathlib import Path

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.sources.ffcalc import (
    AdpUnavailable,
    _cache_key,
    fetch_adp,
    parse_adp,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ffc_ppr_12.json"


@pytest.fixture
def raw():
    return FIXTURE.read_text()


def client_returning(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_produces_players(raw):
    players = parse_adp(raw)
    assert players
    first = players[0]
    assert first.name
    assert first.position in ("QB", "RB", "WR", "TE", "K", "DEF")
    assert first.adp > 0
    assert first.stdev >= 0


def test_parse_sorts_by_adp(raw):
    players = parse_adp(raw)
    assert players == sorted(players, key=lambda p: p.adp)


def test_parse_maps_defense_position_to_def():
    payload = json.dumps(
        {
            "status": "Success",
            "meta": {"type": "PPR", "teams": 12},
            "players": [
                {
                    "name": "Ravens",
                    "position": "DST",
                    "team": "BAL",
                    "adp": 120.0,
                    "stdev": 10.0,
                    "times_drafted": 50,
                    "bye": 7,
                }
            ],
        }
    )
    assert parse_adp(payload)[0].position == "DEF"


def test_parse_rejects_error_status():
    with pytest.raises(AdpUnavailable, match="status"):
        parse_adp(json.dumps({"status": "Error", "players": []}))


def test_parse_rejects_malformed_json():
    with pytest.raises(AdpUnavailable, match="parse"):
        parse_adp("<html>nope</html>")


def test_fetch_hits_network_once_then_serves_cache(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning(raw, calls=calls)
    a = fetch_adp("ppr", 12, 2026, cache, client=client).text
    b = fetch_adp("ppr", 12, 2026, cache, client=client).text
    assert a == b == raw
    assert len(calls) == 1


def test_fetch_url_carries_format_teams_and_year(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    fetch_adp("half-ppr", 10, 2026, cache, client=client_returning(raw, calls=calls))
    url = calls[0]
    assert "half-ppr" in url
    assert "teams=10" in url
    assert "year=2026" in url


def test_fetch_falls_back_to_stale_cache_on_failure(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_adp("ppr", 12, 2026, cache, client=client_returning(raw))
    # Force expiry, then fail the network.
    cache.set(_cache_key("ppr", 12, 2026), raw, ttl_seconds=-1)
    got = fetch_adp("ppr", 12, 2026, cache, client=client_returning("", status=500)).text
    assert got == raw


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(AdpUnavailable, match="500"):
        fetch_adp("ppr", 12, 2026, cache, client=client_returning("", status=500))
