"""Assemble the draft board.

Emits structured rows, never prose. Spec design rule 2: advisors produce
findings; the Claude skill turns findings into coaching.
"""

from __future__ import annotations

from dataclasses import dataclass

from ffcoach.config import LeagueConfig
from ffcoach.model.players import Player
from ffcoach.model.tiers import assign_tiers
from ffcoach.model.value import availability, availability_text


@dataclass(frozen=True)
class BoardRow:
    rank: int
    name: str
    position: str
    team: str
    adp: float
    stdev: float
    bye: int | None
    availability: str
    availability_text: str
    tier: int
    tier_break_after: bool
    injury_status: str | None
    reason: str


def _reason(avail: str, injury: str | None) -> str:
    """One short sentence explaining why this row is highlighted.

    Spec UX rule 4: no unexplained badge, in either mode. Every clause here
    must trace to something computed, not inferred -- which is why there is
    no "falling past his usual slot" clause any more.
    """
    parts: list[str] = []
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
                availability=avail,
                availability_text=availability_text(avail, next_pick),
                tier=tier,
                tier_break_after=(not is_last and tiers[index + 1] != tier),
                injury_status=player.injury_status,
                reason=_reason(avail, player.injury_status),
            )
        )
    return rows
