"""Join ADP records to player metadata.

The two sources have unrelated ID spaces, so the join key is normalized
name plus position. Unmatched players are reported rather than dropped: a
silent join failure would quietly strip injury data off the board.
"""

from __future__ import annotations

import dataclasses

from ffcoach.model.players import Player


def enrich(
    players: list[Player], meta: dict[tuple[str, str], dict]
) -> tuple[list[Player], list[str]]:
    enriched: list[Player] = []
    unmatched: list[str] = []

    for player in players:
        row = meta.get(player.key)
        if row is None:
            unmatched.append(player.name)
            enriched.append(player)
            continue
        enriched.append(
            dataclasses.replace(
                player,
                sleeper_id=row.get("player_id"),
                injury_status=row.get("injury_status"),
            )
        )

    return enriched, unmatched
