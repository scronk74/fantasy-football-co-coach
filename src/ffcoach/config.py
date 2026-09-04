"""League configuration: the single source of truth for format-specific rules.

Nothing downstream may hardcode scoring, roster shape, or team count.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

SCORING_FORMATS = ("standard", "half-ppr", "ppr")

# Used only when `league.yaml` cannot be read at all. **ESPN publishes no
# timezone field anywhere** -- `acquisitionSettings.waiverProcessHour` is a bare
# integer, and the whole payload was searched to confirm it -- so this cannot be
# derived and has to be stated. Getting it wrong shifts every waiver deadline
# the tool emits by hours, silently and confidently, which is the exact failure
# class the rest of this codebase is built to avoid.
DEFAULT_TIMEZONE = "America/New_York"
STARTER_SLOTS = ("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")
BENCH_SLOT = "BN"
VALID_SLOTS = STARTER_SLOTS + (BENCH_SLOT,)


class ConfigError(Exception):
    """Raised when league.yaml is missing, malformed, or invalid."""


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    season: int
    teams: int
    scoring: str
    my_pick: int
    roster: dict[str, int]
    # The league's own clock. Waiver processing hours and quiet hours are both
    # read in it. Not derivable from ESPN -- see DEFAULT_TIMEZONE.
    timezone: str = DEFAULT_TIMEZONE

    @property
    def tzinfo(self):
        return ZoneInfo(self.timezone)

    @property
    def starters_total(self) -> int:
        return sum(n for slot, n in self.roster.items() if slot != BENCH_SLOT)

    @property
    def rounds(self) -> int:
        return sum(self.roster.values())

    def next_pick_after(self, pick: int) -> int | None:
        """Next overall pick number in a snake draft, or None past the end.

        In a snake, the order reverses every round, so your next pick is
        always mirrored around the turn. Both the odd->even and even->odd
        transitions reduce to the same expression.
        """
        rnd = (pick - 1) // self.teams + 1
        if rnd >= self.rounds:
            return None
        pos_in_round = (pick - 1) % self.teams + 1
        return rnd * self.teams + (self.teams - pos_in_round + 1)


@dataclass(frozen=True)
class EspnCredentials:
    league_id: str
    season: int
    espn_s2: str
    swid: str


def load_espn_credentials(path: Path) -> EspnCredentials:
    """Load the gitignored ESPN session-cookie file.

    Kept separate from LeagueConfig/league.yaml: these are session
    credentials that authenticate as you, not plain league settings, so
    league.yaml stays safe to share or screenshot.
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"ESPN credentials not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    missing = {"league_id", "season", "espn_s2", "swid"} - raw.keys()
    if missing:
        raise ConfigError(f"missing required keys: {', '.join(sorted(missing))}")

    return EspnCredentials(
        league_id=str(raw["league_id"]),
        season=int(raw["season"]),
        espn_s2=str(raw["espn_s2"]),
        swid=str(raw["swid"]),
    )


@dataclass(frozen=True)
class NotifyConfig:
    """Where alerts go. Its own file for the same reason `espn.yaml` is.

    A public ntfy topic has **no authentication**: whoever knows the name can
    read your alerts and publish to them. The name is therefore a credential,
    it lives in a gitignored file, and nothing prints it -- `doctor` reports
    that a channel is configured, never which topic.
    """

    channel: str
    topic: str = ""
    server: str = "https://ntfy.sh"
    # E3's off-host half. Empty means no external monitoring at all, and
    # `doctor` says so rather than letting it look covered -- an unconfigured
    # heartbeat is the difference between "the machine died and I was told"
    # and "the machine died".
    heartbeat_url: str = ""
    heartbeat_fail_url: str = ""
    max_silence_hours: float = 12.0
    min_consecutive_failures: int = 3

    @property
    def has_heartbeat(self) -> bool:
        return bool(self.heartbeat_url)


# Written by `ffcoach notify --init`. Kept beside the loader so the file it
# writes and the file it reads cannot drift apart.
NOTIFY_TEMPLATE = """\
# Written by `ffcoach notify --init`. Gitignored.
#
# The ntfy topic below IS the credential: a public ntfy topic has no
# authentication, so anyone who knows the name can read your alerts and publish
# to them. Do not paste it anywhere.

channel: ntfy

ntfy:
  topic: "{topic}"
  # Only change this if you self-host ntfy.
  server: "https://ntfy.sh"

# The on-host dead-man's switch. Alerts you when ffcoach itself stops working --
# the expired-cookie case, where the check errors and sends nothing, which looks
# exactly like a clean week.
watchdog:
  max_silence_hours: 12
  min_consecutive_failures: 3

# The off-host half, and the only thing that survives this machine dying.
# Point `url` at any service where the ABSENCE of a ping is the alert:
# healthchecks.io (free), Cronitor, Better Stack, self-hosted Uptime Kuma.
# Leave it blank and a power cut or a network drop is completely silent --
# `ffcoach doctor` will say so on every run until you fill it in.
heartbeat:
  url: ""
  # Optional. Never guessed from `url`: appending "/fail" is one vendor's
  # convention and silently wrong for the others.
  fail_url: ""
"""


