"""What state is this installation actually in?

E1 and E3 already record everything here -- the run log knows when a check last
succeeded, the watchdog knows whether the tool has stopped working, `doctor`
knows which setup steps remain. All of it lives in a JSONL file and a terminal
command, which is to say: nowhere the user looks on a Sunday morning.

**Generated per request, never written to a file.** A health panel served from
a stale snapshot is self-refuting -- it would report "last run 3 minutes ago"
from a file written three hours ago. That is the one thing this page exists to
make impossible, so the freshness cannot itself be cached.

**No secret ever appears in the payload.** Not the ntfy topic, not the
heartbeat URL, not the ESPN cookies. Only whether each is configured. This JSON
is served over the LAN when `serve --lan` is on, and is the thing a person
screenshots when asking for help.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ffcoach.agent import DEFAULT_INTERVAL_MINUTES, LABEL, agent_plist_path
from ffcoach.config import ConfigError, load_notify_config
from ffcoach.host import is_scheduler_host, this_host
from ffcoach.runlog import RunLog
from ffcoach.watchdog import WatchdogConfig, assess


def _age_seconds(iso: str | None, now: dt.datetime) -> float | None:
    if not iso:
        return None
    try:
        when = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return (now - when).total_seconds()


def _run_summary(record: dict | None, now: dt.datetime) -> dict | None:
    if record is None:
        return None
    return {
        "at": record.get("at"),
        "age_seconds": _age_seconds(record.get("at"), now),
        "ok": bool(record.get("ok")),
        "status": record.get("status"),
        "week": record.get("week"),
        "findings": record.get("findings"),
        "actionable": record.get("actionable"),
        "sent": record.get("sent"),
        "exit_code": record.get("exit_code"),
        "error": record.get("error"),
        # Present when a non-scheduler machine declined to send (D-072).
        "suppressed_host": record.get("suppressed_host"),
        "sources": record.get("sources") or [],
    }


def health_payload(
    log_path: Path,
    notify_path: Path,
    now: dt.datetime,
    plist_exists: bool | None = None,
    agent_loaded: bool | None = None,
    setup_steps: list[tuple[bool, str, str]] | None = None,
) -> dict:
    """Everything the panel shows, built fresh.

    `agent_loaded` is passed in rather than looked up: it costs a `launchctl`
    subprocess, which does not belong inside a request handler that is also
    unit-tested. `None` means "not determined", and the page renders that as
    unknown rather than as healthy -- absence is not evidence.
    """
    run_log = RunLog(log_path)
    last = run_log.tail(1)
    last_record = last[0] if last else None
    last_success = run_log.last_success()

    alerts: dict = {"configured": False, "channel": None, "reason": None}
    heartbeat = {"configured": False}
    scheduler: dict = {
        "host": None,
        "is_this_machine": True,
        "plist_exists": plist_exists,
        "loaded": agent_loaded,
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "label": LABEL,
    }
    watchdog: dict = {"tripped": False, "reason": None}

    try:
        conf = load_notify_config(notify_path)
    except ConfigError as exc:
        alerts["reason"] = str(exc)
        conf = None

    if conf is not None:
        # Whether, never which. The topic is a credential (D-058) and the
        # heartbeat URL is one too -- a forged ping makes a dead machine look
        # alive.
        alerts.update(configured=True, channel=conf.channel)
        heartbeat["configured"] = conf.has_heartbeat
        scheduler["host"] = conf.scheduler_host or None
        scheduler["is_this_machine"] = is_scheduler_host(conf.scheduler_host)

        alert = assess(
            run_log.tail(50),
            now,
            WatchdogConfig(
                max_silence=dt.timedelta(hours=conf.max_silence_hours),
                min_consecutive_failures=conf.min_consecutive_failures,
            ),
        )
        if alert is not None:
            watchdog = {"tripped": True, "reason": alert.reason}

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "host": this_host(),
        "alerts": alerts,
        "heartbeat": heartbeat,
        "scheduler": scheduler,
        "watchdog": watchdog,
        "last_run": _run_summary(last_record, now),
        "last_success": _run_summary(last_success, now),
        "setup": [
            {"done": done, "what": what, "fix": fix}
            for done, what, fix in (setup_steps or [])
        ],
    }


def plist_present() -> bool:
    try:
        return agent_plist_path().exists()
    except OSError:
        return False
