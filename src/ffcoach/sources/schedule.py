"""NFL schedule: bye weeks and per-game kickoff times.

Two things the alerting system cannot work without, and neither is available
from ESPN's league API:

* **Bye weeks**, derived rather than stated -- a team is on bye in the week it
  has no game. Alerting on a bye-week starter is the single most certain
  finding the product makes.
* **Kickoff times**, because an NFL week does not lock all at once. Week 8 of
  2025 has six distinct windows (Thu 20:15, Sun 13:00/16:05/16:25/20:20, Mon
  20:15). One weekly sweep would fire uselessly early for some players and far
  too late for others, so every alert is timed off its own player's kickoff.

Source is nflverse, free and unauthenticated.

**Team abbreviations disagree between sources and must be normalized.** nflverse
writes `LA` and `WAS`; ESPN writes `LAR` and `WSH`. Left alone, Rams and
Commanders starters would silently never match a schedule row and never alert on
a bye -- precisely the failure this product exists to prevent. `_TEAM_ALIASES`
below maps nflverse to the ESPN spelling used everywhere else in this codebase,
and a test asserts all 32 teams round-trip.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx

from ffcoach.cache import Cache

SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
# Flex scheduling moves kickoff times mid-season, so this cannot be cached for
# long the way player identity can.
TTL_SECONDS = 12 * 60 * 60

EASTERN = ZoneInfo("America/New_York")

# nflverse spelling -> the ESPN spelling used elsewhere in this codebase.
_TEAM_ALIASES = {"LA": "LAR", "WAS": "WSH"}


class ScheduleUnavailable(Exception):
    """Raised when the NFL schedule cannot be fetched or parsed."""


def _cache_key(season: int) -> str:
    return f"schedule:nflverse:{season}"


def normalize_team(team: str) -> str:
    team = (team or "").strip().upper()
    return _TEAM_ALIASES.get(team, team)


@dataclass(frozen=True)
class Game:
    week: int
    team: str
    opponent: str
    kickoff: dt.datetime  # timezone-aware


class Schedule:
    """One season's games, indexed for the two questions alerting asks."""

    def __init__(self, season: int, games: list[Game]):
        self.season = season
        self.games = games
        self._by_team_week: dict[tuple[str, int], Game] = {
            (g.team, g.week): g for g in games
        }
        self.teams: set[str] = {g.team for g in games}
        self.weeks: set[int] = {g.week for g in games}

        # A team is on bye in a regular-season week it has no game.
        self._byes: dict[str, int] = {}
        for team in self.teams:
            missing = sorted(w for w in self.weeks if (team, w) not in self._by_team_week)
            if len(missing) == 1:
                self._byes[team] = missing[0]

    def bye_week(self, team: str) -> int | None:
        return self._byes.get(normalize_team(team))

    def is_on_bye(self, team: str, week: int) -> bool:
        team = normalize_team(team)
        if team not in self.teams:
            return False
        return (team, week) not in self._by_team_week

    def kickoff(self, team: str, week: int) -> dt.datetime | None:
        game = self._by_team_week.get((normalize_team(team), week))
        return game.kickoff if game else None

    def lock_windows(self, week: int) -> list[dt.datetime]:
        """Distinct kickoff times in a week, ascending.

        Each is a separate deadline; alerts are batched per window.
        """
        return sorted({g.kickoff for g in self.games if g.week == week})


def fetch_schedule(season: int, cache: Cache, client: httpx.Client | None = None) -> str:
    key = _cache_key(season)
    cached = cache.get(key)
    if cached is not None:
        return cached

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        response = client.get(SCHEDULE_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stale = cache.get_stale(key)
        if stale is not None:
            return stale[0]
        raise ScheduleUnavailable(
            f"could not fetch NFL schedule and no cached copy exists: {exc}"
        ) from exc
    finally:
        if owns_client:
            client.close()

    cache.set(key, response.text, ttl_seconds=TTL_SECONDS)
    return response.text


def parse_schedule(raw: str, season: int) -> Schedule:
    """Pure: CSV text in, Schedule for one season out.

    Regular season only. Playoff weeks reuse week numbers and would corrupt
    bye derivation.
    """
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except csv.Error as exc:
        raise ScheduleUnavailable(f"could not parse NFL schedule CSV: {exc}") from exc

    if rows and "gameday" not in rows[0]:
        raise ScheduleUnavailable(
            f"could not parse NFL schedule: no 'gameday' column; got {sorted(rows[0])[:6]}"
        )

    games: list[Game] = []
    for row in rows:
        if row.get("season") != str(season) or row.get("game_type") != "REG":
            continue
        kickoff = _kickoff(row.get("gameday"), row.get("gametime"))
        if kickoff is None:
            continue
        week = int(row["week"])
        home = normalize_team(row["home_team"])
        away = normalize_team(row["away_team"])
        games.append(Game(week=week, team=home, opponent=away, kickoff=kickoff))
        games.append(Game(week=week, team=away, opponent=home, kickoff=kickoff))

    if not games:
        raise ScheduleUnavailable(f"no regular-season games found for {season}")

    return Schedule(season=season, games=games)


def _kickoff(gameday: str | None, gametime: str | None) -> dt.datetime | None:
    """Combine nflverse's date and Eastern clock time into an aware datetime."""
    if not gameday or not gametime:
        return None
    try:
        day = dt.date.fromisoformat(gameday.strip())
        hour, minute = (int(part) for part in gametime.strip().split(":")[:2])
    except (ValueError, TypeError):
        return None
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=EASTERN)
