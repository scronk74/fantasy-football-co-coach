import json
from pathlib import Path

import pytest

from ffcoach.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
LEAGUE = """
name: Test League
season: 2026
teams: 12
scoring: ppr
my_pick: 7
roster: {QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DEF: 1, BN: 6}
"""


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "league.yaml").write_text(LEAGUE)
    cache_db = tmp_path / "c.sqlite3"

    from ffcoach.cache import Cache
    from ffcoach.sources.ffcalc import _cache_key
    from ffcoach.sources.sleeper import CACHE_KEY

    cache = Cache(cache_db)
    cache.set(_cache_key("ppr", 12, 2026), (FIXTURES / "ffc_ppr_12.json").read_text(), 3600)
    cache.set(CACHE_KEY, (FIXTURES / "sleeper_players.json").read_text(), 3600)
    return tmp_path


def test_build_writes_the_board(workspace):
    out = workspace / "web" / "data" / "board.json"
    code = main([
        "build",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["players"]
    assert payload["league"]["next_pick"] == 18


def test_build_ranks_players_from_one(workspace):
    out = workspace / "board.json"
    main([
        "build",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
        "--out", str(out),
    ])
    ranks = [r["rank"] for r in json.loads(out.read_text())["players"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_missing_config_exits_nonzero_with_a_clear_message(tmp_path, capsys):
    code = main([
        "build",
        "--config", str(tmp_path / "absent.yaml"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "b.json"),
    ])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_doctor_reports_config_and_cache(workspace, capsys):
    code = main([
        "doctor",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "Test League" in out
    assert "ppr" in out


def test_unknown_command_exits_nonzero(capsys):
    with pytest.raises(SystemExit):
        main(["nonsense"])


def test_league_writes_teams_from_fixture(tmp_path):
    out = tmp_path / "web" / "data" / "league.json"
    code = main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert len(payload["teams"]) == 2


def test_league_fixture_mode_needs_no_espn_config(tmp_path):
    # No espn.yaml exists at all in this tmp_path -- fixture mode must not
    # require one.
    out = tmp_path / "league.json"
    code = main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
        "--espn-config", str(tmp_path / "does-not-exist.yaml"),
    ])
    assert code == 0


def test_league_missing_espn_config_exits_nonzero_without_fixture(tmp_path):
    code = main([
        "league",
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "league.json"),
        "--espn-config", str(tmp_path / "absent-espn.yaml"),
    ])
    assert code == 1


def test_league_takes_the_week_from_espn(tmp_path):
    """The fixture carries scoringPeriodId=5.

    ESPN's number short-circuits before any schedule fetch, so this needs no
    network and no cached schedule.
    """
    out = tmp_path / "league.json"
    code = main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
        "--season", "2025",
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["week"] == 5
    assert payload["week_source"] == "espn"


def test_league_payload_carries_roster_slots(tmp_path):
    """Needed by the empty-slot check; must survive to the browser."""
    out = tmp_path / "league.json"
    main([
        "league",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(out),
        "--season", "2025",
    ])
    slots = json.loads(out.read_text())["league"]["roster_slots"]
    assert slots["RB"] == 2
    assert slots["FLEX"] == 1


def test_league_refuses_rather_than_guessing_the_week(tmp_path):
    """No week from ESPN and no schedule available: exit nonzero, never default."""
    stripped = json.loads((FIXTURES / "espn_league.json").read_text())
    stripped.pop("scoringPeriodId", None)
    stripped.get("status", {}).pop("currentMatchupPeriod", None)
    fixture = tmp_path / "no_week.json"
    fixture.write_text(json.dumps(stripped))

    cache_db = tmp_path / "c.sqlite3"
    from ffcoach.cache import Cache
    from ffcoach.sources.schedule import _cache_key
    # Seed an empty schedule so nothing reaches the network.
    Cache(cache_db).set(_cache_key(2025), "game_id,season,game_type,week,gameday\n", 3600)

    code = main([
        "league",
        "--fixture", str(fixture),
        "--cache", str(cache_db),
        "--out", str(tmp_path / "league.json"),
        "--season", "2025",
    ])
    assert code == 1


def test_league_missing_fixture_file_exits_nonzero(tmp_path):
    code = main([
        "league",
        "--fixture", str(tmp_path / "nope.json"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "league.json"),
    ])
    assert code == 1


# --- `ffcoach check` (C7.2): the whole safety decision, offline ---

SWID = "{ABCDEF12-3456-7890-ABCD-EF1234567890}"


@pytest.fixture
def checkable(tmp_path):
    """A cache holding the NFL schedule, so `check` needs no network."""
    from ffcoach.cache import Cache
    from ffcoach.sources.schedule import _cache_key

    db = tmp_path / "c.sqlite3"
    cache = Cache(db)
    cache.set(_cache_key(2025), (FIXTURES / "nfl_schedule_2025.csv").read_text(), 3600)
    return db


def run_check(db, *extra):
    return main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(db),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T09:00-04:00",
        *extra,
    ])


def test_check_runs_end_to_end_with_no_cookies_and_no_network(checkable, capsys):
    """The point of C7: the safety decision is exercisable offline.

    Before this, `find_problems()` appeared exactly once under `src/` -- at its
    own definition. Nothing ran the detection this whole stage built.
    """
    code = run_check(checkable)
    out = capsys.readouterr().out
    assert code == 2  # actionable problems exist in the fixture roster
    assert "week 5 (from espn)" in out
    assert "to fix" in out


def test_check_reports_the_empty_slots_the_fixture_roster_has(checkable, capsys):
    code = run_check(checkable)
    out = capsys.readouterr().out
    assert code == 2
    assert "EMPTY" in out
    assert "no one in this slot" in out


def test_check_names_the_next_lock_and_the_waiver_deadline(checkable, capsys):
    run_check(checkable)
    out = capsys.readouterr().out
    assert "Next slot freezes:" in out
    assert "Waivers next process:" in out


def test_check_exits_nonzero_when_no_team_is_marked_as_yours(checkable, capsys):
    """Never falls back to teams[0] -- that reports a stranger's roster as yours."""
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--now", "2025-10-01T09:00-04:00",
    ])
    assert code == 1
    assert "no team" in capsys.readouterr().err


