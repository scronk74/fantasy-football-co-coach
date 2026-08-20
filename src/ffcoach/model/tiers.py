"""Tier assignment by ADP cliff detection.

A tier break is where the market's opinion drops off sharply, which is more
useful than fixed-size buckets: it tells you when waiting costs you real
quality rather than one ranking slot.
"""

from __future__ import annotations

from collections.abc import Sequence

from ffcoach.model.players import Player


def assign_tiers(players: Sequence[Player], gap_multiplier: float = 1.5) -> list[int]:
    """Return a tier number per player, in input order, starting at 1."""
    if not players:
        return []

    tiers = [1]
    gaps: list[float] = []
    tier = 1

    for prev, cur in zip(players, players[1:]):
        gap = cur.adp - prev.adp
        if gaps:
            mean_gap = sum(gaps) / len(gaps)
            if mean_gap > 0 and gap > mean_gap * gap_multiplier:
                tier += 1
                gaps = []
                tiers.append(tier)
                continue
        gaps.append(gap)
        tiers.append(tier)

    return tiers
