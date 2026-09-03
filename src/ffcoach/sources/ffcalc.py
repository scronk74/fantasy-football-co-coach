"""Average Draft Position from Fantasy Football Calculator.

Free, public, unauthenticated. Chosen over Sleeper because Sleeper exposes
no aggregate ADP endpoint. The `stdev` field is what makes a real
availability calculation possible instead of a guess.
"""

from __future__ import annotations

import json

import httpx

from ffcoach.cache import Cache
from ffcoach.model.players import Player
from ffcoach.sources.base import SourceResult, stale_fallback

FFCALC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"
TTL_SECONDS = 6 * 60 * 60

_POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}


class AdpUnavailable(Exception):
    """Raised when ADP cannot be fetched or parsed and no cache exists."""


def _cache_key(scoring: str, teams: int, season: int) -> str:
    return f"adp:{scoring}:{teams}:{season}"


def fetch_adp(
    scoring: str,
    teams: int,
    season: int,
    cache: Cache,
    client: httpx.Client | None = None,
) -> SourceResult:
    key = _cache_key(scoring, teams, season)
    hit = cache.get_with_age(key)
    if hit is not None:
        return SourceResult(text=hit[0], age_seconds=hit[1])

    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        response = client.get(
            FFCALC_URL.format(scoring=scoring),
            params={"teams": teams, "year": season},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return stale_fallback(cache, key, exc, AdpUnavailable, "ADP")
    finally:
        if owns_client:
            client.close()

    # Parse before caching. A 200 is not proof of a usable body, and writing an
    # unparseable one would evict the last copy that *was* usable.
    try:
        parse_adp(response.text)
    except AdpUnavailable as exc:
        return stale_fallback(cache, key, exc, AdpUnavailable, "ADP")

    cache.set(key, response.text, ttl_seconds=TTL_SECONDS)
    return SourceResult(text=response.text)


def parse_adp(raw: str) -> list[Player]:
    """Pure: JSON text in, sorted Players out."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdpUnavailable(f"could not parse ADP response: {exc}") from exc

    if payload.get("status") != "Success":
        raise AdpUnavailable(f"ADP response status was {payload.get('status')!r}")

    players = [
        Player(
            name=row["name"],
            position=_POSITION_ALIASES.get(row["position"], row["position"]),
            team=row.get("team") or "",
            adp=float(row["adp"]),
            stdev=float(row.get("stdev") or 0.0),
            bye=int(row["bye"]) if row.get("bye") else None,
            times_drafted=int(row.get("times_drafted") or 0),
            injury_status=None,
            sleeper_id=None,
        )
        for row in payload.get("players", [])
    ]
    return sorted(players, key=lambda p: p.adp)
