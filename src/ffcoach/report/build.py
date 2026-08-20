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


def write_board(payload: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1))
