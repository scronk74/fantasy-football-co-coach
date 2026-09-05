"""League configuration: the single source of truth for format-specific rules.

Nothing downstream may hardcode scoring, roster shape, or team count.
"""

from __future__ import annotations

import datetime as dt
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
    # Which machine is allowed to send alerts and ping the heartbeat. Empty
    # means "any", which is right until a second machine exists. See
    # `ffcoach.host` for why this matters more than it looks.
    scheduler_host: str = ""

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

# The one machine allowed to send alerts and ping the heartbeat. Set
# automatically by `ffcoach schedule --install`.
#
# Leave it blank while you have one machine. Once a second one exists, an
# unguarded setup sends every alert twice -- alert history is a local file --
# and, far worse, a laptop that checks occasionally keeps the heartbeat green
# while the scheduler machine is face-down. A run from any other host still
# checks and still writes the page; it just does not send or ping.
scheduler_host: ""
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
        scheduler_host=str(raw.get("scheduler_host") or "").strip(),
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


def set_scheduler_host(path: Path, host: str) -> None:
    """Record which machine runs the scheduler, in place.

    A line edit rather than a YAML round-trip: rewriting the file through
    `yaml.dump` would strip every comment, and this config is mostly comments
    explaining what each knob costs if you get it wrong.
    """
    path = Path(path)
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc

    replacement = f'scheduler_host: "{host}"'
    for index, line in enumerate(lines):
        if line.strip().startswith("scheduler_host:"):
            lines[index] = replacement
            break
    else:
        lines.append("")
        lines.append("# Set by `ffcoach schedule --install`.")
        lines.append(replacement)

    path.write_text("\n".join(lines) + "\n")


# --- D4: which findings are allowed to reach a phone ------------------------
#
# Deliberately a *separate* file from `notify.yaml`. That file holds the ntfy
# topic, which is the credential (D-058), and F2's control page writes these
# preferences over HTTP. Splitting them means a request that reaches the write
# endpoint cannot touch the topic at all -- the whole class of "a POST
# redirects your alerts somewhere else" does not exist. Same instinct that
# already keeps `espn.yaml` out of `league.yaml`.
#
# Nothing in this file is secret, which is why it can be served and rewritten.

ALERT_KINDS = ("empty_slot", "out", "at_risk", "bye", "bye_next_week")

# What each switch turns off, in the words the control page uses.
ALERT_KIND_LABELS = {
    "empty_slot": "An empty starting slot",
    "out": "A starter ruled OUT",
    "at_risk": "Questionable or Doubtful, minutes before the lock",
    "bye": "A starter on bye this week",
    "bye_next_week": "A starter on bye next week (look-ahead)",
}


@dataclass(frozen=True)
class AlertPrefs:
    """What may interrupt you, and when.

    **Stores what is switched *off*, never what is on.** A kind this build has
    never heard of -- one added by a later version, or a file written before
    that kind existed -- is therefore allowed to alert. That direction is
    chosen: the failure this product exists to prevent is silence, so an
    unrecognized kind costs a message you did not need rather than a missed
    one you did.

    Disabling a kind stops it *sending*. It still appears in `ffcoach check`
    and on the Week page (the D-011 precedent for locked findings), and it is
    never recorded as a blind spot -- we did look, and we did find it.
    """

    disabled_kinds: frozenset[str] = frozenset()
    quiet_enabled: bool = True
    quiet_start: int = 23
    quiet_end: int = 8
    # An instant, never a boolean. A mute with no expiry is how a season ends
    # in silence; this one lapses on its own even if nobody remembers it.
    mute_until: "dt.datetime | None" = None

    def sends(self, kind: str) -> bool:
        return kind not in self.disabled_kinds

    def muted_at(self, now: "dt.datetime") -> bool:
        return self.mute_until is not None and now < self.mute_until


ALERTS_TEMPLATE = """\
# Which findings are allowed to reach your phone. Written by the Alerts page
# (`ffcoach serve` -> Alerts) and safe to edit by hand.
#
# This file holds no credentials -- the ntfy topic lives in notify.yaml and is
# deliberately not reachable from here.
#
# Every kind is ON unless listed as `off` below, including a kind a later
# version adds. Turning one off stops it *sending*; it still shows in
# `ffcoach check` and on the Week page.
kinds:
{kinds}
# Nothing interrupts between `start` and `end` (24h, league timezone) -- except
# a deadline that falls inside the window, which always wins. Deferred, never
# dropped: the next run after `end` finds the problem again.
quiet_hours:
  enabled: {quiet_enabled}
  start: {quiet_start}
  end: {quiet_end}

# Silence everything until this instant, then resume by itself. Must carry a
# UTC offset. Empty means not muted.
mute_until: "{mute_until}"
"""


