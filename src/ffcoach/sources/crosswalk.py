"""Player identity crosswalk from DynastyProcess.

Maps one player to every fantasy platform's ID space at once -- MFL,
Sleeper, ESPN, GSIS (nflverse), FantasyPros, PFR, CBS. This is what makes
multiple sources joinable: rather than matching names pairwise between
every pair of sources (which already failed twice here, on accented names
and on team defenses), each source resolves into a canonical identity once.

Two field-level gotchas this module absorbs, both verified against the
live file:

* Missing values are the literal string ``"NA"``, not an empty cell. Taken
  at face value they would collide thousands of players onto one bogus key.
* ``merge_name`` is a *curated alias*, not merely a lowercased ``name``:
  "Andres Borregales" carries merge_name "andy borregales", which is how
  the sources that use his nickname resolve at all. Both fields are indexed.

Team defenses are absent from this file entirely -- it lists individual
players only -- so DEF continues to match by name and is never looked up
here.
"""

from __future__ import annotations

import csv
import io

import httpx

from ffcoach.cache import Cache
from ffcoach.model.players import normalize_name

CROSSWALK_URL = (
    "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
)
CACHE_KEY = "crosswalk:dynastyprocess:playerids"
TTL_SECONDS = 7 * 24 * 60 * 60  # identity changes slowly; weekly is plenty

_MISSING = ("", "NA")
_POSITION_ALIASES = {"PK": "K", "DST": "DEF", "D/ST": "DEF"}
# Individual players only. DEF is deliberately excluded -- see module docstring.
_FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K")

_ID_FIELDS = ("mfl_id", "sleeper_id", "espn_id", "gsis_id", "fantasypros_id", "pfr_id", "cbs_id")
# Presence of a modern ID separates an active player from a historical
# namesake -- see Crosswalk.resolve.
_MODERN_ID_FIELDS = ("sleeper_id", "gsis_id", "espn_id")


class CrosswalkUnavailable(Exception):
    """Raised when the crosswalk cannot be fetched or parsed."""


def _clean(value: str | None) -> str | None:
    """Normalize the file's ``NA`` sentinel to a real None."""
    if value is None:
        return None
    value = value.strip()
    return None if value in _MISSING else value


class CrosswalkEntry:
    """One player's identity across every ID space."""

    __slots__ = ("ids", "name", "position", "team")

    def __init__(self, ids: dict[str, str | None], name: str, position: str, team: str | None):
        self.ids = ids
        self.name = name
        self.position = position
        self.team = team

    @property
    def has_modern_id(self) -> bool:
        return any(self.ids.get(f) for f in _MODERN_ID_FIELDS)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CrosswalkEntry({self.name!r}, {self.position!r}, {self.team!r})"


class Crosswalk:
    """Resolves (name, position, team) or a platform ID to one identity."""

    def __init__(self, entries: list[CrosswalkEntry]):
        self.entries = entries
        self._by_name: dict[tuple[str, str], list[CrosswalkEntry]] = {}
        self._by_last: dict[tuple[str, str], list[CrosswalkEntry]] = {}
        self._by_id: dict[tuple[str, str], CrosswalkEntry] = {}

        for entry in entries:
            for field in _ID_FIELDS:
                value = entry.ids.get(field)
                if value:
                    self._by_id.setdefault((field, value), entry)

            for label in (entry.name, entry.ids.get("merge_name")):
                if label:
                    key = (normalize_name(label), entry.position)
                    bucket = self._by_name.setdefault(key, [])
                    if entry not in bucket:
                        bucket.append(entry)

            parts = entry.name.split()
            if parts:
                self._by_last.setdefault(
                    (normalize_name(parts[-1]), entry.position), []
                ).append(entry)

    def by_id(self, field: str, value: str) -> CrosswalkEntry | None:
        """Direct lookup for sources that carry a platform ID."""
        return self._by_id.get((field, str(value)))

    def resolve(
        self, name: str, position: str, team: str | None = None
    ) -> tuple[CrosswalkEntry | None, str]:
        """Best-effort identity for a source that only supplies a name.

        Returns ``(entry, confidence)`` where confidence is one of:

        ``"exact"``
            Matched the formal name or the curated alias outright.
        ``"fuzzy"``
            Only the surname and position matched. This rescues real cases
            (FFC's "Kenny Gainwell" against "Kenneth Gainwell") but is the
            one rule that could bind a *different* player who happens to
            share a surname and position, so it is reported rather than
            hidden.
        ``"unresolved"``
            Nothing matched, or several candidates survived and guessing
            would be worse than admitting it. ``entry`` is None.

        Ambiguity is broken by preferring entries with a modern platform
        ID, then by team. The ID rule is what separates Marvin Harrison Jr.
        from his Hall-of-Fame father: our name normalizer strips the "Jr."
        suffix, so both collapse to one key, but only the son carries a
        Sleeper/GSIS/ESPN id.
        """
        position = _POSITION_ALIASES.get(position, position)
        confidence = "exact"
        candidates = list(self._by_name.get((normalize_name(name), position), []))

        if not candidates:
            parts = name.split()
            if parts:
                candidates = list(
                    self._by_last.get((normalize_name(parts[-1]), position), [])
                )
                confidence = "fuzzy"

        if len(candidates) > 1:
            modern = [c for c in candidates if c.has_modern_id]
            if modern:
                candidates = modern

        if len(candidates) > 1 and team:
            matched = [
                c for c in candidates if c.team and c.team.upper()[:2] == team.upper()[:2]
            ]
            if len(matched) == 1:
                candidates = matched

        if len(candidates) != 1:
            return None, "unresolved"
        return candidates[0], confidence


def fetch_crosswalk(cache: Cache, client: httpx.Client | None = None) -> str:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        response = client.get(CROSSWALK_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stale = cache.get_stale(CACHE_KEY)
        if stale is not None:
            return stale[0]
        raise CrosswalkUnavailable(
            f"could not fetch player crosswalk and no cached copy exists: {exc}"
        ) from exc
    finally:
        if owns_client:
            client.close()

    cache.set(CACHE_KEY, response.text, ttl_seconds=TTL_SECONDS)
    return response.text


def parse_crosswalk(raw: str) -> Crosswalk:
    """Pure: CSV text in, Crosswalk out."""
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except csv.Error as exc:
        raise CrosswalkUnavailable(f"could not parse crosswalk CSV: {exc}") from exc

    if rows and "name" not in rows[0]:
        raise CrosswalkUnavailable(
            "could not parse crosswalk: no 'name' column; got "
            f"{sorted(rows[0])[:6]}"
        )

    entries: list[CrosswalkEntry] = []
    for row in rows:
        position = _POSITION_ALIASES.get(row.get("position"), row.get("position"))
        name = _clean(row.get("name"))
        if not name or position not in _FANTASY_POSITIONS:
            continue

        ids = {field: _clean(row.get(field)) for field in _ID_FIELDS}
        ids["merge_name"] = _clean(row.get("merge_name"))
        entries.append(
            CrosswalkEntry(ids=ids, name=name, position=position, team=_clean(row.get("team")))
        )

    return Crosswalk(entries)
