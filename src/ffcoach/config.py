"""League configuration: the single source of truth for format-specific rules.

Nothing downstream may hardcode scoring, roster shape, or team count.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

SCORING_FORMATS = ("standard", "half-ppr", "ppr")
STARTER_SLOTS = ("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")
BENCH_SLOT = "BN"
VALID_SLOTS = STARTER_SLOTS + (BENCH_SLOT,)


class ConfigError(Exception):
    """Raised when league.yaml is missing, malformed, or invalid."""


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    season: int
    teams: int
    scoring: str
    my_pick: int
    roster: dict[str, int]

    @property
    def starters_total(self) -> int:
        return sum(n for slot, n in self.roster.items() if slot != BENCH_SLOT)

    @property
    def rounds(self) -> int:
        return sum(self.roster.values())

    def next_pick_after(self, pick: int) -> int | None:
        """Next overall pick number in a snake draft, or None past the end.

        In a snake, the order reverses every round, so your next pick is
        always mirrored around the turn. Both the odd->even and even->odd
        transitions reduce to the same expression.
        """
        rnd = (pick - 1) // self.teams + 1
        if rnd >= self.rounds:
            return None
        pos_in_round = (pick - 1) % self.teams + 1
        return rnd * self.teams + (self.teams - pos_in_round + 1)


def load_config(path: Path) -> LeagueConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"league config not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    missing = {"name", "season", "teams", "scoring", "my_pick", "roster"} - raw.keys()
    if missing:
        raise ConfigError(f"missing required keys: {', '.join(sorted(missing))}")

    scoring = str(raw["scoring"]).lower()
    if scoring not in SCORING_FORMATS:
        raise ConfigError(f"scoring must be one of {SCORING_FORMATS}, got {scoring!r}")

    roster = raw["roster"] or {}
    for slot in roster:
        if slot not in VALID_SLOTS:
            raise ConfigError(f"unknown roster slot {slot!r}; valid: {VALID_SLOTS}")

    teams = int(raw["teams"])
    my_pick = int(raw["my_pick"])
    if not 1 <= my_pick <= teams:
        raise ConfigError(f"my_pick must be between 1 and {teams}, got {my_pick}")

    return LeagueConfig(
        name=str(raw["name"]),
        season=int(raw["season"]),
        teams=teams,
        scoring=scoring,
        my_pick=my_pick,
        roster={str(k): int(v) for k, v in roster.items()},
    )