def load_alert_prefs(path: Path) -> AlertPrefs:
    """Read the preferences, or the defaults when the file is absent.

    A missing file is not an error: the defaults are exactly the behaviour
    before D4 existed, so an install that never opens the Alerts page keeps
    working unchanged.
    """
    path = Path(path)
    if not path.exists():
        return AlertPrefs()

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")

    kinds = raw.get("kinds") or {}
    if not isinstance(kinds, dict):
        raise ConfigError(f"{path}: kinds must be a mapping of name -> on/off")
    disabled = frozenset(name for name, on in kinds.items() if not _truthy(on))

    quiet = raw.get("quiet_hours") or {}
    if not isinstance(quiet, dict):
        raise ConfigError(f"{path}: quiet_hours must be a mapping")
    start = _hour(path, "quiet_hours.start", quiet.get("start", 23))
    end = _hour(path, "quiet_hours.end", quiet.get("end", 8))

    return AlertPrefs(
        disabled_kinds=disabled,
        quiet_enabled=_truthy(quiet.get("enabled", True)),
        quiet_start=start,
        quiet_end=end,
        mute_until=_mute_until(path, raw.get("mute_until")),
    )


def _truthy(value) -> bool:
    """YAML already understands on/off/true/false; strings are the hand-edit case."""
    if isinstance(value, str):
        return value.strip().lower() in ("on", "true", "yes", "1")
    return bool(value)


def _hour(path: Path, field: str, value) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: {field} must be an hour 0-23") from exc
    if not 0 <= hour <= 23:
        raise ConfigError(f"{path}: {field} must be an hour 0-23, got {hour}")
    return hour


def _mute_until(path: Path, value) -> "dt.datetime | None":
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ConfigError(
            f"{path}: mute_until {text!r} is not an ISO instant "
            "(for example 2026-09-13T17:00-04:00)"
        ) from exc
    if moment.tzinfo is None:
        # Refused rather than read as UTC, for the reason `--now` refuses one:
        # a four-hour error in when the silence lifts is invisible and lands
        # exactly on a Sunday afternoon.
        raise ConfigError(
            f"{path}: mute_until {text!r} has no UTC offset; add one "
            "(for example 2026-09-13T17:00-04:00)"
        )
    return moment


def save_alert_prefs(path: Path, prefs: AlertPrefs) -> None:
    """Write the file the control page owns, comments and all.

    A full rewrite rather than `set_scheduler_host`'s line edit, and that is
    safe *because* this file is generated: the comments are rendered from the
    template each time rather than being a human's that a dump would destroy.
    """
    lines = []
    for kind in ALERT_KINDS:
        state = "off" if kind in prefs.disabled_kinds else "on"
        lines.append(f"  {kind}: {state}")
    # A kind switched off by some other version is preserved rather than
    # silently re-enabled by a save from this one.
    for kind in sorted(prefs.disabled_kinds - set(ALERT_KINDS)):
        lines.append(f"  {kind}: off")

    Path(path).write_text(
        ALERTS_TEMPLATE.format(
            kinds="\n".join(lines) + "\n",
            quiet_enabled="true" if prefs.quiet_enabled else "false",
            quiet_start=prefs.quiet_start,
            quiet_end=prefs.quiet_end,
            mute_until=prefs.mute_until.isoformat(timespec="minutes") if prefs.mute_until else "",
        )
    )


def prefs_from_payload(body: dict, current: AlertPrefs | None = None) -> AlertPrefs:
    """Validate what the control page posted, or refuse it by name.

    Pure, and separate from the HTTP handler so the rules are testable without
    a socket. Anything the payload omits keeps its current value: the page
    sends the whole form, but a hand-rolled request that sets one field must
    not silently reset the rest.

    A kind this build does not recognize is **rejected**, not stored. Unknown
    keys in a file are tolerated on read (a later version may have written
    them); accepting one over HTTP would let a typo -- `bye_next_wek` -- read
    as a successful save while the real alert kept firing.
    """
    current = current or AlertPrefs()

    kinds = body.get("kinds", None)
    disabled = set(current.disabled_kinds)
    if kinds is not None:
        if not isinstance(kinds, dict):
            raise ConfigError("kinds must be an object of name -> true/false")
        for name, on in kinds.items():
            if name not in ALERT_KINDS:
                raise ConfigError(
                    f"unknown alert kind {name!r}; expected one of "
                    + ", ".join(ALERT_KINDS)
                )
            disabled.discard(name)
            if not _truthy(on):
                disabled.add(name)

    quiet = body.get("quiet_hours", None)
    quiet_enabled, start, end = current.quiet_enabled, current.quiet_start, current.quiet_end
    if quiet is not None:
        if not isinstance(quiet, dict):
            raise ConfigError("quiet_hours must be an object")
        quiet_enabled = _truthy(quiet.get("enabled", quiet_enabled))
        start = _hour(Path("alerts"), "quiet_hours.start", quiet.get("start", start))
        end = _hour(Path("alerts"), "quiet_hours.end", quiet.get("end", end))
        if start == end and quiet_enabled:
            # Equal bounds are the one shape `QuietHours.covers` reads as an
            # empty window, so it would silently mean "no quiet hours" while
            # the page showed them enabled.
            raise ConfigError("quiet_hours.start and end must differ")

    mute = current.mute_until
    if "mute_until" in body:
        mute = _mute_until(Path("alerts"), body.get("mute_until"))

    return AlertPrefs(
        disabled_kinds=frozenset(disabled),
        quiet_enabled=quiet_enabled,
        quiet_start=start,
        quiet_end=end,
        mute_until=mute,
    )
