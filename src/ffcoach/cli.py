"""Command line entry point."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from ffcoach.advisors.draft import build_board
from ffcoach.cache import Cache
from ffcoach.config import ConfigError, load_config, load_espn_credentials
from ffcoach.leagues.espn import parse_league
from ffcoach.leagues.espn_client import EspnUnavailable, fetch_league
from ffcoach.model.week import (
    MAX_WEEK,
    MIN_WEEK,
    WeekResolution,
    WeekUnavailable,
    resolve_week,
)
from ffcoach.report.build import board_payload, league_payload, write_board
from ffcoach.sources.schedule import ScheduleUnavailable, fetch_schedule, parse_schedule
from ffcoach.sources.crosswalk import CrosswalkUnavailable, fetch_crosswalk, parse_crosswalk
from ffcoach.sources.ffcalc import AdpUnavailable, fetch_adp, parse_adp
from ffcoach.sources.base import freshest
from ffcoach.sources.match import enrich
from ffcoach.sources.sleeper import (
    PlayersUnavailable,
    fetch_players,
    parse_players,
    parse_players_by_id,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ffcoach")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("refresh", "fetch and cache player data"),
        ("build", "write web/data/board.json"),
        ("doctor", "report config and cache state"),
        ("league", "fetch ESPN league/roster data and write web/data/league.json"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default="league.yaml", type=Path)
        p.add_argument("--cache", default=".ffcoach.sqlite3", type=Path)
        if name == "build":
            p.add_argument("--out", default=Path("web/data/board.json"), type=Path)
        if name == "league":
            p.add_argument("--espn-config", default=Path("espn.yaml"), type=Path)
            p.add_argument("--out", default=Path("web/data/league.json"), type=Path)
            p.add_argument(
                "--fixture",
                type=Path,
                default=None,
                help="parse this JSON file instead of fetching ESPN (no cookies needed)",
            )
            p.add_argument(
                "--season",
                type=int,
                default=dt.date.today().year,
                help="NFL season, used to load the schedule for week resolution",
            )
            p.add_argument(
                "--my-swid",
                default=None,
                help=(
                    "with --fixture, which owner id counts as you, so the demo "
                    "exercises the pinned-team behavior the page promises"
                ),
            )

    return parser


def _load_players(config, cache):
    """Enriched players, plus how old the oldest input to them was."""
    adp = fetch_adp(config.scoring, config.teams, config.season, cache)
    players = parse_adp(adp.text)

    meta_raw = fetch_players(cache)
    meta = parse_players(meta_raw.text)
    meta_by_id = parse_players_by_id(meta_raw.text)

    # Identity is best-effort: if the crosswalk is unreachable the join
    # falls back to names, which is how this worked before it existed.
    crosswalk = None
    crosswalk_raw = None
    try:
        crosswalk_raw = fetch_crosswalk(cache)
        crosswalk = parse_crosswalk(crosswalk_raw.text)
    except CrosswalkUnavailable as exc:
        print(f"note: player crosswalk unavailable, matching by name only: {exc}", file=sys.stderr)

    for result, label in ((adp, "ADP"), (meta_raw, "Sleeper players"), (crosswalk_raw, "crosswalk")):
        if result is not None and result.stale:
            print(
                f"warning: serving cached {label} from {_age(result.age_seconds)} ago; "
                f"the live fetch failed ({result.error})",
                file=sys.stderr,
            )

    result = enrich(players, meta, crosswalk=crosswalk, meta_by_id=meta_by_id)
    # The crosswalk is a join table: it puts no number on the board, it only
    # binds one source's id to another's. Its age is not the board's age; its
    # staleness still is. See sources/base.freshest.
    return result, freshest(adp, meta_raw, lookups=(crosswalk_raw,))


def _age(seconds: float) -> str:
    """Human duration for a log line. Rounded: false precision reads as fact."""
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 90 * 60:
        return f"{int(seconds / 60)}m"
    if seconds < 48 * 3600:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _run_league(args, cache: Cache) -> int:
    source = None
    if args.fixture:
        try:
            raw = args.fixture.read_text()
        except OSError as exc:
            print(f"error: could not read fixture: {exc}", file=sys.stderr)
            return 1
        # Fixture mode used to leave `my_swid` None, so the demo produced a page
        # with no "your team" card while the page's own copy promised one.
        my_swid = args.my_swid
    else:
        try:
            creds = load_espn_credentials(args.espn_config)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            source = fetch_league(
                creds.league_id, creds.season, creds.espn_s2, creds.swid, cache
            )
        except EspnUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raw = source.text
        my_swid = creds.swid

    try:
        league = parse_league(raw, my_swid=my_swid)
    except EspnUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # No caller may invent a week. Resolve it once, here, and say where it
    # came from -- a derived week is a fallback, not a fact.
    week = _resolve_week(league, cache, args.season)
    if week is None:
        return 1

    age_seconds, stale = freshest(source)
    payload = league_payload(
        league,
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        age_seconds=age_seconds,
        stale=stale,
        week=week.week,
        week_source=week.source,
    )
    write_board(payload, args.out)
    print(f"Wrote {len(league.teams)} teams to {args.out} — {week.note}")
    if stale and source is not None:
        print(
            f"warning: this is cached ESPN data from {_age(source.age_seconds)} ago; "
            f"the live fetch failed ({source.error})",
            file=sys.stderr,
        )
    if week.is_derived:
        print(f"note: {week.note}", file=sys.stderr)
    # The lineup-lock rule silently rescales every deadline this tool emits, so
    # an assumed or unrecognized value is said out loud rather than absorbed.
    if league.lineup_lock.note:
        print(f"note: {league.lineup_lock.note}", file=sys.stderr)
    # Anything the adapter could not interpret. An unrecognized slot id means a
    # starter may be miscategorized, which is worth a line on every run.
    for note in league.diagnostics:
        print(f"note: ESPN data: {note}", file=sys.stderr)
    return 0


def _resolve_week(league, cache: Cache, season: int):
    """Establish the current week, or explain why we refuse to guess.

    ESPN's number short-circuits before the schedule is fetched at all: it is
    authoritative, so loading a schedule to second-guess it would be wasted
    work and would make the common path depend on the network.
    """
    if MIN_WEEK <= (league.current_week or 0) <= MAX_WEEK:
        return WeekResolution(week=league.current_week, source="espn")

    try:
        schedule = parse_schedule(fetch_schedule(season, cache).text, season)
    except ScheduleUnavailable as exc:
        print(f"error: no week from ESPN and no schedule to derive one: {exc}", file=sys.stderr)
        return None

    try:
        return resolve_week(league.current_week, schedule, dt.datetime.now(dt.UTC))
    except WeekUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cache = Cache(args.cache)

    if args.command == "league":
        return _run_league(args, cache)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "doctor":
        print(f"League:   {config.name} ({config.season})")
        print(f"Format:   {config.scoring}, {config.teams} teams")
        print(f"Your pick: {config.my_pick} -> next {config.next_pick_after(config.my_pick)}")
        print(f"Cache:    {args.cache}")
        return 0

    try:
        result, (age_seconds, stale) = _load_players(config, cache)
    except (AdpUnavailable, PlayersUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    players, unmatched, fuzzy = result.players, result.unmatched, result.fuzzy

    if args.command == "refresh":
        print(f"Cached {len(players)} players; {len(unmatched)} unmatched.")
        return 0

    rows = build_board(players, config)
    payload = board_payload(
        rows,
        config,
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        unmatched=unmatched,
        age_seconds=age_seconds,
        stale=stale,
    )
    write_board(payload, args.out)
    print(f"Wrote {len(rows)} players to {args.out}")
    if unmatched:
        print(f"note: {len(unmatched)} players had no Sleeper match", file=sys.stderr)
    if fuzzy:
        print(
            f"note: {len(fuzzy)} players matched only by surname: {', '.join(fuzzy)}",
            file=sys.stderr,
        )
    return 0