def test_check_refuses_a_naive_now_rather_than_assuming_utc(checkable, capsys):
    """Reading a naive instant as UTC shifts every deadline by hours."""
    code = run_check(checkable, )
    assert code == 2
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T09:00",
    ])
    assert code == 1
    assert "timezone" in capsys.readouterr().err


def test_check_refuses_an_unparseable_now(checkable, capsys):
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "next tuesday",
    ])
    assert code == 1
    assert "ISO-8601" in capsys.readouterr().err


def test_check_refuses_rather_than_reporting_undated_findings(tmp_path, capsys):
    """No usable schedule means no kickoffs, no byes and no deadlines.

    Every finding this tool makes is timed off one, so an answer without a
    schedule would read like a clean lineup rather than an unknown one.

    The cached body here is a well-formed CSV that is not a schedule -- the
    same shape as a captive portal or a truncated download, and the case that
    a status-code check alone would wave through.
    """
    from ffcoach.cache import Cache
    from ffcoach.sources.schedule import _cache_key

    db = tmp_path / "c.sqlite3"
    Cache(db).set(_cache_key(2025), "not,a,schedule\n1,2,3\n", 3600)

    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(db),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T09:00-04:00",
    ])
    assert code == 1
    assert "no NFL schedule" in capsys.readouterr().err


def test_a_check_after_every_kickoff_is_not_reported_as_actionable(checkable, capsys):
    """January. Nothing is fixable, and the exit code must not say otherwise."""
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2026-01-01T09:00-05:00",
    ])
    out = capsys.readouterr().out
    assert code != 2
    assert "LOCKED, too late" in out


# --- D1: delivery ---

NOTIFY_YAML = """
channel: ntfy
ntfy:
  topic: "a-long-unguessable-topic-name"
"""


def test_check_dry_run_prints_the_message_it_would_have_sent(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    out = capsys.readouterr().out
    assert code == 2
    assert "[interrupt]" in out
    assert "lineup fixes — week 5" in out


def test_a_dry_run_still_validates_the_channel_config(checkable, tmp_path, capsys):
    """A dry run that skips validation "succeeds" against a broken topic."""
    conf = tmp_path / "notify.yaml"
    conf.write_text("channel: ntfy\nntfy: {topic: ''}\n")
    code = run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    assert code == 1
    assert "topic is required" in capsys.readouterr().err


def test_notify_without_a_config_file_exits_nonzero(checkable, tmp_path, capsys):
    code = run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(tmp_path / "nope.yaml")
    )
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_a_run_with_nothing_to_send_says_so_rather_than_staying_quiet(
    checkable, tmp_path, capsys
):
    """"Nothing sent" and "failed to send" must never look alike."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2026-01-01T09:00-05:00",   # every kickoff is past
        "--notify", "--dry-run",
        "--notify-config", str(conf),
    ])
    out = capsys.readouterr().out
    assert code == 3
    assert "Nothing to send" in out


def test_notify_test_needs_the_flag(tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    assert main(["notify", "--notify-config", str(conf)]) == 1
    assert "--init" in capsys.readouterr().err


def test_a_guessable_topic_is_refused(checkable, tmp_path, capsys):
    """A public ntfy topic has no auth; `ffcoach` is not a secret."""
    conf = tmp_path / "notify.yaml"
    conf.write_text("channel: ntfy\nntfy: {topic: 'ffcoach'}\n")
    code = run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    assert code == 1
    assert "guessable" in capsys.readouterr().err


# --- D3: the repeat policy, end to end ---


def test_a_repeated_check_does_not_send_the_same_alert_again(checkable, tmp_path, capsys):
    """The scheduler runs this many times an hour. Without the policy that is
    the same six alerts, every time, until Sunday."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    calls = []

    import ffcoach.cli as cli
    from ffcoach.notify.base import Notification

    class Recording:
        name = "recording"

        def send(self, notification: Notification) -> None:
            calls.append(notification)

    original = cli._notifier
    cli._notifier = lambda args: Recording()
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf))
        run_check(checkable, "--notify", "--notify-config", str(conf))
    finally:
        cli._notifier = original

    assert len(calls) == 1, "the second run must not repeat the first run's alert"
    assert "held" in capsys.readouterr().out


def test_a_failed_delivery_does_not_spend_a_strike(checkable, tmp_path, capsys):
    """Recording before sending would burn the alert that mattered."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)

    import ffcoach.cli as cli
    from ffcoach.notify.base import DeliveryError

    class Broken:
        name = "broken"

        def send(self, notification):
            raise DeliveryError("network is down")

    original = cli._notifier
    cli._notifier = lambda args: Broken()
    try:
        assert run_check(checkable, "--notify", "--notify-config", str(conf)) == 1
    finally:
        cli._notifier = original

    from ffcoach.notify.history import AlertHistory

    assert AlertHistory(checkable).counts() == {}


def test_a_dry_run_never_spends_a_strike(checkable, tmp_path, capsys):
    """It delivered nothing, so it must not count as having told you."""
    from ffcoach.notify.history import AlertHistory

    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    assert AlertHistory(checkable).counts() == {}


def test_quiet_hours_hold_the_alert_and_say_so(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T02:00-04:00",   # 2am ET
        "--notify", "--dry-run",
        "--notify-config", str(conf),
    ])
    out = capsys.readouterr().out
    assert code == 2, "the findings are still real; only the message is held"
    assert "quiet hours" in out
    assert "Nothing to send" in out


def test_quiet_hours_can_be_overridden_from_the_command_line(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--my-swid", SWID,
        "--now", "2025-10-01T02:00-04:00",
        "--notify", "--dry-run", "--ignore-quiet-hours",
        "--notify-config", str(conf),
    ])
    assert "[interrupt]" in capsys.readouterr().out


def test_the_title_counts_what_is_being_sent_not_what_exists(checkable, tmp_path, capsys):
    """A "6 lineup fixes" title above two lines reads as truncation, not policy."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf))
    out = capsys.readouterr().out
    import re

    title = re.search(r"\[interrupt\] (\d+) lineup fix", out)
    lines = out.count("EMPTY ") + out.count("BYE ") + out.count("OUT ")
    assert title and int(title.group(1)) >= 1


