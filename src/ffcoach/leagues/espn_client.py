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

ESPN_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
    "/segments/0/leagues/{league_id}"
)
TTL_SECONDS = 15 * 60
VIEWS = ("mTeam", "mRoster", "mSettings")


class EspnUnavailable(Exception):
    """Raised when the ESPN league response cannot be fetched or parsed."""


class EspnAuthError(EspnUnavailable):
    """Raised when ESPN rejects the session cookies (401/403).

    Distinct from a generic outage: this needs the user to re-extract
    espn_s2/SWID, not a retry, and is the hook a future notifier catches.
    """


def _cache_key(league_id: str, season: int) -> str:
    return f"espn:league:{league_id}:{season}"


def fetch_league(
    league_id: str,
    season: int,
    espn_s2: str,
    swid: str,
    cache: Cache,
    client: httpx.Client | None = None,
) -> str:
    key = _cache_key(league_id, season)
    cached = cache.get(key)
    if cached is not None:
        return cached

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
            raise EspnAuthError(
                f"ESPN rejected the session cookies ({exc.response.status_code}); "
                "re-extract espn_s2/SWID from your browser and update espn.yaml"
            ) from exc
        stale = cache.get_stale(key)
        if stale is not None:
            return stale[0]
        raise EspnUnavailable(
            f"could not fetch ESPN league and no cached copy exists: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        stale = cache.get_stale(key)
        if stale is not None:
            return stale[0]
        raise EspnUnavailable(
            f"could not fetch ESPN league and no cached copy exists: {exc}"
        ) from exc
    finally:
        if owns_client:
            client.close()

    cache.set(key, response.text, ttl_seconds=TTL_SECONDS)
    return response.text
