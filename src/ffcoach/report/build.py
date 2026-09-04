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
                "abbrev": t.abbrev,
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


def check_payload(
    result,
    league_name: str,
    generated_at: str,
    timezone: str,
) -> dict:
    """One check, shaped for the Week page.

    Findings are flattened here rather than in the browser: `FixPlan`, the
    severity ordering and `is_actionable` are all tested Python, and
    re-deriving any of them in JavaScript would be a second implementation of
    the rules that decide whether you get told about a problem.

    `status` and `blind_spots` travel verbatim. The page's job is to render the
    difference between "nothing is wrong" and "we could not see everything"
    (D-054), and it cannot do that from an empty findings list alone.
    """
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "timezone": timezone,
        "league": league_name,
        "team": result.team_name,
        "team_abbrev": result.team_abbrev,
        "opponent": result.opponent_name,
        "opponent_abbrev": result.opponent_abbrev,
        "week": result.week,
        "week_source": result.week_source,
        "status": result.status,
        "all_clear": result.all_clear,
        "pre_draft": result.pre_draft,
        "blind_spots": list(result.blind_spots),
        "next_lock": _iso(result.next_lock),
        "waiver_deadline": _iso(result.waiver_deadline),
        "stale": any(s.stale for s in result.sources),
        "age_seconds": max((s.age_seconds for s in result.sources), default=None),
        "sources": [
            {"name": s.name, "age_seconds": s.age_seconds, "stale": s.stale,
             "error": s.error}
            for s in result.sources
        ],
        "findings": [
            {
                "kind": f.kind,
                "player_name": f.player_name,
                "position": f.position,
                "lineup_slot": f.lineup_slot,
                "nfl_team": f.nfl_team,
                "reason": f.reason,
                "replacements": list(f.replacements),
                "ir_candidates": list(f.ir_candidates),
                # The verb, not the kind: "Claim" and "Swap" are different
                # instructions, and a time alone cannot express the difference
                # (D-046).
                "verb": f.fix.verb,
                "deadline": _iso(f.deadline),
                "locked": f.locked,
                # Computed here because `is_actionable` is tested Python and
                # comparing a deadline to "now" in the browser would answer a
                # slightly different question on every reload.
                "actionable": f in result.actionable,
                "lock_is_estimated": f.lock_is_estimated,
                "severity": f.severity,
            }
            for f in result.findings
        ],
    }


def _iso(moment) -> str | None:
    return moment.isoformat() if moment is not None else None
