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