def test_the_alert_history_is_stamped_with_the_checks_clock_not_the_wall_clock(
    checkable, tmp_path
):
    """`--now` has to be coherent, or the repeat policy compares a simulated
    instant against a real one -- wrong wherever the flag is used, and
    invisible in production where the two agree."""
    import datetime as dt

    from ffcoach.notify.history import AlertHistory

    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)

    import ffcoach.cli as cli

    class Stub:
        name = "stub"

        def send(self, notification):
            pass

    original = cli._notifier
    cli._notifier = lambda args: Stub()
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf))
    finally:
        cli._notifier = original

    stamps = {r.last_sent for r in AlertHistory(checkable).records().values()}
    assert stamps
    assert all(s.year == 2025 and s.month == 10 for s in stamps), stamps
    assert all(s < dt.datetime.now(dt.UTC) for s in stamps)


# --- E1: every run leaves a line ---


def read_log(path):
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


def test_a_check_writes_one_run_log_line(checkable, tmp_path):
    log = tmp_path / "runs.jsonl"
    run_check(checkable, "--log", str(log))
    records = read_log(log)
    assert len(records) == 1
    r = records[0]
    assert r["command"] == "check"
    assert r["ok"] is True
    assert r["exit_code"] == 2
    assert r["week"] == 5
    assert r["week_source"] == "espn"
    assert r["status"] == "problems"
    assert r["findings"] == 6
    assert r["actionable"] == 6
    assert isinstance(r["duration_ms"], int)


def test_the_log_records_per_source_freshness(checkable, tmp_path):
    """F3's health panel reads this, and so does a person at 9am on a Sunday."""
    log = tmp_path / "runs.jsonl"
    run_check(checkable, "--log", str(log))
    names = {s["name"] for s in read_log(log)[0]["sources"]}
    assert "NFL schedule" in names


def test_a_failed_run_is_logged_as_not_ok(checkable, tmp_path):
    """A run that could not complete is not a heartbeat."""
    log = tmp_path / "runs.jsonl"
    main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--now", "2025-10-01T09:00-04:00",   # no --my-swid: no team is yours
        "--log", str(log),
    ])
    r = read_log(log)[0]
    assert r["ok"] is False
    assert r["exit_code"] == 1


def test_a_crash_still_leaves_a_line(checkable, tmp_path):
    """The runs most worth diagnosing are the ones that blew up.

    A check that raised and left no trace is exactly the silence E3 has to be
    able to tell apart from a clean week.
    """
    import ffcoach.cli as cli

    log = tmp_path / "runs.jsonl"
    original = cli.build_check
    cli.build_check = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        with pytest.raises(RuntimeError):
            run_check(checkable, "--log", str(log))
    finally:
        cli.build_check = original

    r = read_log(log)[0]
    assert r["ok"] is False
    assert "RuntimeError: boom" in r["error"]


def test_delivery_outcomes_reach_the_log(checkable, tmp_path):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    log = tmp_path / "runs.jsonl"

    import ffcoach.cli as cli

    class Stub:
        name = "stub"

        def send(self, notification):
            pass

    original = cli._notifier
    cli._notifier = lambda args: Stub()
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf), "--log", str(log))
    finally:
        cli._notifier = original

    r = read_log(log)[0]
    assert r["sent"] == 6
    assert r["channel"] == "stub"


def test_a_dry_run_is_marked_as_such_in_the_log(checkable, tmp_path):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    log = tmp_path / "runs.jsonl"
    run_check(checkable, "--notify", "--dry-run", "--notify-config", str(conf),
              "--log", str(log))
    r = read_log(log)[0]
    assert r["dry_run"] is True
    assert "sent" not in r


def test_the_ntfy_topic_never_reaches_the_log(checkable, tmp_path):
    """The topic is the credential, and the log is what gets pasted into issues."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    log = tmp_path / "runs.jsonl"

    import ffcoach.cli as cli
    from ffcoach.notify.base import DeliveryError

    class Leaky:
        name = "leaky"

        def send(self, notification):
            raise DeliveryError("POST to a-long-unguessable-topic-name failed")

    original = cli._notifier
    cli._notifier = lambda args: Leaky()
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf), "--log", str(log))
    finally:
        cli._notifier = original

    text = log.read_text()
    assert "a-long-unguessable-topic-name" not in text
    assert "***" in text


# --- E3: the dead-man's switch ---

WATCH_YAML = """
channel: ntfy
ntfy:
  topic: "a-long-unguessable-topic-name"
watchdog:
  max_silence_hours: 12
  min_consecutive_failures: 3
"""


def stub_notifier(sent):
    class Stub:
        name = "stub"

        def send(self, notification):
            sent.append(notification)

    return Stub()


def prefill_failures(log, n, hours_ago_start=1.0):
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    with log.open("w") as fh:
        for i in range(n):
            at = (now - dt.timedelta(hours=hours_ago_start + i)).isoformat()
            fh.write(json.dumps({"at": at, "command": "check", "ok": False}) + "\n")


def run_failing_check(checkable, conf, log):
    """A check that cannot run: no --my-swid, so no team is marked as yours."""
    return main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable),
        "--season", "2025",
        "--now", "2025-10-01T09:00-04:00",
        "--notify", "--notify-config", str(conf), "--log", str(log),
    ])


def test_a_run_of_failures_produces_an_outage_alert(checkable, tmp_path, capsys):
    """D-023 exactly: the check errors, nothing is sent, and that looks
    identical to a clean week unless something says otherwise."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)
    log = tmp_path / "runs.jsonl"
    prefill_failures(log, 2)

    import ffcoach.cli as cli

    sent = []
    original = cli._notifier
    cli._notifier = lambda args: stub_notifier(sent)
    try:
        run_failing_check(checkable, conf, log)
    finally:
        cli._notifier = original

    outage = [n for n in sent if n.title == "ffcoach is not working"]
    assert len(outage) == 1
    assert "3 runs in a row" in outage[0].body
    assert "cookies" in outage[0].body


