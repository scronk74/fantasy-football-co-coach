import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.leagues.espn_client import (
    EspnAuthError,
    EspnUnavailable,
    _cache_key,
    fetch_league,
)


def client_returning(payload, status=200, calls=None, headers=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        return httpx.Response(status, text=payload, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_hits_network_once_then_serves_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning('{"id": 1}', calls=calls)
    a = fetch_league("999", 2026, "s2", "{swid}", cache, client=client).text
    b = fetch_league("999", 2026, "s2", "{swid}", cache, client=client).text
    assert a == b == '{"id": 1}'
    assert len(calls) == 1


def test_fetch_url_carries_season_league_id_and_views(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning("{}", calls=calls))
    url = str(calls[0].url)
    assert "seasons/2026" in url
    assert "leagues/999" in url
    assert "view=mTeam" in url
    assert "view=mRoster" in url
    assert "view=mSettings" in url


def test_fetch_sends_cookies(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    fetch_league(
        "999", 2026, "the-s2-value", "{the-swid}", cache, client=client_returning("{}", calls=calls)
    )
    cookie_header = calls[0].headers.get("cookie", "")
    assert "espn_s2=the-s2-value" in cookie_header
    assert "SWID" in cookie_header


def test_fetch_raises_auth_error_on_401(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(EspnAuthError, match="401"):
        fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning("", status=401))


def test_fetch_raises_auth_error_on_403(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(EspnAuthError, match="403"):
        fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning("", status=403))


def test_auth_error_does_not_fall_back_to_stale_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning('{"id": 1}'))
    # Expire it, then fail with a 401 -- this must still raise, not serve stale.
    cache.set(_cache_key("999", 2026), '{"id": 1}', ttl_seconds=-1)
    with pytest.raises(EspnAuthError):
        fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning("", status=401))


def test_fetch_falls_back_to_stale_cache_on_non_auth_failure(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning('{"id": 1}'))
    cache.set(_cache_key("999", 2026), '{"id": 1}', ttl_seconds=-1)
    got = fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning("", status=500)).text
    assert got == '{"id": 1}'


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(EspnUnavailable, match="500"):
        fetch_league("999", 2026, "s2", "{swid}", cache, client=client_returning("", status=500))


def test_the_cache_key_distinguishes_different_view_sets():
    """Adding a view to VIEWS must not keep serving the body from before it.

    The request changed and the key did not, so the cache answered with a
    response that simply did not contain the new field -- and the fetch looked
    like it had succeeded.
    """
    from ffcoach.leagues.espn_client import _cache_key

    a = _cache_key("9", 2026, ("mTeam", "mRoster"))
    b = _cache_key("9", 2026, ("mTeam", "mRoster", "mMatchup"))
    assert a != b


def test_the_cache_key_ignores_the_order_views_are_listed_in():
    """Reordering the tuple is not a different question."""
    from ffcoach.leagues.espn_client import _cache_key

    assert _cache_key("9", 2026, ("a", "b")) == _cache_key("9", 2026, ("b", "a"))
