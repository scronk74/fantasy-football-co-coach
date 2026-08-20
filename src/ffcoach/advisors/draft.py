"""Assemble the draft board.

Emits structured rows, never prose. Spec design rule 2: advisors produce
findings; the Claude skill turns findings into coaching.
"""

from __future__ import annotations

from dataclasses import dataclass

from ffcoach.config import LeagueConfig
from ffcoach.model.players import Player
from ffcoach.model.tiers import assign_tiers
from ffcoach.model.value import (
    availability,
    availability_text,
    verdict,
    verdict_text,
)


@dataclass(frozen=True)
class BoardRow:
    rank: int
    name: str
    position: str
    team: str
    adp: float
    stdev: float
    bye: int | None
    value: float
    verdict: str
    verdict_text: str
    availability: str
    availability_text: str
    tier: int
    tier_break_after: bool
    injury_status: str | None
    reason: str


def _reason(row_verdict: str, avail: str, injury: str | None) -> str:
    """One short sentence explaining why this row is highlighted.

    Spec UX rule 4: no unexplained badge, in either mode.
    """
    parts: list[str] = []
    if row_verdict == "bargain":
        parts.append("Falling past his usual draft slot")
    elif row_verdict == "reach":
        parts.append("Would be an early pick for him")
    if avail == "gone":
        parts.append("unlikely to last to your next pick")
    if injury:
        parts.append(f"listed {injury}")
    if not parts:
        return ""
    sentence = ", ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def build_board(players: list[Player], config: LeagueConfig) -> list[BoardRow]:
    if not players:
        return []

    ordered = sorted(players, key=lambda p: p.adp)
    tiers = assign_tiers(ordered)
    next_pick = config.next_pick_after(config.my_pick) or config.my_pick

    rows: list[BoardRow] = []
    for index, (player, tier) in enumerate(zip(ordered, tiers)):
        rank = index + 1
        row_verdict = verdict(rank=rank, adp=player.adp)
        avail = availability(adp=player.adp, stdev=player.stdev, pick=next_pick)
        is_last = index == len(ordered) - 1
        rows.append(
            BoardRow(
                rank=rank,
                name=player.name,
                position=player.position,
                team=player.team,
                adp=player.adp,
                stdev=player.stdev,
                bye=player.bye,
                value=round(player.adp - rank, 1),
                verdict=row_verdict,
                verdict_text=verdict_text(row_verdict),
                availability=avail,
                availability_text=availability_text(avail, next_pick),
                tier=tier,
                tier_break_after=(not is_last and tiers[index + 1] != tier),
                injury_status=player.injury_status,
                reason=_reason(row_verdict, avail, player.injury_status),
            )
        )
    return rows