def test_a_success_clears_the_failure_streak(checkable, tmp_path):
    """Three failures then a success is a resolved outage, not an ongoing one."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)
    log = tmp_path / "runs.jsonl"
    prefill_failures(log, 3)

    import ffcoach.cli as cli

    sent = []
    original = cli._notifier
    cli._notifier = lambda args: stub_notifier(sent)
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf), "--log", str(log))
    finally:
        cli._notifier = original

    assert [n for n in sent if n.title == "ffcoach is not working"] == []


def test_the_outage_alert_does_not_repeat_every_run(checkable, tmp_path):
    """A tripped watchdog is true on every run until it is fixed."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)
    log = tmp_path / "runs.jsonl"
    prefill_failures(log, 2)

    import ffcoach.cli as cli

    sent = []
    original = cli._notifier
    cli._notifier = lambda args: stub_notifier(sent)
    try:
        for _ in range(3):
            run_failing_check(checkable, conf, log)
    finally:
        cli._notifier = original

    assert len([n for n in sent if n.title == "ffcoach is not working"]) == 1


def test_a_healthy_run_produces_no_outage_alert(checkable, tmp_path):
    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)
    log = tmp_path / "runs.jsonl"

    import ffcoach.cli as cli

    sent = []
    original = cli._notifier
    cli._notifier = lambda args: stub_notifier(sent)
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf), "--log", str(log))
    finally:
        cli._notifier = original

    assert [n for n in sent if n.title == "ffcoach is not working"] == []


