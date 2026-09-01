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
    age_seconds: float | None = None,
    stale: bool = False,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        # `generated_at` is when this file was written; `age_seconds` is how
        # old the *data* in it is. Conflating the two is how week-old rosters
        # were published with a current timestamp and `stale: false`.
        "stale": stale,
        "age_seconds": age_seconds,
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
    age_seconds: float | None = None,
    stale: bool = False,
    week: int | None = None,
    week_source: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        # `generated_at` is when this file was written; `age_seconds` is how
        # old the *data* in it is. Conflating the two is how week-old rosters
        # were published with a current timestamp and `stale: false`.
        "stale": stale,
        "age_seconds": age_seconds,
        "week": week,
        # "espn" or "derived". The page shows this so a fallback week is never
        # presented as authoritative.
        "week_source": week_source,
        # Things the ESPN adapter could not interpret. Surfaced in the payload
        # so a renamed slot id shows up on the page rather than only on stderr
        # of a run nobody watched.
        "diagnostics": list(league.diagnostics),
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
                        # ESPN gives us this and the page used to throw it
                        # away, so a QUESTIONABLE starter looked identical to
                        # a healthy one on a page whose whole job is telling
                        # you where your team stands.
                        "injury_status": e.injury_status,
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
