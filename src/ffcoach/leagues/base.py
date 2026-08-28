"""The internal league/team model every adapter maps into.

Pure module: no I/O, no clock. ESPN is today's only implementation of
`LeagueAdapter`; this is the seam that keeps report building and the UI
from knowing that -- a second platform later satisfies the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

BENCH_SLOTS = ("BN", "IR")


@dataclass(frozen=True)
class RosterEntry:
    player_name: str
    position: str
    nfl_team: str
    lineup_slot: str

    @property
    def is_starter(self) -> bool:
        return self.lineup_slot not in BENCH_SLOTS


@dataclass(frozen=True)
class Team:
    team_id: str
    name: str
    owner: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    roster: tuple[RosterEntry, ...]
    is_user_team: bool = False

    @property
    def record(self) -> str:
        if self.ties:
            return f"{self.wins}-{self.losses}-{self.ties}"
        return f"{self.wins}-{self.losses}"


@dataclass(frozen=True)
class League:
    name: str
    season: int
    teams: tuple[Team, ...]


@runtime_checkable
class LeagueAdapter(Protocol):
    """Anything that can produce the current state of the league.

    `manual` (a hand-filled YAML roster) and platform scrapers are both
    expected implementations eventually; nothing downstream should import
    a specific adapter.
    """

    def fetch_league(self) -> League: ...
