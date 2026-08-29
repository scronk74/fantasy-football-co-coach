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
from ffcoach.report.build import board_payload, league_payload, write_board
from ffcoach.sources.ffcalc import AdpUnavailable, fetch_adp, parse_adp
from ffcoach.sources.match import enrich
from ffcoach.sources.sleeper import PlayersUnavailable, fetch_players, parse_players


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

    return parser


def _load_players(config, cache):
    raw_adp = fetch_adp(config.scoring, config.teams, config.season, cache)
    players = parse_adp(raw_adp)
    meta = parse_players(fetch_players(cache))
    return enrich(players, meta)


def _run_league(args, cache: Cache) -> int:
    if args.fixture:
        try:
            raw = args.fixture.read_text()
        except OSError as exc:
            print(f"error: could not read fixture: {exc}", file=sys.stderr)
            return 1
        my_swid = None
    else:
        try:
            creds = load_espn_credentials(args.espn_config)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            raw = fetch_league(creds.league_id, creds.season, creds.espn_s2, creds.swid, cache)
        except EspnUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        my_swid = creds.swid

    try:
        league = parse_league(raw, my_swid=my_swid)
    except EspnUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = league_payload(
        league,
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        stale_seconds=None,
    )
    write_board(payload, args.out)
    print(f"Wrote {len(league.teams)} teams to {args.out}")
    return 0


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
        players, unmatched = _load_players(config, cache)
    except (AdpUnavailable, PlayersUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "refresh":
        print(f"Cached {len(players)} players; {len(unmatched)} unmatched.")
        return 0

    rows = build_board(players, config)
    payload = board_payload(
        rows,
        config,
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        unmatched=unmatched,
        stale_seconds=None,
    )
    write_board(payload, args.out)
    print(f"Wrote {len(rows)} players to {args.out}")
    if unmatched:
        print(f"note: {len(unmatched)} players had no Sleeper match", file=sys.stderr)
    return 0
