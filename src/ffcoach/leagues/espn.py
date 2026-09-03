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

from ffcoach.leagues.base import (
    PER_PLAYER_LOCKTIME,
    UNKNOWN,
    League,
    LineupLock,
    LockMode,
    RosterEntry,
    Team,
    WaiverSettings,
)
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


def _parse_entry(entry: dict, notes: list[str]) -> RosterEntry:
    player = entry.get("playerPoolEntry", {}).get("player", {})
    name = player.get("fullName", "")

    # An unrecognized id becomes UNKNOWN and says so, rather than falling back
    # to a plausible default. The defaults it used to have were the two worst
    # available: an unknown slot became "BN", so a real starter ESPN had
    # renamed the slot id for would be skipped by every check; and an unknown
    # pro team became "FA", so he would match no schedule row and look like
    # someone with nothing to worry about. Both produce a clean run and a
    # silently unguarded lineup.
    slot_id = entry.get("lineupSlotId")
    slot = _SLOT_IDS.get(slot_id) if isinstance(slot_id, int) else None
    if slot is None:
        notes.append(f"unrecognized lineupSlotId {slot_id!r} for {name or 'a player'}")
        slot = UNKNOWN

    team_id = player.get("proTeamId")
    nfl_team = _PRO_TEAM_ABBREVIATIONS.get(team_id) if isinstance(team_id, int) else None
    if nfl_team is None:
        notes.append(f"unrecognized proTeamId {team_id!r} for {name or 'a player'}")
        nfl_team = UNKNOWN

    position = _POSITION_IDS.get(player.get("defaultPositionId"), UNKNOWN)

    # ESPN reports availability as injuryStatus (ACTIVE/QUESTIONABLE/OUT/
    # INJURY_RESERVE) and separately as an `injured` boolean. The string is the
    # useful one; the boolean cannot distinguish "questionable" from "out".
    return RosterEntry(
        player_name=name,
        position=position,
        nfl_team=nfl_team,
        lineup_slot=slot,
        injury_status=player.get("injuryStatus"),
    )


def _parse_team(
    row: dict, member_names: dict[str, str], my_swid: str | None, notes: list[str]
) -> Team:
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
        roster=tuple(
            _parse_entry(e, notes)
            for e in row.get("roster", {}).get("entries", [])
            if isinstance(e, dict)
        ),
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

    # Shape, not just syntax. Valid JSON of the wrong shape used to escape as a
    # bare AttributeError or ValueError -- a stack trace instead of the
    # module's own exception, so no caller's `except EspnUnavailable` could
    # catch it and no stale fallback could run. Confirmed reachable with a
    # top-level list, `settings: []`, and `wins: "oops"`.
    _require(isinstance(payload, dict), "top level is not an object")
    _require(isinstance(payload.get("settings", {}), dict), "settings is not an object")
    _require(isinstance(payload.get("teams", []), list), "teams is not a list")
    _require(isinstance(payload.get("members", []), list), "members is not a list")

    notes: list[str] = []
    member_names = {
        _normalize_swid(m["id"]): m.get("displayName", "")
        for m in payload.get("members", [])
        if isinstance(m, dict) and m.get("id")
    }

    try:
        teams = tuple(
            _parse_team(row, member_names, my_swid, notes)
            for row in payload.get("teams", [])
            if isinstance(row, dict)
        )
        season = int(payload.get("seasonId", 0))
    except (TypeError, ValueError, AttributeError) as exc:
        raise EspnUnavailable(f"could not parse ESPN league: unexpected shape: {exc}") from exc

    waivers, waiver_note = _parse_waivers(payload)
    if waiver_note:
        notes.append(waiver_note)

    return League(
        name=str(payload.get("settings", {}).get("name", "")),
        season=season,
        teams=teams,
        roster_slots=_parse_roster_slots(payload),
        current_week=_parse_current_week(payload),
        waivers=waivers,
        lineup_lock=_parse_lineup_lock(payload),
        diagnostics=tuple(notes),
    )


def _require(ok: bool, what: str) -> None:
    if not ok:
        raise EspnUnavailable(f"could not parse ESPN league: {what}")


def _parse_lineup_lock(payload: dict) -> LineupLock:
    """`rosterSettings.lineupLocktimeType` -> a lock mode plus its provenance.

    Only the per-player spelling is matched, because it is the only one seen
    live. A present-but-unfamiliar value is read as weekly rather than shrugged
    off: ESPN offers exactly two lock rules, so a non-default value is evidence
    the league chose the other one. Absence is *not* such evidence -- it is no
    evidence at all -- so it falls back to ESPN's default and says so. That
    asymmetry is deliberate.
    """
    roster_settings = payload.get("settings", {}).get("rosterSettings")
    raw = roster_settings.get("lineupLocktimeType") if isinstance(roster_settings, dict) else None
    if raw is None:
        return LineupLock(mode=LockMode.PER_PLAYER, raw=None, assumed=True)
    text = str(raw).strip().upper()
    if text == PER_PLAYER_LOCKTIME:
        return LineupLock(mode=LockMode.PER_PLAYER, raw=str(raw))
    return LineupLock(mode=LockMode.WEEKLY, raw=str(raw), unrecognized=True)


def _parse_waivers(payload: dict) -> tuple[WaiverSettings, str | None]:
    """Waiver schedule, plus a note when it had to be discarded.

    An out-of-range hour is treated as *unknown*, not clamped. Hour 25 used to
    survive parsing and then blow up building a datetime much later, and a
    clamp to 23 would be worse still: it would produce a confident deadline
    from a value we know is wrong. Returning unknown makes the deadline None,
    which every caller already handles as "a claim is needed but not by when".
    """
    a = payload.get("settings", {}).get("acquisitionSettings")
    if not isinstance(a, dict):
        return WaiverSettings(), None

    days = a.get("waiverProcessDays")
    days = days if isinstance(days, list) else []

    try:
        hour = int(a.get("waiverProcessHour", 0))
    except (TypeError, ValueError):
        return WaiverSettings(), (
            f"unusable waiverProcessHour {a.get('waiverProcessHour')!r}; "
            "waiver deadlines will read as unknown"
        )
    if not 0 <= hour <= 23:
        return WaiverSettings(), (
            f"waiverProcessHour {hour} is outside 0-23; "
            "waiver deadlines will read as unknown"
        )

    return (
        WaiverSettings(
            process_days=tuple(str(d).upper() for d in days),
            process_hour=hour,
            uses_budget=bool(a.get("isUsingAcquisitionBudget")),
        ),
        None,
    )


def _parse_roster_slots(payload: dict) -> dict[str, int]:
    """Lineup slot counts from `rosterSettings.lineupSlotCounts`.

    ESPN keys this by slot id as a string and lists every slot in the game,
    most with a count of zero. Only non-zero, recognized slots are kept -- the
    zeros are slots this league does not use.
    """
    roster_settings = payload.get("settings", {}).get("rosterSettings")
    counts = roster_settings.get("lineupSlotCounts") if isinstance(roster_settings, dict) else None
    if not isinstance(counts, dict):
        return {}
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
    status = payload.get("status")
    for value in (
        payload.get("scoringPeriodId"),
        status.get("currentMatchupPeriod") if isinstance(status, dict) else None,
    ):
        try:
            week = int(value)
        except (TypeError, ValueError):
            continue
        if week > 0:
            return week
    return None
