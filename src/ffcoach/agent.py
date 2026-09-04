"""The launchd agent that runs the check without being asked.

**Why launchd and not cron** (D-022): cron does not run a job it missed while
the Mac was asleep. It would appear to work all week and be silently absent on
exactly the mornings that matter. launchd fires a missed `StartInterval` once
on wake, which is the whole reason this file exists.

**Why the plist is built here and loaded elsewhere.** R-2 says launchd
correctness cannot be verified in CI, and that is true of the *loading*. It is
not true of the plist, which is a pure function of two paths and an interval --
and a wrong plist is the worst outcome available, because launchd will happily
"run" it and fail silently every interval forever. So everything checkable
lives in this module and is tested; only `launchctl` itself is unverifiable.

**Why it refuses more than it accepts.** Every guard here exists because the
failure it prevents is *silent*. A missing `uv`, a working directory with no
config, a relative path: none of them raise anything a person would see. The
job runs, exits nonzero, and launchd tries again in fifteen minutes forever.
The dead-man's switch (E3) would eventually notice -- but only if the check got
far enough to write a log line, and these failures happen before that.

`plistlib` rather than a format string, because a directory named
`Tom & Jerry` is a perfectly ordinary thing to have and hand-written XML breaks
on it.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass
from pathlib import Path

LABEL = "com.ffcoach.check"

# Every half hour, which is a deliberate middle. Denser than the three-hour
# last-call window so a reminder is never late, sparse enough that a season is
# ~10k requests to an unofficial API rather than ~300k. The bounds below are
# the reasoning made enforceable.
DEFAULT_INTERVAL_MINUTES = 30
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 240

# Present before the agent is written. Not a courtesy check: launchd reports
# none of these as anything but a nonzero exit repeating forever.
REQUIRED_CONFIG = ("league.yaml", "espn.yaml", "notify.yaml")


class AgentError(Exception):
    """The agent cannot be built, which is better than one that cannot run."""


@dataclass(frozen=True)
class LaunchAgent:
    working_dir: Path
    uv: Path
    interval_minutes: int
    stdout_path: Path
    stderr_path: Path

    @property
    def domain_target(self) -> str:
        """What `launchctl bootout` addresses. `gui/<uid>`, not `user/<uid>`:
        the job needs the user's GUI session to reach the keychain and the
        network the way a logged-in process does."""
        import os

        return f"gui/{os.getuid()}"

    @property
    def service_target(self) -> str:
        return f"{self.domain_target}/{LABEL}"


def agent_plist_path(home: Path | None = None) -> Path:
    home = Path(home) if home else Path.home()
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_agent(
    working_dir: Path,
    uv: Path,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
) -> LaunchAgent:
    """Validate everything launchd will not, then describe the job."""
    if not MIN_INTERVAL_MINUTES <= interval_minutes <= MAX_INTERVAL_MINUTES:
        raise AgentError(
            f"interval must be between {MIN_INTERVAL_MINUTES} and "
            f"{MAX_INTERVAL_MINUTES} minutes, got {interval_minutes}. Below the "
            "floor this hammers an unofficial API; above the ceiling it cannot "
            "catch a Sunday inactives ruling before kickoff."
        )

    uv = Path(uv)
    if not uv.is_file():
        raise AgentError(
            f"uv not found at {uv}. launchd has no PATH, so the plist must "
            "name an absolute path to a binary that exists."
        )

    working_dir = Path(working_dir).resolve()
    if not working_dir.is_dir():
        raise AgentError(f"working directory does not exist: {working_dir}")
    for name in REQUIRED_CONFIG:
        if not (working_dir / name).exists():
            raise AgentError(
                f"{working_dir / name} is missing. Scheduling a check that "
                "cannot read its config, or has nowhere to send, is scheduling "
                "silence."
            )

    return LaunchAgent(
        working_dir=working_dir,
        uv=uv.resolve(),
        interval_minutes=interval_minutes,
        # Beside the JSONL run log, which covers a check that *ran*. These
        # catch one that could not start -- a traceback before any of our own
        # code executes, which the run log by definition cannot record.
        stdout_path=working_dir / ".ffcoach-launchd.out.log",
        stderr_path=working_dir / ".ffcoach-launchd.err.log",
    )


def plist_bytes(agent: LaunchAgent) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [
                str(agent.uv), "run", "ffcoach", "check", "--notify",
            ],
            "WorkingDirectory": str(agent.working_dir),
            "StartInterval": agent.interval_minutes * 60,
            # So a reboot or a fresh load does not begin with a blind interval.
            "RunAtLoad": True,
            # Deliberately no KeepAlive: it restarts a job the moment it exits,
            # which for a periodic check is an infinite loop against ESPN.
            "StandardOutPath": str(agent.stdout_path),
            "StandardErrorPath": str(agent.stderr_path),
            "ProcessType": "Background",
            # launchd starts with almost nothing. HOME is what `uv` and the
            # cache path resolution both assume exists.
            "EnvironmentVariables": {"HOME": str(Path.home())},
        }
    )
