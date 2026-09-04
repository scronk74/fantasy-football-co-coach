"""Command line entry point."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from ffcoach.agent import (
    DEFAULT_INTERVAL_MINUTES,
    LABEL,
    AgentError,
    agent_plist_path,
    build_agent,
    plist_bytes,
)
from ffcoach.advisors.draft import build_board
from ffcoach.cache import Cache
from ffcoach.check import LEAGUE_TZ, CheckError, SourceHealth, build_check
from ffcoach.config import (
    ConfigError,
    load_config,
    load_espn_credentials,
    load_notify_config,
    new_topic,
    write_notify_config,
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
from ffcoach.report.build import (
    board_payload,
    check_payload,
    league_payload,
    write_board,
)
from ffcoach.runlog import RunLog
from ffcoach.serve import (
    ALL_INTERFACES,
    DEFAULT_PORT,
    LOCALHOST,
    ServeError,
    build_server,
    lan_address,
    web_root,
)
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
        ("schedule", "run the check automatically via launchd"),
        ("serve", "serve the pages over HTTP"),
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
            p.add_argument(
                "--out",
                default=Path("web/data/check.json"),
                type=Path,
                help="write the payload the Week page reads",
            )
            p.add_argument(
                "--no-write",
                action="store_true",
                help="do not write the Week page payload",
            )
        if name == "notify":
            p.add_argument(
                "--init",
                action="store_true",
                help="create notify.yaml with a fresh, unguessable ntfy topic",
            )
            p.add_argument(
                "--force",
                action="store_true",
                help="with --init, replace an existing notify.yaml",
            )
            p.add_argument(
                "--test",
                action="store_true",
                help="send one test message, to prove the channel works before you rely on it",
            )
        if name == "serve":
            p.add_argument("--port", type=int, default=DEFAULT_PORT)
            p.add_argument(
                "--lan",
                action="store_true",
                help=(
                    "listen on every interface so other devices on your network "
                    "can read the pages (they contain your roster)"
                ),
            )
            p.add_argument(
                "--open", dest="open_browser", action="store_true",
                help="open a browser at the served page",
            )
        if name == "schedule":
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument("--install", action="store_true",
                               help="write the launchd agent and load it")
            group.add_argument("--uninstall", action="store_true",
                               help="unload the agent and remove it")
            group.add_argument("--status", action="store_true",
                               help="is it loaded, and when did it last run")
            group.add_argument("--print", dest="print_only", action="store_true",
                               help="print the plist without writing anything")
            p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_MINUTES,
                           help="minutes between checks (5-240)")
            p.add_argument("--log", default=Path(".ffcoach-runs.jsonl"), type=Path)
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


def _launchctl(*argv: str) -> tuple[int, str]:
    """Run `launchctl`, returning its code and combined output.

    Isolated so the tests can replace exactly one function. Everything above it
    -- the plist, the validation, the messages -- is verifiable; this call is
    the part R-2 says never can be.
    """
    import subprocess

    proc = subprocess.run(
        ["launchctl", *argv], capture_output=True, text=True, check=False
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _current_agent(args):
    """Build the agent for this working directory, or explain why not."""
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        raise AgentError(
            "uv is not on PATH here, so its absolute path cannot be recorded. "
            "launchd has no PATH of its own and would fail silently."
        )
    return build_agent(Path.cwd(), Path(uv), args.interval)


def _run_serve(args) -> int:
    """Serve `web/` until interrupted."""
    try:
        root = web_root()
        host = ALL_INTERFACES if args.lan else LOCALHOST
        server = build_server(root, host, args.port)
    except ServeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Serving {root} — press Ctrl-C to stop.")
    print(f"  http://{LOCALHOST}:{args.port}/")
    if args.lan:
        address = lan_address()
        if address:
            print(f"  http://{address}:{args.port}/   (other devices on your network)")
        # Said plainly rather than buried in --help: the pages carry the user's
        # roster and league. Not credentials -- those never leave the repo root,
        # which is not served -- but not something to broadcast unknowingly.
        print()
        print("  Listening on every interface. Anyone on this network can read")
        print("  your roster and league. Use plain `ffcoach serve` to keep it local.")
    if args.open_browser:
        import webbrowser

        webbrowser.open(f"http://{LOCALHOST}:{args.port}/")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return EXIT_ALL_CLEAR


def _is_macos() -> bool:
    """Its own function so the tests can stub it.

    CI runs on Linux, and gating on `sys.platform` inline meant every branch
    below was unreachable there -- the whole command would have been covered
    only on the author's laptop. That is the same gap R-2 already regrets about
    `launchctl`, and there is no reason to widen it to code that is perfectly
    testable anywhere.
    """
    return sys.platform == "darwin"


def _run_schedule(args) -> int:
    if not _is_macos() and not args.print_only:
        # cron is not an acceptable substitute (D-022) and pretending otherwise
        # would ship a scheduler that skips every job missed during sleep.
        print("error: launchd is macOS-only; this machine is not macOS.",
              file=sys.stderr)
        return EXIT_ERROR

    if args.status:
        return _schedule_status(args)

    if args.uninstall:
        return _schedule_uninstall()

    try:
        agent = _current_agent(args)
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.print_only:
        sys.stdout.write(plist_bytes(agent).decode())
        return EXIT_ALL_CLEAR

    path = agent_plist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plist_bytes(agent))
    except OSError as exc:
        print(f"error: could not write {path}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    # bootout first, so re-installing after an edit actually takes effect
    # rather than leaving the old definition loaded. Its failure is expected
    # and ignored: nothing is loaded on a first install.
    _launchctl("bootout", agent.service_target)
    code, output = _launchctl("bootstrap", agent.domain_target, str(path))
    if code != 0:
        print(f"error: launchctl bootstrap failed: {output}", file=sys.stderr)
        print(f"note: the plist is written at {path}; nothing is scheduled.",
              file=sys.stderr)
        return EXIT_ERROR

    print(f"Scheduled: every {agent.interval_minutes} minutes, starting now.")
    print(f"  plist    {path}")
    print(f"  runs in  {agent.working_dir}")
    print(f"  stderr   {agent.stderr_path}")
    print()
    print("It will run once immediately (RunAtLoad). Check with:")
    print("  uv run ffcoach schedule --status")
    return EXIT_ALL_CLEAR


def _schedule_uninstall() -> int:
    import os

    path = agent_plist_path()
    code, output = _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    path.unlink(missing_ok=True)
    if code != 0 and "No such process" not in output:
        print(f"warning: launchctl bootout said: {output}", file=sys.stderr)
    print(f"Unscheduled. Removed {path}.")
    return EXIT_ALL_CLEAR


def _schedule_status(args) -> int:
    """Loaded, and did it actually do anything.

    Both, deliberately, and for the same reason `doctor` reports two lines: a
    loaded agent proves launchd accepted the plist, and proves nothing at all
    about whether the job runs, succeeds, or reaches your phone. R-2 is exactly
    the gap between those two facts.
    """
    import os

    path = agent_plist_path()
    print(f"Plist:    {path}{'' if path.exists() else '  (absent)'}")

    code, output = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    if code != 0:
        print("Loaded:   no — nothing is scheduled")
    else:
        state = next(
            (ln.strip() for ln in output.splitlines() if ln.strip().startswith("state =")),
            "state = unknown",
        )
        print(f"Loaded:   yes ({state})")

    for line in _last_run_lines(RunLog(args.log)):
        print(line)
    if code == 0 and not RunLog(args.log).tail(1):
        print("note: loaded but nothing has run yet — check the stderr log.")
    return EXIT_ALL_CLEAR


def _run_notify(args) -> int:
    """Set the channel up, and prove it works before anything depends on it."""
    if args.init:
        return _run_notify_init(args)
    if not args.test:
        print("error: nothing to do; try `ffcoach notify --init` or `--test`",
              file=sys.stderr)
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


def _deliver(args, result, now, outcome: dict, tz) -> int | None:
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
        result.actionable, result.week, history.records(), now, quiet, tz
    )

    # A suppressed alert is a decision, not an absence. Printed every time so
    # "you were not told" always has a visible reason attached to it.
    for reason in plan.held:
        print(f"  held: {reason}")
    outcome["held"] = len(plan.held)

    note = notification_for(result, tz, plan.send) if plan.send else None
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


def _run_notify_init(args) -> int:
    """Create `notify.yaml` with a fresh topic and say what to do next.

    The topic is generated here rather than asked for. Left to a human it
    becomes "ffcoach" or "steve-fantasy" -- and a public ntfy topic has no
    authentication, so a guessable name is a stranger reading your alerts and
    publishing fake ones to your phone.
    """
    topic = new_topic()
    try:
        write_notify_config(args.notify_config, topic, force=args.force)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: could not write {args.notify_config}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Wrote {args.notify_config} (gitignored, mode 600).")
    print()
    print("Next, on your phone:")
    print("  1. Install ntfy — free, no account, iOS or Android.")
    print("  2. Subscribe to this exact topic:")
    print()
    print(f"       {topic}")
    print()
    print(f"     Or open  https://ntfy.sh/{topic}  and tap Subscribe.")
    print("  3. Come back and run:  uv run ffcoach notify --test")
    print()
    print("That topic is a credential — anyone who has it can read your alerts")
    print("and send you fake ones. Do not paste it into a chat or an issue.")
    return EXIT_ALL_CLEAR


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


def _league_timezone(args):
    """`(tzinfo, blind-spot note or None)`.

    ESPN publishes no timezone, so this is stated in `league.yaml` rather than
    derived. When that file cannot be read the fallback is used **and said out
    loud**: a silently assumed zone shifts every waiver deadline by hours while
    the tool goes on stating them as fact, which is the failure this codebase
    keeps rediscovering.
    """
    try:
        return load_config(args.config).tzinfo, None
    except ConfigError as exc:
        return LEAGUE_TZ, (
            f"timezone assumed {LEAGUE_TZ.key}: {exc}. "
            "Waiver deadlines may be hours off"
        )


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

    tz, tz_note = _league_timezone(args)
    record["timezone"] = str(tz)

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

    if tz_note:
        sources.append(SourceHealth(tz_note, 0.0, True))

    try:
        result = build_check(
            league, schedule, week, now, sources, tz=tz,
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

    for line in render_check(result, tz, league.name):
        print(line)

    if not args.no_write:
        payload = check_payload(
            result,
            league_name=league.name,
            generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            timezone=str(tz),
        )
        try:
            write_board(payload, args.out)
        except OSError as exc:
            # The page going stale is worth a warning; it is not worth losing
            # the alert this run exists to send.
            print(f"warning: could not write {args.out}: {exc}", file=sys.stderr)

    if args.notify:
        rc = _deliver(args, result, now, record, tz)
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

    if args.command == "schedule":
        return _run_schedule(args)

    if args.command == "serve":
        return _run_serve(args)

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
