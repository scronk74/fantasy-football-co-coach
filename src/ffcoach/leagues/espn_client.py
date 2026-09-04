"""Authenticated fetch of ESPN league/roster/team JSON.

ESPN's fantasy API is unofficial: no docs, no API key, no OAuth. Public
leagues are readable with no auth; private leagues (the common case)
require the `espn_s2` and `SWID` cookies pulled from a logged-in browser
session. There is no refresh endpoint -- when they go bad, the fix is
pulling fresh values from the browser again, so an auth failure is raised
as its own exception rather than silently masked behind stale cache.
"""

from __future__ import annotations

import httpx

from ffcoach.cache import Cache
from ffcoach.sources.base import SourceResult, stale_fallback

ESPN_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
    "/segments/0/leagues/{league_id}"
)
TTL_SECONDS = 15 * 60
# mMatchup adds ~15 KB to a ~28 KB response and is what names this week's
# opponent. Measured rather than assumed, because the scheduler fetches this
# every 30 minutes all season.
VIEWS = ("mTeam", "mRoster", "mSettings", "mMatchup")


class EspnUnavailable(Exception):
    """Raised when the ESPN league response cannot be fetched or parsed."""


class EspnAuthError(EspnUnavailable):
    """Raised when ESPN rejects the session cookies (401/403).

    Distinct from a generic outage: this needs the user to re-extract
    espn_s2/SWID, not a retry, and is the hook a future notifier catches.
    """


def _cache_key(league_id: str, season: int, views: tuple[str, ...] = VIEWS) -> str:
    """Cache key, **including which views were asked for**.

    Without the views in the key, adding one to `VIEWS` silently kept serving
    the old body: the request changed, the key did not, and the cache answered
    with a response that simply did not contain the new field. Found by adding
    `mMatchup` and watching the opponent stay unknown for a fetch that had, as
    far as anything could tell, just succeeded.

    The same shape as the freshness bug in `SourceResult`: a cache that cannot
    tell two different questions apart answers the wrong one confidently.
    """
    return f"espn:league:{league_id}:{season}:{'+'.join(sorted(views))}"


def fetch_league(
    league_id: str,
    season: int,
    espn_s2: str,
    swid: str,
    cache: Cache,
    client: httpx.Client | None = None,
) -> SourceResult:
    key = _cache_key(league_id, season)
    hit = cache.get_with_age(key)
    if hit is not None:
        return SourceResult(text=hit[0], age_seconds=hit[1])

    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        response = client.get(
            ESPN_URL.format(season=season, league_id=league_id),
            params=[("view", v) for v in VIEWS],
            headers={"Cookie": f"espn_s2={espn_s2}; SWID={swid}"},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            # Deliberately no stale fallback: old rosters cannot repair dead
            # cookies, and serving them would hide the one failure that needs
            # a human.
            raise EspnAuthError(
                f"ESPN rejected the session cookies ({exc.response.status_code}); "
                "re-extract espn_s2/SWID from your browser and update espn.yaml"
            ) from exc
        return stale_fallback(cache, key, exc, EspnUnavailable, "ESPN league")
    except httpx.HTTPError as exc:
        return stale_fallback(cache, key, exc, EspnUnavailable, "ESPN league")
    finally:
        if owns_client:
            client.close()

    # Imported here rather than at module scope because `leagues.espn` imports
    # this module's exceptions; at call time the cycle is already resolved.
    # The check itself is the point: ESPN answers an expired session with a
    # 200-status HTML login page, and caching that would destroy the roster we
    # would otherwise still be able to fall back on.
    from ffcoach.leagues.espn import parse_league

    try:
        parse_league(response.text)
    except EspnUnavailable as exc:
        return stale_fallback(cache, key, exc, EspnUnavailable, "ESPN league")

    cache.set(key, response.text, ttl_seconds=TTL_SECONDS)
    return SourceResult(text=response.text)