def test_the_watchdog_sees_the_run_it_is_reporting_on(checkable, tmp_path):
    """It reads the log *after* the line is written, not before."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)
    log = tmp_path / "runs.jsonl"
    prefill_failures(log, 2)   # two prior failures; this run makes three

    import ffcoach.cli as cli

    sent = []
    original = cli._notifier
    cli._notifier = lambda args: stub_notifier(sent)
    try:
        main([
            "check",
            "--fixture", str(FIXTURES / "espn_league.json"),
            "--cache", str(checkable),
            "--season", "2025",
            "--now", "2025-10-01T09:00-04:00",   # no --my-swid: this run fails
            "--notify", "--notify-config", str(conf), "--log", str(log),
        ])
    finally:
        cli._notifier = original

    assert [n for n in sent if n.title == "ffcoach is not working"]


def test_the_heartbeat_fires_even_without_notify(checkable, tmp_path):
    """Absence of the ping is what reports a dead machine, so suppressing it
    for a non-notifying run would fake one."""
    import ffcoach.cli as cli

    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML + '\nheartbeat:\n  url: "https://hc-ping.com/secret"\n')
    pings = []

    class FakeBeat:
        def __init__(self, url, fail_url=""):
            self.url, self.fail = url, fail_url

        def ping(self, ok=True):
            pings.append((self.url, ok))

    original = cli.Heartbeat
    cli.Heartbeat = FakeBeat
    try:
        run_check(checkable, "--log", str(tmp_path / "runs.jsonl"),
                  "--notify-config", str(conf))
    finally:
        cli.Heartbeat = original

    assert pings == [("https://hc-ping.com/secret", True)]


def test_a_watchdog_failure_never_replaces_the_real_error(checkable, tmp_path, capsys):
    """It runs in a `finally`; an exception here would mask what actually broke."""
    import ffcoach.cli as cli

    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)

    original = cli.assess
    cli.assess = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("watchdog broke"))
    try:
        code = run_check(checkable, "--notify", "--dry-run",
                         "--notify-config", str(conf), "--log", str(tmp_path / "r.jsonl"))
    finally:
        cli.assess = original
    assert code == 2


def test_doctor_states_the_exposure_when_no_heartbeat_is_configured(tmp_path, capsys):
    """Silence about missing monitoring reads as coverage."""
    import os

    conf = tmp_path / "notify.yaml"
    conf.write_text(WATCH_YAML)
    (tmp_path / "league.yaml").write_text(LEAGUE)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        (tmp_path / "notify.yaml").write_text(WATCH_YAML)
        main(["doctor", "--config", str(tmp_path / "league.yaml"),
              "--cache", str(tmp_path / "c.sqlite3")])
    finally:
        os.chdir(cwd)
    out = capsys.readouterr().out
    assert "Heartbeat: NOT configured" in out
    assert "nothing will tell you" in out


# --- `ffcoach notify --init`: setup as a command, not a ritual ---


def test_init_writes_a_config_with_an_unguessable_topic(tmp_path, capsys):
    """Left to a human the topic becomes "ffcoach" or "steve-fantasy", and a
    public ntfy topic has no authentication at all."""
    from ffcoach.config import load_notify_config

    conf = tmp_path / "notify.yaml"
    assert main(["notify", "--init", "--notify-config", str(conf)]) == 0
    loaded = load_notify_config(conf)
    assert loaded.channel == "ntfy"
    assert loaded.topic.startswith("ffcoach-")
    assert len(loaded.topic) > 20


def test_init_writes_a_file_the_loader_actually_accepts(tmp_path):
    """The template and the parser must not drift apart."""
    from ffcoach.config import load_notify_config

    conf = tmp_path / "notify.yaml"
    main(["notify", "--init", "--notify-config", str(conf)])
    loaded = load_notify_config(conf)
    assert loaded.min_consecutive_failures == 3
    assert loaded.max_silence_hours == 12
    assert loaded.has_heartbeat is False


def test_two_inits_never_produce_the_same_topic(tmp_path):
    from ffcoach.config import load_notify_config

    topics = set()
    for i in range(3):
        conf = tmp_path / f"n{i}.yaml"
        main(["notify", "--init", "--notify-config", str(conf)])
        topics.add(load_notify_config(conf).topic)
    assert len(topics) == 3


def test_init_refuses_to_clobber_an_existing_config(tmp_path, capsys):
    """Overwriting changes the topic out from under a subscribed phone.

    Alerts would go on being "delivered" to a topic nobody is listening to --
    the worst possible failure for this particular file.
    """
    conf = tmp_path / "notify.yaml"
    main(["notify", "--init", "--notify-config", str(conf)])
    before = conf.read_text()
    assert main(["notify", "--init", "--notify-config", str(conf)]) == 1
    assert conf.read_text() == before
    assert "already exists" in capsys.readouterr().err


def test_force_replaces_it_deliberately(tmp_path):
    conf = tmp_path / "notify.yaml"
    main(["notify", "--init", "--notify-config", str(conf)])
    before = conf.read_text()
    assert main(["notify", "--init", "--force", "--notify-config", str(conf)]) == 0
    assert conf.read_text() != before


def test_init_prints_the_topic_and_the_next_command(tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    main(["notify", "--init", "--notify-config", str(conf)])
    out = capsys.readouterr().out
    assert "https://ntfy.sh/ffcoach-" in out
    assert "notify --test" in out
    assert "credential" in out


def test_the_config_is_not_world_readable(tmp_path):
    conf = tmp_path / "notify.yaml"
    main(["notify", "--init", "--notify-config", str(conf)])
    assert conf.stat().st_mode & 0o077 == 0


# --- E2: the launchd agent, with launchctl itself stubbed ---


def in_workspace(tmp_path):
    """A directory that looks like a configured checkout."""
    import os

    for name in ("league.yaml", "espn.yaml", "notify.yaml"):
        (tmp_path / name).write_text("x: 1\n")
    cwd = os.getcwd()
    os.chdir(tmp_path)
    return cwd


@pytest.fixture
def on_macos(monkeypatch):
    """Pretend this is a Mac.

    CI runs on Linux, so without this every assertion below would be about the
    platform refusal rather than about the scheduler. The refusal gets its own
    test; everything else is platform-independent logic and is worth running
    everywhere.
    """
    import ffcoach.cli as cli

    monkeypatch.setattr(cli, "_is_macos", lambda: True)


def test_a_non_macos_machine_is_told_plainly_rather_than_given_cron(
    tmp_path, capsys, monkeypatch
):
    """D-022: cron skips jobs missed while asleep, so it is not a fallback."""
    import os

    import ffcoach.cli as cli

    monkeypatch.setattr(cli, "_is_macos", lambda: False)
    cwd = in_workspace(tmp_path)
    try:
        assert main(["schedule", "--install"]) == 1
    finally:
        os.chdir(cwd)
    assert "macOS-only" in capsys.readouterr().err


def test_the_plist_can_be_inspected_on_any_platform(tmp_path, capsys, monkeypatch):
    """`--print` writes and loads nothing, so it has no reason to be gated."""
    import os

    import ffcoach.cli as cli

    monkeypatch.setattr(cli, "_is_macos", lambda: False)
    cwd = in_workspace(tmp_path)
    try:
        assert main(["schedule", "--print"]) == 0
    finally:
        os.chdir(cwd)
    assert "com.ffcoach.check" in capsys.readouterr().out


def test_print_writes_nothing_and_loads_nothing(tmp_path, capsys):
    """The inspectable path: see exactly what would be installed, first."""
    import os

    import ffcoach.cli as cli

    calls = []
    original = cli._launchctl
    cli._launchctl = lambda *a: calls.append(a) or (0, "")
    cwd = in_workspace(tmp_path)
    try:
        assert main(["schedule", "--print"]) == 0
    finally:
        os.chdir(cwd)
        cli._launchctl = original

    out = capsys.readouterr().out
    assert "com.ffcoach.check" in out
    assert "<key>StartInterval</key>" in out
    assert calls == []


def test_install_boots_the_agent_out_before_bootstrapping_it(tmp_path, on_macos):
    """Re-installing after an edit must replace the definition, not sit behind
    the one already loaded."""
    import os

    import ffcoach.cli as cli

    calls = []
    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: calls.append(a[0]) or (0, "")
    cli.agent_plist_path = lambda home=None: tmp_path / "agent.plist"
    cwd = in_workspace(tmp_path)
    try:
        assert main(["schedule", "--install"]) == 0
    finally:
        os.chdir(cwd)
        cli._launchctl, cli.agent_plist_path = original_lc, original_path

    assert calls == ["bootout", "bootstrap"]
    assert (tmp_path / "agent.plist").exists()


def test_a_failed_bootstrap_is_reported_rather_than_claimed_as_success(tmp_path, capsys, on_macos):
    """A scheduler that silently did not load is the failure this whole stage
    is about."""
    import os

    import ffcoach.cli as cli

    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: (0, "") if a[0] == "bootout" else (5, "Input/output error")
    cli.agent_plist_path = lambda home=None: tmp_path / "agent.plist"
    cwd = in_workspace(tmp_path)
    try:
        assert main(["schedule", "--install"]) == 1
    finally:
        os.chdir(cwd)
        cli._launchctl, cli.agent_plist_path = original_lc, original_path

    err = capsys.readouterr().err
    assert "bootstrap failed" in err
    assert "nothing is scheduled" in err


def test_install_refuses_in_a_directory_with_no_config(tmp_path, capsys, on_macos):
    """launchd reports a missing config as a nonzero exit, forever, silently."""
    import os

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert main(["schedule", "--install"]) == 1
    finally:
        os.chdir(cwd)
    assert "league.yaml" in capsys.readouterr().err


def test_an_out_of_range_interval_is_refused(tmp_path, capsys, on_macos):
    import os

    cwd = in_workspace(tmp_path)
    try:
        assert main(["schedule", "--print", "--interval", "1"]) == 1
    finally:
        os.chdir(cwd)
    assert "interval must be between" in capsys.readouterr().err


def test_uninstall_removes_the_plist_even_when_nothing_was_loaded(tmp_path, capsys, on_macos):
    import ffcoach.cli as cli

    plist = tmp_path / "agent.plist"
    plist.write_text("<plist/>")
    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: (3, "No such process")
    cli.agent_plist_path = lambda home=None: plist
    try:
        assert main(["schedule", "--uninstall"]) == 0
    finally:
        cli._launchctl, cli.agent_plist_path = original_lc, original_path
    assert not plist.exists()
    assert "Unscheduled" in capsys.readouterr().out


def test_status_reports_loaded_and_whether_anything_has_actually_run(tmp_path, capsys, on_macos):
    """R-2 is exactly the gap between those two facts: launchd accepting a
    plist says nothing about the job succeeding or reaching a phone."""
    import ffcoach.cli as cli

    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: (0, "\tstate = running\n")
    cli.agent_plist_path = lambda home=None: tmp_path / "agent.plist"
    try:
        main(["schedule", "--status", "--log", str(tmp_path / "runs.jsonl")])
    finally:
        cli._launchctl, cli.agent_plist_path = original_lc, original_path

    out = capsys.readouterr().out
    assert "Loaded:   yes" in out
    assert "Last run: never" in out
    assert "nothing has run yet" in out


def test_status_says_plainly_when_nothing_is_scheduled(tmp_path, capsys, on_macos):
    import ffcoach.cli as cli

    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: (3, "Could not find service")
    cli.agent_plist_path = lambda home=None: tmp_path / "absent.plist"
    try:
        main(["schedule", "--status", "--log", str(tmp_path / "runs.jsonl")])
    finally:
        cli._launchctl, cli.agent_plist_path = original_lc, original_path

    out = capsys.readouterr().out
    assert "(absent)" in out
    assert "Loaded:   no" in out


def test_schedule_requires_a_mode(capsys):
    with pytest.raises(SystemExit):
        main(["schedule"])


def test_the_suite_never_writes_to_the_real_run_log(tmp_path):
    """Regression guard for the conftest isolation.

    `--log`, `--notify-config` and `--cache` all default to paths relative to
    the working directory, so a test that forgets one reads and writes the
    developer's own files. 463 test records had accumulated in the real run log
    before this was noticed -- and `_watch` was loading the real notify.yaml,
    which would have pinged a live heartbeat service and faked a healthy machine.
    """
    from pathlib import Path

    assert Path.cwd() != Path(__file__).resolve().parent.parent
    assert not (Path.cwd() / ".ffcoach-runs.jsonl").exists()


# --- the league's clock ---


def test_the_check_uses_the_timezone_from_league_config(checkable, tmp_path, capsys):
    """ESPN reports `waiverProcessHour: 11` with no zone. Eastern and Pacific
    are both plausible readings of that number, three hours apart, on a
    deadline the tool states as fact."""
    east = tmp_path / "east.yaml"
    east.write_text(LEAGUE)
    west = tmp_path / "west.yaml"
    west.write_text(LEAGUE + "timezone: America/Los_Angeles\n")

    def deadline_line(config):
        main([
            "check",
            "--fixture", str(FIXTURES / "espn_league.json"),
            "--cache", str(checkable), "--season", "2025", "--my-swid", SWID,
            "--now", "2025-10-01T09:00-04:00",
            "--config", str(config), "--log", str(tmp_path / "r.jsonl"),
        ])
        out = capsys.readouterr().out
        return next(ln for ln in out.splitlines() if ln.startswith("Waivers next"))

    assert "EDT" in deadline_line(east)
    assert "PDT" in deadline_line(west)


def test_an_unreadable_league_config_is_a_blind_spot_not_a_silent_assumption(
    checkable, tmp_path, capsys
):
    """A guessed timezone shifts every waiver deadline by hours while the tool
    goes on stating them as fact."""
    code = main([
        "check",
        "--fixture", str(FIXTURES / "espn_league.json"),
        "--cache", str(checkable), "--season", "2025", "--my-swid", SWID,
        "--now", "2025-10-01T09:00-04:00",
        "--config", str(tmp_path / "absent.yaml"),
        "--log", str(tmp_path / "r.jsonl"),
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert "timezone assumed" in out
    assert "Waiver deadlines may be hours off" in out


def test_the_run_log_records_which_timezone_was_used(checkable, tmp_path):
    """A deadline three hours out is unexplainable afterwards without it."""
    conf = tmp_path / "league.yaml"
    conf.write_text(LEAGUE + "timezone: America/Chicago\n")
    log = tmp_path / "runs.jsonl"
    run_check(checkable, "--config", str(conf), "--log", str(log))
    assert "America/Chicago" in read_log(log)[0]["timezone"]


# --- F0: `ffcoach serve` ---


def test_serve_refuses_a_directory_with_no_pages(tmp_path, capsys):
    """The plausible fallback is the project root, which is where the
    credentials live -- so there is no fallback."""
    assert main(["serve"]) == 1
    assert "no pages found" in capsys.readouterr().err


def test_serve_binds_to_localhost_unless_lan_is_asked_for(tmp_path, capsys):
    """The pages carry the user's roster. Broadcasting them is opt-in."""
    import ffcoach.cli as cli
    from ffcoach.serve import ALL_INTERFACES, LOCALHOST

    # conftest chdirs every test into a scratch directory, and `web_root()`
    # resolves from the working directory -- so the pages go there, not in
    # tmp_path.
    web = Path.cwd() / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>x</h1>")

    seen = []

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    original = cli.build_server
    cli.build_server = lambda root, host, port, **kw: seen.append(host) or FakeServer()
    try:
        main(["serve"])
        main(["serve", "--lan"])
    finally:
        cli.build_server = original

    assert seen == [LOCALHOST, ALL_INTERFACES]


