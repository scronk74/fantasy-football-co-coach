"""Command line entry point."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from ffcoach.advisors.draft import build_board
from ffcoach.cache import Cache
from ffcoach.check import LEAGUE_TZ, CheckError, SourceHealth, build_check
from ffcoach.config import (
    ConfigError,
    load_config,
    load_espn_credentials,
    load_notify_config,
)
from ffcoach.leagues.espn import parse_league
from ffcoach.leagues.espn_client import EspnUnavailable, fetch_league
from ffcoach.model.week import (
    MAX_WEEK,
    MIN_WEEK,
    WeekResolution,
    WeekUnavailable,
    resolve_week,
)
from ffcoach.notify.base import DeliveryError, Notification
from ffcoach.notify.heartbeat import Heartbeat
from ffcoach.notify.history import AlertHistory
from ffcoach.notify.message import notification_for
from ffcoach.notify.policy import QuietHours, decide
from ffcoach.notify.ntfy import ConsoleNotifier, NtfyNotifier
from ffcoach.report.build import board_payload, league_payload, write_board
from ffcoach.runlog import RunLog
from ffcoach.watchdog import WatchdogConfig, assess
from ffcoach.report.check_text import render_check
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
        ("check", "report whether this week's lineup needs fixing"),
        ("notify", "check the notification channel itself"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default="league.yaml", type=Path)
        p.add_argument("--cache", default=".ffcoach.sqlite3", type=Path)
        if name == "build":
            p.add_argument("--out", default=Path("web/data/board.json"), type=Path)
        if name == "check":
            p.add_argument(
                "--now",
                default=None,
                help=(
                    "ISO-8601 instant to check as, instead of the real clock. "
                    "Every deadline in the output depends on it, so this is how "
                    "the whole decision is exercised offline"
                ),
            )
            p.add_argument(
                "--no-look-ahead",
                action="store_true",
                help="skip next week's uncovered byes",
            )
            p.add_argument(
                "--notify",
                action="store_true",
                help="send the result to the configured channel",
            )
            p.add_argument(
                "--dry-run",
                action="store_true",
                help="with --notify, print the message instead of sending it",
            )
            p.add_argument(
                "--ignore-quiet-hours",
                action="store_true",
                help="send even between 23:00 and 08:00",
            )
            p.add_argument(
                "--log",
                default=Path(".ffcoach-runs.jsonl"),
                type=Path,
                help="append one JSON line per run here",
            )
        if name == "notify":
            p.add_argument(
                "--test",
                action="store_true",
                help="send one test message, to prove the channel works before you rely on it",
            )
        if name in ("check", "notify"):
            p.add_argument("--notify-config", default=Path("notify.yaml"), type=Path)
        if name == "league":
            p.add_argument("--out", default=Path("web/data/league.json"), type=Path)
        if name in ("league", "check"):
            p.add_argument("--espn-config", default=Path("espn.yaml"), type=Path)
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


def _load_league(args, cache: Cache):
    """`(League, SourceResult | None)`, or `None` after printing why not.

    Shared by `league` and `check` so the fixture path -- the one that needs no
    cookies and no network -- is the same code in both, rather than a second
    implementation that can drift from the one people actually run.
    """
    source = None
    if args.fixture:
        try:
            raw = args.fixture.read_text()
        except OSError as exc:
            print(f"error: could not read fixture: {exc}", file=sys.stderr)
            return None
        # Fixture mode used to leave `my_swid` None, so the demo produced a page
        # with no "your team" card while the page's own copy promised one.
        my_swid = args.my_swid
    else:
        try:
            creds = load_espn_credentials(args.espn_config)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return None
        try:
            source = fetch_league(
                creds.league_id, creds.season, creds.espn_s2, creds.swid, cache
            )
        except EspnUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return None
        raw = source.text
        my_swid = creds.swid

    try:
        return parse_league(raw, my_swid=my_swid), source
    except EspnUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _run_league(args, cache: Cache) -> int:
    loaded = _load_league(args, cache)
    if loaded is None:
        return 1
    league, source = loaded

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


# Exit codes. A check is run unattended long before anyone reads its output,
# so the status has to survive as a number.
EXIT_ALL_CLEAR = 0
EXIT_ERROR = 1
EXIT_ACTIONABLE = 2       # something you can still fix
EXIT_INCOMPLETE = 3       # nothing actionable, but this run was not a clean look


def _notifier(args):
    """The configured channel, or `None` after printing why not.

    `--dry-run` returns a real `ConsoleNotifier` rather than a flag the caller
    branches on, so the dry run walks the same path as a live send and cannot
    quietly stop matching it. It still loads the config first: a dry run that
    skips validation would happily "succeed" against a broken topic.
    """
    try:
        conf = load_notify_config(args.notify_config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    if args.dry_run:
        return ConsoleNotifier()
    try:
        return NtfyNotifier(conf.topic, conf.server)
    except DeliveryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _run_notify(args) -> int:
    """Prove the channel works before anything depends on it."""
    if not args.test:
        print("error: nothing to do; try `ffcoach notify --test`", file=sys.stderr)
        return EXIT_ERROR
    try:
        conf = load_notify_config(args.notify_config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        notifier = NtfyNotifier(conf.topic, conf.server)
        notifier.send(
            Notification(
                title="ffcoach test",
                body=(
                    "If you can read this, alerts will reach you. "
                    "This is the only message ffcoach sends that is not about your lineup."
                ),
                tier="interrupt",
            )
        )
    except DeliveryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    # Delivered is not the same as received: ntfy accepts a publish to a topic
    # nobody is subscribed to, so the only real confirmation is the user's phone.
    print(f"Sent one test message via {conf.channel}. Check your phone.")
    print("Nothing arrived? The topic in notify.yaml is not the one you subscribed to.")
    return EXIT_ALL_CLEAR


def _deliver(args, result, now, outcome: dict) -> int | None:
    """Send what the repeat policy allows. Returns an exit code only on failure.

    The order here is load-bearing: **decide, send, then record**. Recording
    before a send would spend a strike on a message that never arrived, and the
    second strike is the one that lands ninety minutes before kickoff.
    """
    notifier = _notifier(args)
    if notifier is None:
        return EXIT_ERROR

    # The history clock must be the check's clock, not the wall clock. With
    # `--now` they differ, and every "how long since the last alert" comparison
    # is then between a simulated instant and a real one -- silently wrong
    # everywhere the flag is used, and invisible in production where they agree.
    history = AlertHistory(args.cache, now=now.timestamp)
    quiet = QuietHours(enabled=not args.ignore_quiet_hours)
    plan = decide(
        result.actionable, result.week, history.records(), now, quiet, LEAGUE_TZ
    )

    # A suppressed alert is a decision, not an absence. Printed every time so
    # "you were not told" always has a visible reason attached to it.
    for reason in plan.held:
        print(f"  held: {reason}")
    outcome["held"] = len(plan.held)

    note = notification_for(result, LEAGUE_TZ, plan.send) if plan.send else None
    if note is None:
        # D-016: zero interrupts in a clean week is the system working. Said out
        # loud so "nothing sent" is never confused with a failure to send --
        # which is exactly what the dead-man's switch exists for.
        why = result.status if not plan.held else "everything held by policy"
        print(f"Nothing to send ({why}); no message dispatched.")
        return None

    try:
        notifier.send(note)
    except DeliveryError as exc:
        # A check that ran and could not be delivered is a different problem
        # from a check that could not run (D-024), and nothing is recorded --
        # so the next run tries again rather than counting a phantom strike.
        print(f"error: {exc}", file=sys.stderr)
        outcome["delivery_error"] = str(exc)
        return EXIT_ERROR

    # A dry run must not spend strikes: it delivered nothing.
    if notifier.name == "console":
        outcome["dry_run"] = True
        return None

    history.record(plan.keys_sent)
    outcome["sent"] = len(plan.send)
    outcome["channel"] = notifier.name
    print(f"Sent via {notifier.name} ({len(plan.send)} of {len(result.actionable)}).")
    return None


def _watch(args, run_log: RunLog, ok: bool) -> None:
    """E3: tell someone when the tool itself has stopped working.

    Never raises. This runs in a `finally`, so an exception here would replace
    the real failure with a confusing one, and the watchdog reporting an outage
    badly is worse than the outage.
    """
    try:
        _watch_body(args, run_log, ok)
    except Exception as exc:  # noqa: BLE001 -- see the docstring
        print(f"warning: the watchdog itself failed ({exc})", file=sys.stderr)


def _watch_body(args, run_log: RunLog, ok: bool) -> None:
    try:
        conf = load_notify_config(args.notify_config)
    except (ConfigError, AttributeError):
        return

    # Off-host half. Absence of this ping is what tells you the machine died,
    # so it goes out on every successful run regardless of --notify: it is
    # monitoring, not an alert, and suppressing it would fake a dead machine.
    if conf.has_heartbeat:
        error = Heartbeat(conf.heartbeat_url, conf.heartbeat_fail_url).ping(ok=ok)
        if error:
            print(f"warning: {error}", file=sys.stderr)

    if not getattr(args, "notify", False):
        return

    alert = assess(
        run_log.tail(50),
        dt.datetime.now(dt.UTC),
        WatchdogConfig(
            max_silence=dt.timedelta(hours=conf.max_silence_hours),
            min_consecutive_failures=conf.min_consecutive_failures,
        ),
    )
    if alert is None:
        return

    history = AlertHistory(args.cache)
    # One send per escalation step. A tripped watchdog is true on every run
    # until it is fixed, so without this it is the loudest thing you own.
    if history.counts().get(alert.key):
        return

    notifier = _notifier(args)
    if notifier is None:
        return
    try:
        notifier.send(
            Notification(title="ffcoach is not working", body=alert.reason,
                         tier="interrupt")
        )
    except DeliveryError as exc:
        print(f"warning: could not report the outage: {exc}", file=sys.stderr)
        return
    if notifier.name != "console":
        history.record([alert.key])
    print(f"warning: {alert.reason}", file=sys.stderr)


def _last_run_lines(run_log: RunLog) -> list[str]:
    """What `doctor` says about the last run, and the last one that worked.

    Both, deliberately. A recent *run* proves the scheduler is alive; a recent
    *success* proves it would have told you something. Reporting only the first
    is how a machine that has been erroring every fifteen minutes since
    Thursday reads as healthy.
    """
    last = run_log.tail(1)
    if not last:
        return ["Last run: never — nothing has run `ffcoach check` yet"]
    record = last[0]
    bits = [f"exit {record.get('exit_code', '?')}"]
    if record.get("status"):
        bits.append(str(record["status"]))
    if record.get("findings") is not None:
        bits.append(f"{record['findings']} found")
    if record.get("sent"):
        bits.append(f"{record['sent']} sent")
    if record.get("error"):
        bits.append(str(record["error"]))
    lines = [f"Last run: {record.get('at', '?')} — {', '.join(bits)}"]

    if not record.get("ok"):
        success = run_log.last_success()
        lines.append(
            f"Last OK:  {success['at']}" if success
            else "Last OK:  never — no run has ever completed"
        )
    return lines


def _run_log_for(args) -> RunLog:
    """A log that scrubs whatever credentials this invocation has in play.

    Loaded best-effort: a missing or malformed config must not stop the run
    from being logged, and an absent secret is simply one fewer thing to
    redact. Nothing here prints or stores the values themselves.
    """
    secrets: list[str] = []
    for loader, path in (
        (load_espn_credentials, getattr(args, "espn_config", None)),
        (load_notify_config, getattr(args, "notify_config", None)),
    ):
        if path is None:
            continue
        try:
            conf = loader(path)
        except ConfigError:
            continue
        secrets.extend(
            v for v in (
                getattr(conf, "espn_s2", None),
                getattr(conf, "swid", None),
                getattr(conf, "topic", None),
                # Whoever has the ping URL can forge a heartbeat, which makes
                # a dead machine look alive -- worse than no monitoring.
                getattr(conf, "heartbeat_url", None),
                getattr(conf, "heartbeat_fail_url", None),
            ) if v
        )
    return RunLog(args.log, secrets=secrets)


def _run_check(args, cache: Cache) -> int:
    """Compose the whole safety decision, say what it concluded, and log it.

    The logging is wrapped around everything in a `finally` rather than added
    at the end, because the runs worth diagnosing are the ones that crash. A
    check that raised and left no trace is exactly the silence E3 has to be
    able to tell apart from a clean week.
    """
    started = time.monotonic()
    record: dict = {"command": "check", "ok": False}
    run_log = _run_log_for(args)
    try:
        code = _check_body(args, cache, record)
        record["ok"] = code != EXIT_ERROR
        record["exit_code"] = code
        return code
    except Exception as exc:  # noqa: BLE001 -- re-raised below; logged first
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["exit_code"] = EXIT_ERROR
        raise
    finally:
        record["duration_ms"] = round((time.monotonic() - started) * 1000)
        run_log.append(record)
        # After the line is written, never before: the watchdog reads the log,
        # and this run is part of what it must see. Both halves run even when
        # the check itself failed -- a failed check is exactly what E3 is for.
        _watch(args, run_log, record.get("ok", False))


def _check_body(args, cache: Cache, record: dict) -> int:
    if args.now:
        try:
            now = dt.datetime.fromisoformat(args.now)
        except ValueError as exc:
            print(f"error: --now is not an ISO-8601 instant: {exc}", file=sys.stderr)
            return EXIT_ERROR
        if now.tzinfo is None:
            # A naive instant would silently be read as UTC, shifting every
            # deadline by hours. Refuse rather than pick a zone.
            print("error: --now needs a timezone offset, e.g. 2026-09-06T09:00-04:00",
                  file=sys.stderr)
            return EXIT_ERROR
    else:
        now = dt.datetime.now(dt.UTC)

    loaded = _load_league(args, cache)
    if loaded is None:
        return EXIT_ERROR
    league, source = loaded

    week = _resolve_week(league, cache, args.season)
    if week is None:
        return EXIT_ERROR
    record["week"] = week.week
    record["week_source"] = week.source

    try:
        schedule_raw = fetch_schedule(args.season, cache)
        schedule = parse_schedule(schedule_raw.text, args.season)
    except ScheduleUnavailable as exc:
        # Without a schedule there are no kickoffs, no byes and no deadlines --
        # every finding this tool makes is timed off one. Refusing beats
        # emitting an untimed answer that reads like a clean lineup.
        print(f"error: no NFL schedule, so no deadlines can be computed: {exc}",
              file=sys.stderr)
        return EXIT_ERROR

    sources = [SourceHealth("NFL schedule", schedule_raw.age_seconds,
                            schedule_raw.stale, schedule_raw.error)]
    if source is not None:
        sources.insert(0, SourceHealth("ESPN league", source.age_seconds,
                                       source.stale, source.error))

    try:
        result = build_check(
            league, schedule, week, now, sources,
            look_ahead=not args.no_look_ahead,
        )
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    record.update(
        status=result.status,
        findings=len(result.findings),
        actionable=len(result.actionable),
        blind_spots=list(result.blind_spots),
        sources=[
            {"name": s.name, "age_seconds": round(s.age_seconds), "stale": s.stale}
            for s in result.sources
        ],
    )

    for line in render_check(result, LEAGUE_TZ, league.name):
        print(line)

    if args.notify:
        rc = _deliver(args, result, now, record)
        if rc is not None:
            return rc

    if result.actionable:
        return EXIT_ACTIONABLE
    if result.all_clear:
        return EXIT_ALL_CLEAR
    return EXIT_INCOMPLETE


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

    if args.command == "check":
        return _run_check(args, cache)

    if args.command == "notify":
        return _run_notify(args)

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
        # Whether alerts have somewhere to go, never where. The topic is the
        # credential, and `doctor` output is what gets pasted into a bug report.
        try:
            notify_conf = load_notify_config(Path("notify.yaml"))
            print(f"Alerts:   {notify_conf.channel} configured ({notify_conf.server})")
            # Stated as an exposure, not as a missing option. An unconfigured
            # heartbeat is the difference between "the machine died and I was
            # told" and "the machine died".
            print(
                "Heartbeat: configured (off-host)" if notify_conf.has_heartbeat
                else "Heartbeat: NOT configured — if this machine dies, "
                     "nothing will tell you"
            )
        except ConfigError as exc:
            print(f"Alerts:   not configured — {exc}")
        # The diagnostic payoff of E1: "it has been quiet" and "it has been
        # broken since Thursday" look identical without this.
        for line in _last_run_lines(RunLog(Path(".ffcoach-runs.jsonl"))):
            print(line)
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