def new_topic() -> str:
    """An unguessable ntfy topic.

    `secrets`, not `random`: this is a credential, and a predictable one lets a
    stranger read your alerts and publish fake ones to your phone. 12 bytes of
    URL-safe entropy is 96 bits, which is not enumerable.
    """
    import secrets

    return f"ffcoach-{secrets.token_urlsafe(12)}"


def write_notify_config(path: Path, topic: str, force: bool = False) -> None:
    """Create `notify.yaml`. Refuses to clobber an existing one.

    Overwriting would silently change the topic out from under a phone that is
    already subscribed -- alerts would go on being "delivered" to a topic
    nobody is listening to, which is the worst possible failure for this file.
    """
    path = Path(path)
    if path.exists() and not force:
        raise ConfigError(
            f"{path} already exists; overwriting would change the topic your "
            "phone is subscribed to. Pass --force if that is what you want."
        )
    path.write_text(NOTIFY_TEMPLATE.format(topic=topic))
    # Alerts are not secret in the way a password is, but the topic is, and a
    # world-readable credential in a home directory is a free win to avoid.
    path.chmod(0o600)


def load_notify_config(path: Path) -> NotifyConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"notification config not found: {path} "
            "(copy notify.example.yaml and pick an unguessable topic)"
        )

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    channel = str(raw.get("channel", "")).lower()
    if channel != "ntfy":
        raise ConfigError(f"unknown notification channel {channel!r}; supported: ntfy")

    section = raw.get("ntfy") or {}
    topic = str(section.get("topic", "")).strip()
    if not topic:
        raise ConfigError(f"{path}: ntfy.topic is required and must not be empty")
    # A topic anyone could guess is a topic anyone can read and publish to.
    if topic in ("ffcoach", "fantasy", "test", "alerts"):
        raise ConfigError(
            f"{path}: ntfy.topic {topic!r} is guessable; a public ntfy topic has "
            "no authentication, so use a long random name"
        )

    watch = raw.get("watchdog") or {}
    try:
        max_silence = float(watch.get("max_silence_hours", 12))
        min_failures = int(watch.get("min_consecutive_failures", 3))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: watchdog values must be numbers: {exc}") from exc
    if max_silence <= 0:
        raise ConfigError(f"{path}: watchdog.max_silence_hours must be positive")
    # One is not a streak. A single flaky fetch would page you, and an alert
    # channel that cries wolf is the one you mute before the week that matters.
    if min_failures < 2:
        raise ConfigError(f"{path}: watchdog.min_consecutive_failures must be at least 2")

    beat = raw.get("heartbeat") or {}
    return NotifyConfig(
        channel=channel,
        topic=topic,
        server=str(section.get("server") or "https://ntfy.sh"),
        heartbeat_url=str(beat.get("url") or "").strip(),
        heartbeat_fail_url=str(beat.get("fail_url") or "").strip(),
        max_silence_hours=max_silence,
        min_consecutive_failures=min_failures,
    )


def load_config(path: Path) -> LeagueConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"league config not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    missing = {"name", "season", "teams", "scoring", "my_pick", "roster"} - raw.keys()
    if missing:
        raise ConfigError(f"missing required keys: {', '.join(sorted(missing))}")

    scoring = str(raw["scoring"]).lower()
    if scoring not in SCORING_FORMATS:
        raise ConfigError(f"scoring must be one of {SCORING_FORMATS}, got {scoring!r}")

    roster = raw["roster"] or {}
    for slot in roster:
        if slot not in VALID_SLOTS:
            raise ConfigError(f"unknown roster slot {slot!r}; valid: {VALID_SLOTS}")

    timezone = str(raw.get("timezone") or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        # Refused rather than defaulted: a typo'd zone that silently became
        # Eastern would leave the user believing a value they set.
        raise ConfigError(f"unknown timezone {timezone!r}: {exc}") from exc

    teams = int(raw["teams"])
    my_pick = int(raw["my_pick"])
    if not 1 <= my_pick <= teams:
        raise ConfigError(f"my_pick must be between 1 and {teams}, got {my_pick}")

    return LeagueConfig(
        name=str(raw["name"]),
        season=int(raw["season"]),
        teams=teams,
        scoring=scoring,
        my_pick=my_pick,
        roster={str(k): int(v) for k, v in roster.items()},
        timezone=timezone,
    )