def test_lan_mode_says_plainly_what_it_exposes(tmp_path, capsys):
    """Buried in --help is not said."""
    import ffcoach.cli as cli

    # conftest chdirs every test into a scratch directory, and `web_root()`
    # resolves from the working directory -- so the pages go there, not in
    # tmp_path.
    web = Path.cwd() / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>x</h1>")

    class FakeServer:
        server_address = ("0.0.0.0", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    original = cli.build_server
    cli.build_server = lambda root, host, port, **kw: FakeServer()
    try:
        main(["serve", "--lan"])
    finally:
        cli.build_server = original

    out = capsys.readouterr().out
    assert "Anyone on this network can read" in out
    assert "your roster" in out


# --- E5: `ffcoach init` and the hardened `doctor` ---


def fresh_project():
    """A directory shaped like a fresh clone: examples only, no real config."""
    root = Path(__file__).resolve().parent.parent
    for name in ("league.example.yaml", "espn.example.yaml", "notify.example.yaml"):
        (Path.cwd() / name).write_text((root / name).read_text())
    return Path.cwd()


def init_args(**over):
    base = {"config": "league.yaml", "notify_config": Path("notify.yaml"),
            "espn_config": Path("espn.yaml")}
    base.update(over)
    return base


def run_init():
    return main(["init"])


def test_init_creates_what_it_can_and_names_what_it_cannot(capsys):
    """The cookies need a browser. A wizard that stalls there is worse than a
    checklist that names it."""
    fresh_project()
    assert run_init() == 0
    out = capsys.readouterr().out
    assert "Created league.yaml" in out
    assert "Created notify.yaml" in out
    assert "[ ] espn.yaml" in out
    assert "paste espn_s2 / SWID from your browser" in out


def test_init_is_idempotent(capsys):
    fresh_project()
    run_init()
    before = (Path.cwd() / "notify.yaml").read_text()
    capsys.readouterr()
    assert run_init() == 0
    assert (Path.cwd() / "notify.yaml").read_text() == before
    assert "Nothing to create" in capsys.readouterr().out


def test_init_never_reuses_a_topic_across_projects():
    fresh_project()
    run_init()
    first = (Path.cwd() / "notify.yaml").read_text()
    (Path.cwd() / "notify.yaml").unlink()
    run_init()
    assert (Path.cwd() / "notify.yaml").read_text() != first


def test_init_outside_the_project_says_so_rather_than_half_creating(capsys):
    assert run_init() == 1
    assert "is this the project directory" in capsys.readouterr().err


def test_doctor_lists_the_same_remaining_steps_as_init(capsys):
    """One list read by both, so "what is missing" and "how do I fix it"
    cannot drift apart."""
    fresh_project()
    run_init()
    capsys.readouterr()
    main(["doctor"])
    out = capsys.readouterr().out
    assert "Setup: 3 step(s) left" in out
    assert "espn.yaml" in out


def test_a_complete_setup_reports_no_remaining_steps(capsys):
    fresh_project()
    run_init()
    (Path.cwd() / "espn.yaml").write_text("x: 1\n")
    conf = Path.cwd() / "notify.yaml"
    conf.write_text(
        conf.read_text()
        .replace('url: ""', 'url: "https://hc-ping.com/abc"', 1)
        .replace('scheduler_host: ""', 'scheduler_host: "somebox"')
    )
    capsys.readouterr()
    assert run_init() == 0
    assert "Setup looks complete" in capsys.readouterr().out


# --- the single-scheduler guard ---


GUARDED_YAML = """
channel: ntfy
ntfy:
  topic: "a-long-unguessable-topic-name"
scheduler_host: "some-other-machine"
"""


def test_a_non_scheduler_machine_does_not_send(checkable, tmp_path, capsys):
    """Two machines alerting means every alert twice: alert history is a local
    SQLite file, so the strikes never line up."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(GUARDED_YAML)

    import ffcoach.cli as cli

    sent = []

    class Stub:
        name = "stub"

        def send(self, notification):
            sent.append(notification)

    original = cli._notifier
    cli._notifier = lambda args: Stub()
    try:
        code = run_check(checkable, "--notify", "--notify-config", str(conf),
                         "--log", str(tmp_path / "r.jsonl"))
    finally:
        cli._notifier = original

    assert code == 2, "the findings are still real; only the sending is skipped"
    assert sent == []
    assert "Not the scheduler" in capsys.readouterr().out


def test_a_non_scheduler_machine_does_not_ping_the_heartbeat(checkable, tmp_path):
    """The dangerous half. A laptop pinging keeps healthchecks green while the
    scheduler machine is face-down -- E3 defeated by its own mechanism."""
    import ffcoach.cli as cli

    conf = tmp_path / "notify.yaml"
    conf.write_text(GUARDED_YAML + '\nheartbeat:\n  url: "https://hc-ping.com/x"\n')
    pings = []

    class FakeBeat:
        def __init__(self, url, fail_url=""):
            pass

        def ping(self, ok=True):
            pings.append(ok)

    original = cli.Heartbeat
    cli.Heartbeat = FakeBeat
    try:
        run_check(checkable, "--log", str(tmp_path / "r.jsonl"),
                  "--notify-config", str(conf))
    finally:
        cli.Heartbeat = original

    assert pings == []


def test_the_scheduler_machine_itself_is_unaffected(checkable, tmp_path):
    import ffcoach.cli as cli
    from ffcoach.host import this_host

    conf = tmp_path / "notify.yaml"
    conf.write_text(GUARDED_YAML.replace("some-other-machine", this_host()))
    sent = []

    class Stub:
        name = "stub"

        def send(self, notification):
            sent.append(notification)

    original = cli._notifier
    cli._notifier = lambda args: Stub()
    try:
        run_check(checkable, "--notify", "--notify-config", str(conf),
                  "--log", str(tmp_path / "r.jsonl"))
    finally:
        cli._notifier = original

    assert sent


def test_the_suppressed_host_is_recorded_in_the_run_log(checkable, tmp_path):
    """"Nothing was sent" and "nothing needed sending" must not look alike."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(GUARDED_YAML)
    log = tmp_path / "runs.jsonl"
    run_check(checkable, "--notify", "--notify-config", str(conf), "--log", str(log))
    assert read_log(log)[0]["suppressed_host"]


def test_install_records_this_machine_as_the_scheduler(tmp_path, on_macos):
    """A guard nobody remembers to set is not a guard."""
    import ffcoach.cli as cli
    from ffcoach.config import load_notify_config
    from ffcoach.host import this_host

    conf = Path.cwd() / "notify.yaml"
    fresh_project()
    run_init()

    class FakeServer:
        pass

    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: (0, "")
    cli.agent_plist_path = lambda home=None: tmp_path / "agent.plist"
    (Path.cwd() / "espn.yaml").write_text("x: 1\n")
    try:
        assert main(["schedule", "--install"]) == 0
    finally:
        cli._launchctl, cli.agent_plist_path = original_lc, original_path

    assert load_notify_config(conf).scheduler_host == this_host()


def test_no_claim_leaves_the_host_alone(tmp_path, on_macos):
    import ffcoach.cli as cli
    from ffcoach.config import load_notify_config

    fresh_project()
    run_init()
    (Path.cwd() / "espn.yaml").write_text("x: 1\n")

    original_lc, original_path = cli._launchctl, cli.agent_plist_path
    cli._launchctl = lambda *a: (0, "")
    cli.agent_plist_path = lambda home=None: tmp_path / "agent.plist"
    try:
        main(["schedule", "--install", "--no-claim"])
    finally:
        cli._launchctl, cli.agent_plist_path = original_lc, original_path

    assert load_notify_config(Path.cwd() / "notify.yaml").scheduler_host == ""


# --- D4: the preferences reach the delivery path -------------------------


def _prefs_file(tmp_path, text):
    path = tmp_path / "alerts.yaml"
    path.write_text(text)
    return str(path)


def test_a_switched_off_kind_is_held_and_says_so(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(conf),
        "--alerts-config", _prefs_file(tmp_path, "kinds:\n  bye: off\n  out: off\n"),
    )
    out = capsys.readouterr().out
    assert "switched off" in out
    # Still found, still reported, still exit 2 -- only the sending changed.
    assert code == 2


def test_a_mute_holds_everything_without_hiding_the_findings(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(conf),
        "--alerts-config", _prefs_file(tmp_path, 'mute_until: "2025-12-01T00:00-05:00"\n'),
    )
    out = capsys.readouterr().out
    assert "muted until" in out
    assert "Nothing to send" in out
    # The exit code still says there is work to do: a mute silences the phone,
    # not the check.
    assert code == 2


def test_quiet_hours_come_from_the_file_not_from_a_constant(checkable, tmp_path, capsys):
    """`--now` here is 09:00 ET, outside the default 23-08 window. A file that
    moves the window over it must hold the alert."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(conf),
        "--alerts-config",
        _prefs_file(tmp_path, "quiet_hours:\n  enabled: true\n  start: 8\n  end: 12\n"),
    )
    assert "quiet hours" in capsys.readouterr().out


def test_ignore_quiet_hours_still_overrides_the_file(checkable, tmp_path, capsys):
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    run_check(
        checkable, "--notify", "--dry-run", "--ignore-quiet-hours",
        "--notify-config", str(conf),
        "--alerts-config",
        _prefs_file(tmp_path, "quiet_hours:\n  enabled: true\n  start: 8\n  end: 12\n"),
    )
    assert "quiet hours" not in capsys.readouterr().out


def test_a_missing_alerts_file_changes_nothing(checkable, tmp_path, capsys):
    """The defaults are exactly the behaviour before D4 existed."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(conf),
        "--alerts-config", str(tmp_path / "absent.yaml"),
    )
    assert code == 2
    assert "[interrupt]" in capsys.readouterr().out


