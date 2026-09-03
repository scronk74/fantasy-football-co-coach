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
from ffcoach.sources.base import SourceResult, stale_fallback

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
    # None when the row exists but nflverse has not published a time yet --
    # flexed and international games carry a blank `gametime` for weeks. The
    # game is still real; only its clock is unknown.
    kickoff: dt.datetime | None


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

    def status(self, team: str, week: int) -> str:
        """`"playing"` | `"bye"` | `"unknown"` -- deliberately three values.

        A boolean forced two very different situations to share an answer.
        Rows with a missing kickoff used to be dropped at parse time, after
        which "this team has no game row" meant *bye*, and a Week 2 KC-DEN
        game whose time was still TBD made KC read as on bye. That is a
        data-quality gap being reported as the most certain fact this product
        emits.
        """
        team = normalize_team(team)
        if team not in self.teams:
            return "unknown"
        if (team, week) in self._by_team_week:
            return "playing"
        # A missing row is only evidence of a bye when it is the *single*
        # missing week. Every NFL team has exactly one. A team missing three
        # weeks has a truncated feed, not three byes, and saying "bye" would
        # turn a download that got cut off into three interrupt-priority
        # alerts. Same reasoning as the TBD-kickoff case: a data gap must
        # never be laundered into the most certain fact this product emits.
        return "bye" if self._byes.get(team) == week else "unknown"

    def is_on_bye(self, team: str, week: int) -> bool:
        return self.status(team, week) == "bye"

    def kickoff(self, team: str, week: int) -> dt.datetime | None:
        """When this team plays, or None if it does not play or the time is TBD.

        Ambiguous by design's standards, so callers that care about the
        difference ask `status()` and `kickoff_known()` instead of reading
        None as "no game".
        """
        game = self._by_team_week.get((normalize_team(team), week))
        return game.kickoff if game else None

    def kickoff_known(self, team: str, week: int) -> bool:
        game = self._by_team_week.get((normalize_team(team), week))
        return game is not None and game.kickoff is not None

    def lock_windows(self, week: int) -> list[dt.datetime]:
        """Distinct kickoff times in a week, ascending.

        Each is a separate deadline; alerts are batched per window. Games
        with an unpublished time contribute nothing here -- they cannot, and
        inventing a slot for them would create a deadline out of a blank cell.
        """
        return sorted({g.kickoff for g in self.games if g.week == week and g.kickoff})


def fetch_schedule(
    season: int, cache: Cache, client: httpx.Client | None = None
) -> SourceResult:
    key = _cache_key(season)
    hit = cache.get_with_age(key)
    if hit is not None:
        return SourceResult(text=hit[0], age_seconds=hit[1])

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        response = client.get(SCHEDULE_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return stale_fallback(cache, key, exc, ScheduleUnavailable, "NFL schedule")
    finally:
        if owns_client:
            client.close()

    # A truncated CSV download still arrives as a 200. Parse it before it is
    # allowed to replace a schedule we can still use.
    try:
        parse_schedule(response.text, season)
    except ScheduleUnavailable as exc:
        return stale_fallback(cache, key, exc, ScheduleUnavailable, "NFL schedule")

    cache.set(key, response.text, ttl_seconds=TTL_SECONDS)
    return SourceResult(text=response.text)


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
        # A row without both teams is not a game; a row without a *time* is.
        # Keeping the second kind is the whole point: dropping it turned a
        # TBD kickoff into a bye week.
        home_raw, away_raw = row.get("home_team"), row.get("away_team")
        if not home_raw or not away_raw or not row.get("week"):
            continue
        try:
            week = int(row["week"])
        except (TypeError, ValueError):
            continue
        kickoff = _kickoff(row.get("gameday"), row.get("gametime"))
        home = normalize_team(home_raw)
        away = normalize_team(away_raw)
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
