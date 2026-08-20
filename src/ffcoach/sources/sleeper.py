"""Player metadata from the Sleeper API.

Free, public, unauthenticated. Roughly 12,000 players and about 14MB, so it
is cached for a day. Sleeper supplies injury status and identity; it does
not supply ADP.
"""

from __future__ import annotations

import json

import httpx

from ffcoach.model.players import normalize_name

SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
TTL_SECONDS = 24 * 60 * 60
CACHE_KEY = "sleeper:players:nfl"

_POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}
_KEEP = ("QB", "RB", "WR", "TE", "K", "DEF")


class PlayersUnavailable(Exception):
    """Raised when player metadata cannot be fetched or parsed."""


def fetch_players(cache, client: httpx.Client | None = None) -> str:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        response = client.get(SLEEPER_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stale = cache.get_stale(CACHE_KEY)
        if stale is not None:
            return stale[0]
        raise PlayersUnavailable(
            f"could not fetch Sleeper players and no cached copy exists: {exc}"
        ) from exc
    finally:
        if owns_client:
            client.close()

    cache.set(CACHE_KEY, response.text, ttl_seconds=TTL_SECONDS)
    return response.text


def parse_players(raw: str) -> dict[tuple[str, str], dict]:
    """Pure: JSON text in, lookup keyed by (normalized name, position) out."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlayersUnavailable(f"could not parse Sleeper response: {exc}") from exc

    out: dict[tuple[str, str], dict] = {}
    for row in payload.values():
        name = row.get("full_name")
        position = _POSITION_ALIASES.get(row.get("position"), row.get("position"))
        if not name or position not in _KEEP:
            continue
        out[(normalize_name(name), position)] = row
    return out