def test_an_unreadable_alerts_file_refuses_rather_than_alerting_on_everything(
    checkable, tmp_path, capsys
):
    """A file this tool cannot read is one whose author believes something is
    switched off. Guessing the opposite is how a mute becomes a 3am buzz."""
    conf = tmp_path / "notify.yaml"
    conf.write_text(NOTIFY_YAML)
    code = run_check(
        checkable, "--notify", "--dry-run", "--notify-config", str(conf),
        "--alerts-config", _prefs_file(tmp_path, 'mute_until: "2025-12-01T00:00"\n'),
    )
    assert code == 1
    assert "offset" in capsys.readouterr().err


def test_doctor_says_when_alerts_are_muted(tmp_path, capsys, monkeypatch):
    """Without this line, "I stopped getting alerts" and "I muted it on Sunday
    and forgot" are the same symptom."""
    (tmp_path / "alerts.yaml").write_text('mute_until: "2099-01-01T00:00+00:00"\n')
    monkeypatch.chdir(tmp_path)
    (tmp_path / "league.yaml").write_text(
        (FIXTURES.parent.parent / "league.example.yaml").read_text()
    )
    main(["doctor", "--config", str(tmp_path / "league.yaml"),
          "--alerts-config", str(tmp_path / "alerts.yaml")])
    out = capsys.readouterr().out
    assert "MUTED until" in out


def test_doctor_names_the_kinds_that_will_not_alert(tmp_path, capsys, monkeypatch):
    (tmp_path / "alerts.yaml").write_text("kinds:\n  bye_next_week: off\n")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "league.yaml").write_text(
        (FIXTURES.parent.parent / "league.example.yaml").read_text()
    )
    main(["doctor", "--config", str(tmp_path / "league.yaml"),
          "--alerts-config", str(tmp_path / "alerts.yaml")])
    assert "bye_next_week" in capsys.readouterr().out
