import json
from pathlib import Path

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.sources.sleeper import PlayersUnavailable, fetch_players, parse_players

FIXTURE = Path(__file__).parent / "fixtures" / "sleeper_players.json"


def client_returning(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_keys_by_normalized_name_and_position():
    meta = parse_players(FIXTURE.read_text())
    assert meta
    for (name, position), row in meta.items():
        assert name == name.lower()
        assert " " not in name
        assert position in ("QB", "RB", "WR", "TE", "K", "DEF")
        assert "player_id" in row


def test_parse_skips_players_without_a_name():
    payload = json.dumps({"1": {"player_id": "1", "position": "RB", "full_name": None}})
    assert parse_players(payload) == {}


def test_parse_rejects_malformed_json():
    with pytest.raises(PlayersUnavailable, match="parse"):
        parse_players("not json")


def test_fetch_caches_after_first_call(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning("{}", calls=calls)
    fetch_players(cache, client=client)
    fetch_players(cache, client=client)
    assert len(calls) == 1


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(PlayersUnavailable, match="500"):
        fetch_players(cache, client=client_returning("", status=500))
