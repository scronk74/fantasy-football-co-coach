"""D3: whether a real, actionable problem is allowed to buzz your phone *again*.

Everything here answers a question the detection layer cannot: the same finding
appears on every run until it is fixed, and a scheduler runs the check many
times an hour. Without this module, "alert on actionable findings" means "alert
every fifteen minutes until Sunday", and a channel you mute is strictly worse
than one that is occasionally quiet.

Two rules, and the interesting part of each is its exception.

**Quiet hours defer, they do not drop** (D-018). Nothing is queued: the problem
is still on the roster, so the next run after 08:00 finds it again and sends it.
That is D-019's "the roster is the acknowledgment" applied to deferral. The
exception is that **quiet hours yield to a deadline that falls inside them** --
holding an alert past the last moment it could have been acted on produces
silence indistinguishable from a clean week, which is the failure this whole
product exists to prevent.

**Two strikes, then nothing** (D-019). No inbound channel is needed to
acknowledge an alert, because a fixed problem stops being a finding on its own.
The exception is *when* the second strike is spent: not on the next run, which
would be a reminder fifteen minutes after the first and pure noise, but inside a
last-call window before the deadline, which is the single most useful message
this tool sends.

Pure: no clock, no I/O, no storage. `counts` comes from `notify/history.py` and
`now` is passed in.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ffcoach.advisors.lineup import LineupFinding
from ffcoach.config import AlertPrefs

# How close to the deadline the second and final alert is spent. Three hours
# clears a Sunday-morning inactives ruling with time to make a claim, and is
# short enough that it is not simply "the first alert again".
LAST_CALL = dt.timedelta(hours=3)

# The reminder also needs air between it and the first alert. Without this,
# "last call" collapses into "immediately" whenever a problem is *first* seen
# inside the window -- a scheduler running every fifteen minutes would spend
# both strikes in half an hour and then go silent for the three hours that
# mattered. Found by a test, not by reasoning.
MIN_GAP = dt.timedelta(minutes=45)

MAX_ALERTS = 2


@dataclass(frozen=True)
class QuietHours:
    """A nightly window in which nothing is allowed to interrupt.

    Wraps past midnight, which is why `covers` is a disjunction rather than a
    range check: 23:00-08:00 is not a contiguous span of hour numbers.
    """

    start_hour: int = 23
    end_hour: int = 8
    enabled: bool = True

    def covers(self, moment: dt.datetime, tz: dt.tzinfo) -> bool:
        if not self.enabled:
            return False
        hour = moment.astimezone(tz).hour
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    def ends_at(self, moment: dt.datetime, tz: dt.tzinfo) -> dt.datetime:
        """The next moment this window lifts."""
        local = moment.astimezone(tz)
        end = local.replace(hour=self.end_hour, minute=0, second=0, microsecond=0)
        if end <= local:
            end += dt.timedelta(days=1)
        return end

    @property
    def label(self) -> str:
        return f"{self.start_hour:02d}:00"


@dataclass(frozen=True)
class AlertRecord:
    """What we already told this person about this problem.

    `last_sent` may be `None` for a record whose time we do not know; that is
    treated as "long enough ago", because refusing to remind is the worse
    failure of the two.
    """

    count: int = 0
    last_sent: dt.datetime | None = None


@dataclass(frozen=True)
class SendDecision:
    """What goes out now, what was held, and what to record afterwards."""

    send: list[LineupFinding] = field(default_factory=list)
    # One human sentence per held finding. Surfaced rather than swallowed: a
    # suppressed alert is a decision, and a decision nobody can see is a bug
    # report waiting to happen.
    held: tuple[str, ...] = ()
    # Recorded only after a successful delivery, never before -- see `decide`.
    keys_sent: tuple[str, ...] = ()


def alert_key(week: int, finding: LineupFinding, ordinal: int = 0) -> str:
    """Stable identity for "this problem, this week".

    Includes the week so a bye in week 5 and a bye in week 12 are two problems
    rather than one that already used its strikes.

    `ordinal` disambiguates findings that are genuinely identical: two empty WR
    slots have no player, no NFL team and the same slot name, so nothing on the
    finding itself separates them. It is assigned across the batch, which is
    the only place the distinction exists, and the first of a kind keeps the
    plain key so history stays comparable when a duplicate comes and goes.
    """
    parts = [str(week), finding.kind, finding.lineup_slot, finding.player_name or "-"]
    if ordinal:
        parts.append(f"#{ordinal + 1}")
    return ":".join(parts)


def _keys(week: int, findings: Iterable[LineupFinding]) -> list[str]:
    seen: dict[str, int] = {}
    keys = []
    for finding in findings:
        base = alert_key(week, finding)
        ordinal = seen.get(base, 0)
        seen[base] = ordinal + 1
        keys.append(alert_key(week, finding, ordinal))
    return keys


def _describe(finding: LineupFinding) -> str:
    return finding.player_name or f"the empty {finding.lineup_slot} slot"


def decide(
    findings: Sequence[LineupFinding],
    week: int,
    records: Mapping[str, AlertRecord],
    now: dt.datetime,
    quiet: QuietHours,
    tz: dt.tzinfo,
    last_call: dt.timedelta = LAST_CALL,
    min_gap: dt.timedelta = MIN_GAP,
) -> SendDecision:
    """Which of these actionable findings may interrupt someone right now.

    `records` maps alert key to what has already been delivered for it.

    `keys_sent` is returned rather than recorded here so the caller can record
    it **after** a successful send. Recording first would spend a strike on a
    message that never arrived, and the second strike is the one that lands
    ninety minutes before kickoff.
    """
    send: list[LineupFinding] = []
    keys_sent: list[str] = []
    held: list[str] = []

    for finding, key in zip(findings, _keys(week, findings)):
        record = records.get(key, AlertRecord())
        who = _describe(finding)

        if record.count >= MAX_ALERTS:
            held.append(f"{who}: already alerted twice; the roster is the acknowledgment")
            continue

        deadline = finding.deadline

        if record.count:
            # The reminder waits for the last-call window. With no known
            # deadline there is no window, so it never fires -- one alert, not
            # two.
            if deadline is None or deadline - now > last_call:
                held.append(f"{who}: reminder held until closer to the deadline")
                continue
            # ...and it waits for air after the first alert, or a problem first
            # seen inside the window burns both strikes in one scheduler cycle.
            if record.last_sent is not None and now - record.last_sent < min_gap:
                held.append(f"{who}: reminder held; only just alerted")
                continue

        if quiet.covers(now, tz):
            lifts = quiet.ends_at(now, tz)
            # The exception: a deadline inside quiet hours overrides them.
            if deadline is None or deadline > lifts:
                held.append(
                    f"{who}: quiet hours ({quiet.label}); holding until 08:00"
                )
                continue

        send.append(finding)
        keys_sent.append(key)

    return SendDecision(send=send, held=tuple(held), keys_sent=tuple(keys_sent))


def allowed_by_prefs(
    findings: Sequence[LineupFinding],
    prefs: "AlertPrefs",
    now: dt.datetime,
) -> tuple[list[LineupFinding], tuple[str, ...]]:
    """D4: which findings the user has agreed to be interrupted about.

    Runs *before* `decide`, and the split is deliberate. This answers "may this
    kind ever reach me"; `decide` answers "may it reach me again, right now".
    Collapsing them would let a preference spend a strike.

    Held findings are returned as reasons rather than dropped, for the same
    reason every other suppression is: a message you did not get needs a
    visible cause, or the next silent week is unexplainable.
    """
    if prefs.muted_at(now):
        lifts = prefs.mute_until.astimezone(dt.UTC).isoformat(timespec="minutes")
        return [], (f"all alerts muted until {lifts}",)

    kept: list[LineupFinding] = []
    held: list[str] = []
    for finding in findings:
        if prefs.sends(finding.kind):
            kept.append(finding)
        else:
            held.append(f"{_describe(finding)}: {finding.kind} alerts are switched off")
    return kept, tuple(held)
