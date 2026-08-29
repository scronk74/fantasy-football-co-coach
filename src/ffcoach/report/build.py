"""Write the JSON contract the browser reads.

The shape here is asserted by tests on the Python side so the page's
contract cannot drift silently.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ffcoach.advisors.draft import BoardRow
from ffcoach.config import LeagueConfig
from ffcoach.leagues.base import League

SCHEMA_VERSION = 1


def board_payload(
    rows: list[BoardRow],
    config: LeagueConfig,
    generated_at: str,
    unmatched: list[str],
    stale_seconds: float | None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "stale": stale_seconds is not None,
        "stale_seconds": stale_seconds,
        "unmatched": list(unmatched),
        "league": {
            "name": config.name,
            "season": config.season,
            "teams": config.teams,
            "scoring": config.scoring,
            "my_pick": config.my_pick,
            "next_pick": config.next_pick_after(config.my_pick),
            "rounds": config.rounds,
        },
        "players": [dataclasses.asdict(row) for row in rows],
    }


def league_payload(
    league: League,
    generated_at: str,
    stale_seconds: float | None,
    week: int | None = None,
    week_source: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "stale": stale_seconds is not None,
        "stale_seconds": stale_seconds,
        "week": week,
        # "espn" or "derived". The page shows this so a fallback week is never
        # presented as authoritative.
        "week_source": week_source,
        "league": {
            "name": league.name,
            "season": league.season,
            "roster_slots": dict(league.roster_slots),
        },
        "teams": [
            {
                "team_id": t.team_id,
                "name": t.name,
                "owner": t.owner,
                "wins": t.wins,
                "losses": t.losses,
                "ties": t.ties,
                "record": t.record,
                "points_for": t.points_for,
                "points_against": t.points_against,
                "is_user_team": t.is_user_team,
                "roster": [
                    {
                        "player_name": e.player_name,
                        "position": e.position,
                        "nfl_team": e.nfl_team,
                        "lineup_slot": e.lineup_slot,
                        "is_starter": e.is_starter,
                    }
                    for e in t.roster
                ],
            }
            for t in league.teams
        ],
    }


def write_board(payload: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1))
