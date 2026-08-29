"""ESPN league JSON -> the internal league model.

This is the one file in the project built against a contract no one here
has verified. ESPN's fantasy API is unofficial and community
reverse-engineered; the shape below (position/slot/pro-team ID tables,
mTeam/mRoster/mSettings field names) matches what that community has
documented, exercised only against a hand-built fixture
(tests/fixtures/espn_league.json) until a real league confirms it. See
that fixture's header comment.
"""

from __future__ import annotations

import json

from ffcoach.leagues.base import League, RosterEntry, Team
from ffcoach.leagues.espn_client import EspnUnavailable

# ESPN's defaultPositionId per player.
_POSITION_IDS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

# ESPN's lineupSlotId per roster entry: which slot a player is filling.
_SLOT_IDS = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    23: "FLEX",
    17: "K",
    16: "DEF",
    20: "BN",
    21: "IR",
}

# ESPN's proTeamId -> NFL team abbreviation.
_PRO_TEAM_ABBREVIATIONS = {
    0: "FA",
    1: "ATL",
    2: "BUF",
    3: "CHI",
    4: "CIN",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GB",
    10: "TEN",
    11: "IND",
    12: "KC",
    13: "LV",
    14: "LAR",
    15: "MIA",
    16: "MIN",
    17: "NE",
    18: "NO",
    19: "NYG",
    20: "NYJ",
    21: "PHI",
    22: "ARI",
    23: "PIT",
    24: "LAC",
    25: "SF",
    26: "SEA",
    27: "TB",
    28: "WSH",
    29: "CAR",
    30: "JAX",
    33: "BAL",
    34: "HOU",
}


def _normalize_swid(value: str) -> str:
    """SWID may or may not carry surrounding braces; compare without them."""
    return value.strip("{}").lower()


def _parse_entry(entry: dict) -> RosterEntry:
    player = entry.get("playerPoolEntry", {}).get("player", {})
    # ESPN reports availability as injuryStatus (ACTIVE/QUESTIONABLE/OUT/
    # INJURY_RESERVE) and separately as an `injured` boolean. The string is the
    # useful one; the boolean cannot distinguish "questionable" from "out".
    return RosterEntry(
        player_name=player.get("fullName", ""),
        position=_POSITION_IDS.get(player.get("defaultPositionId"), "UNKNOWN"),
        nfl_team=_PRO_TEAM_ABBREVIATIONS.get(player.get("proTeamId"), "FA"),
        lineup_slot=_SLOT_IDS.get(entry.get("lineupSlotId"), "BN"),
        injury_status=player.get("injuryStatus"),
    )


def _parse_team(row: dict, member_names: dict[str, str], my_swid: str | None) -> Team:
    overall = row.get("record", {}).get("overall", {})
    owner_ids = [_normalize_swid(o) for o in row.get("owners", [])]
    owner_display = ", ".join(member_names.get(oid, oid) for oid in owner_ids) or "Unknown"
    is_user_team = bool(my_swid) and _normalize_swid(my_swid) in owner_ids
    name = row.get("nickname") or row.get("location") or f"Team {row.get('id')}"

    return Team(
        team_id=str(row.get("id")),
        name=str(name),
        owner=owner_display,
        wins=int(overall.get("wins", 0)),
        losses=int(overall.get("losses", 0)),
        ties=int(overall.get("ties", 0)),
        points_for=float(overall.get("pointsFor", 0.0)),
        points_against=float(overall.get("pointsAgainst", 0.0)),
        roster=tuple(_parse_entry(e) for e in row.get("roster", {}).get("entries", [])),
        is_user_team=is_user_team,
    )


def parse_league(raw: str, my_swid: str | None = None) -> League:
    """Pure: ESPN JSON text (+ your own SWID) in, League out.

    `my_swid` identifies which team is yours. ESPN's per-team `owners` list
    holds member GUIDs, and SWID *is* that GUID -- the same value used to
    authenticate. It's passed in rather than read back off the network so
    this stays a pure function.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EspnUnavailable(f"could not parse ESPN league response: {exc}") from exc

    member_names = {
        _normalize_swid(m["id"]): m.get("displayName", "")
        for m in payload.get("members", [])
        if m.get("id")
    }

    return League(
        name=str(payload.get("settings", {}).get("name", "")),
        season=int(payload.get("seasonId", 0)),
        teams=tuple(
            _parse_team(row, member_names, my_swid) for row in payload.get("teams", [])
        ),
        roster_slots=_parse_roster_slots(payload),
        current_week=_parse_current_week(payload),
    )


def _parse_roster_slots(payload: dict) -> dict[str, int]:
    """Lineup slot counts from `rosterSettings.lineupSlotCounts`.

    ESPN keys this by slot id as a string and lists every slot in the game,
    most with a count of zero. Only non-zero, recognized slots are kept -- the
    zeros are slots this league does not use.
    """
    counts = (
        payload.get("settings", {}).get("rosterSettings", {}).get("lineupSlotCounts")
        or {}
    )
    out: dict[str, int] = {}
    for slot_id, count in counts.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        name = _SLOT_IDS.get(int(slot_id)) if str(slot_id).lstrip("-").isdigit() else None
        if name and n > 0:
            out[name] = out.get(name, 0) + n
    return out


def _parse_current_week(payload: dict) -> int | None:
    """ESPN's own week number, preferred over anything we could derive."""
    for value in (
        payload.get("scoringPeriodId"),
        payload.get("status", {}).get("currentMatchupPeriod"),
    ):
        try:
            week = int(value)
        except (TypeError, ValueError):
            continue
        if week > 0:
            return week
    return None
