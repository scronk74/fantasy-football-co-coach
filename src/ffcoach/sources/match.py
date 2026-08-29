"""Resolve player identity, then attach metadata.

Two steps that used to be one. Identity is resolved through the
DynastyProcess crosswalk (`sources/crosswalk.py`), which yields every
platform's id for a player; metadata is then looked up by id where one
exists and by name only as a fallback.

Doing it in that order matters because name matching has already failed
here twice -- on accented characters ("Piñeiro") and on nicknames ("Kenny"
for "Kenneth") -- and each additional source multiplies those near misses.
Identity resolved once, by id, does not have that property.

Nothing is ever silently dropped or silently guessed: players whose
metadata is missing are reported in `unmatched`, and players whose identity
was resolved only by surname are reported in `fuzzy` so a wrong bind is
visible rather than invisible.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from ffcoach.model.players import Player, PlayerIds

_CROSSWALK_ID_FIELDS = ("mfl_id", "sleeper_id", "espn_id", "gsis_id", "fantasypros_id")


@dataclass(frozen=True)
class EnrichResult:
    players: list[Player]
    unmatched: list[str] = field(default_factory=list)
    fuzzy: list[str] = field(default_factory=list)


def _ids_from_entry(entry) -> PlayerIds:
    return PlayerIds(**{f: entry.ids.get(f) for f in _CROSSWALK_ID_FIELDS})


def enrich(
    players: list[Player],
    meta: dict[tuple[str, str], dict],
    crosswalk=None,
    meta_by_id: dict[str, dict] | None = None,
) -> EnrichResult:
    """Attach crosswalk ids and Sleeper metadata to each player.

    `crosswalk` and `meta_by_id` are optional so this stays usable (and the
    existing tests stay meaningful) without them, in which case it behaves
    exactly as the original name-only join did.
    """
    enriched: list[Player] = []
    unmatched: list[str] = []
    fuzzy: list[str] = []

    for player in players:
        ids = player.ids
        confidence = "exact"

        if crosswalk is not None:
            entry, confidence = crosswalk.resolve(player.name, player.position, player.team)
            if entry is not None:
                ids = _ids_from_entry(entry)
                if confidence == "fuzzy":
                    fuzzy.append(player.name)
            else:
                # Team defenses are absent from the crosswalk by design, so
                # an unresolved DEF is expected, not a failure worth noting.
                confidence = "unresolved"

        row = None
        if meta_by_id is not None and ids.sleeper_id:
            row = meta_by_id.get(ids.sleeper_id)
        if row is None:
            row = meta.get(player.key)

        if row is None:
            unmatched.append(player.name)
            enriched.append(dataclasses.replace(player, ids=ids, match_confidence=confidence))
            continue

        enriched.append(
            dataclasses.replace(
                player,
                sleeper_id=row.get("player_id") or ids.sleeper_id,
                injury_status=row.get("injury_status"),
                ids=ids,
                match_confidence=confidence,
            )
        )

    return EnrichResult(players=enriched, unmatched=unmatched, fuzzy=fuzzy)
