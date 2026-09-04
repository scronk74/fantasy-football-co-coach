"""E2: the launchd agent, split so the testable half is actually tested.

R-2 says launchd correctness cannot be verified in CI, and that is true of the
*loading*. It is not true of the plist, which is a pure function of a few paths
and an interval -- and a plist that is subtly wrong is the worst outcome
available here, because launchd will happily "run" it and fail silently every
fifteen minutes forever.
"""

import plistlib
from pathlib import Path

import pytest

from ffcoach.agent import (
    LABEL,
    AgentError,
    agent_plist_path,
    build_agent,
    plist_bytes,
)


def agent(tmp_path, **over):
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir(parents=True, exist_ok=True)
    uv.write_text("#!/bin/sh\n")
    uv.chmod(0o755)
    for name in ("league.yaml", "espn.yaml", "notify.yaml"):
        (tmp_path / name).write_text("x: 1\n")
    kw = dict(working_dir=tmp_path, uv=uv, interval_minutes=30)
    kw.update(over)
    return build_agent(**kw)


def parsed(a):
    return plistlib.loads(plist_bytes(a))


# --- the plist itself ---


def test_the_label_is_stable(tmp_path):
    assert parsed(agent(tmp_path))["Label"] == LABEL


def test_every_path_in_the_plist_is_absolute(tmp_path):
    """launchd has no shell, no PATH and no working directory of its own.

    A relative path here does not fail loudly -- the job runs, cannot find
    `uv`, exits nonzero, and does so silently every interval forever.
    """
    p = parsed(agent(tmp_path))
    for value in [*p["ProgramArguments"], p["WorkingDirectory"],
                  p["StandardOutPath"], p["StandardErrorPath"]]:
        if value.startswith("-") or not value.startswith(("/", "~")):
            assert not Path(value).parts or value.startswith("/") or value in (
                "run", "ffcoach", "check", "--notify"
            ), value
    assert p["ProgramArguments"][0].startswith("/")
    assert p["WorkingDirectory"].startswith("/")
    assert p["StandardOutPath"].startswith("/")


def test_the_scheduled_command_actually_sends(tmp_path):
    """Without --notify the scheduler runs forever and tells no one anything."""
    assert "--notify" in parsed(agent(tmp_path))["ProgramArguments"]


def test_the_interval_is_in_seconds(tmp_path):
    """launchd's StartInterval is seconds; minutes would run it 60x too often."""
    assert parsed(agent(tmp_path, interval_minutes=30))["StartInterval"] == 1800


def test_it_runs_at_load_so_a_reboot_does_not_start_with_a_gap(tmp_path):
    assert parsed(agent(tmp_path))["RunAtLoad"] is True


def test_it_is_not_kept_alive(tmp_path):
    """KeepAlive restarts a job the moment it exits -- correct for a daemon,
    and for a periodic check it is an infinite loop hammering ESPN."""
    assert "KeepAlive" not in parsed(agent(tmp_path))


def test_stdout_and_stderr_are_captured_somewhere(tmp_path):
    """The JSONL run log covers a check that ran. This covers one that could
    not start -- a traceback before any of our code executes."""
    p = parsed(agent(tmp_path))
    assert p["StandardOutPath"] != p["StandardErrorPath"]


def test_a_path_with_xml_metacharacters_survives(tmp_path):
    """Hand-written XML breaks on a directory called `Tom & Jerry`. plistlib
    does not, which is the reason it is used instead of a format string."""
    weird = tmp_path / "Tom & Jerry <fantasy>"
    weird.mkdir()
    for name in ("league.yaml", "espn.yaml", "notify.yaml"):
        (weird / name).write_text("x: 1\n")
    a = agent(tmp_path, working_dir=weird)
    assert parsed(a)["WorkingDirectory"] == str(weird)


# --- refusing to write an agent that cannot work ---


def test_a_missing_uv_binary_is_refused(tmp_path):
    """A plist pointing at a binary that is not there is worse than no plist:
    launchd runs it, it fails, and nothing says so."""
    with pytest.raises(AgentError, match="uv"):
        build_agent(working_dir=tmp_path, uv=tmp_path / "nope", interval_minutes=30)


def test_a_working_directory_without_league_config_is_refused(tmp_path):
    uv = tmp_path / "uv"
    uv.write_text("")
    uv.chmod(0o755)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AgentError, match="league.yaml"):
        build_agent(working_dir=empty, uv=uv, interval_minutes=30)


def test_a_working_directory_without_notify_config_is_refused(tmp_path):
    """Scheduling a check that has nowhere to send is scheduling silence."""
    a_dir = tmp_path / "part"
    a_dir.mkdir()
    (a_dir / "league.yaml").write_text("x: 1")
    (a_dir / "espn.yaml").write_text("x: 1")
    uv = tmp_path / "uv"
    uv.write_text("")
    uv.chmod(0o755)
    with pytest.raises(AgentError, match="notify.yaml"):
        build_agent(working_dir=a_dir, uv=uv, interval_minutes=30)


def test_an_absurd_interval_is_refused(tmp_path):
    """One minute is ~10k ESPN requests a week from an unofficial API."""
    with pytest.raises(AgentError, match="interval"):
        agent(tmp_path, interval_minutes=1)
    with pytest.raises(AgentError, match="interval"):
        agent(tmp_path, interval_minutes=0)


def test_a_very_long_interval_is_refused(tmp_path):
    """Six hours cannot catch a Sunday inactives ruling before kickoff."""
    with pytest.raises(AgentError, match="interval"):
        agent(tmp_path, interval_minutes=600)


# --- where it goes ---


def test_the_agent_lives_in_the_user_launch_agents_directory(tmp_path):
    path = agent_plist_path(home=tmp_path)
    assert path.parent == tmp_path / "Library" / "LaunchAgents"
    assert path.name.endswith(".plist")
    assert LABEL in path.name
