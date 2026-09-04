"""A `CheckResult` rendered for a phone.

Pure: result in, `Notification` or `None` out. Returning `None` is the common
case and the important one -- **a clean week sends nothing**, and that silence
is the system working rather than a failure to report (D-016).

Three rules decide what is sent:

- **Only `actionable` findings.** A locked finding stays in the report (D-011)
  and out of the message: there is nothing left to do about it, and a buzz that
  cannot be acted on is pure cost.
- **Blind spots never send on their own** (D-057). A stale ESPN fetch can
  persist across every run of a day, and until D3's repeat policy exists that
  is a spam machine. They ride *inside* a message that was going out anyway.
- **Every line states its reason**, the same as on screen (UX rule 4). A phone
  is where an unexplained flag is most useless -- there is no second screen to
  check.

Kept separate from `report/check_text.py` because the constraints are genuinely
different: a terminal has room to explain, a lock screen has four lines and no
scrollback.
"""

from __future__ import annotations

import datetime as dt

from ffcoach.check import CheckResult
from ffcoach.notify.base import Notification

# How many findings fit before the message stops being scannable. Beyond this
# the count in the title is still exact -- the body says how many it did not
# list, so nothing is hidden, only deferred to the full check.
_MAX_LINES = 5

_KIND_LABEL = {"empty_slot": "EMPTY", "out": "OUT", "bye": "BYE", "bye_next_week": "BYE+1"}


def _when(moment: dt.datetime | None, tz: dt.tzinfo) -> str:
    if moment is None:
        return "deadline unknown"
    return moment.astimezone(tz).strftime("%a %-I:%M %p")


def _line(finding, tz: dt.tzinfo) -> str:
    label = _KIND_LABEL.get(finding.kind, finding.kind.upper())
    if finding.player_name:
        who = f"{finding.player_name} ({finding.lineup_slot})"
    else:
        who = f"{finding.lineup_slot} slot is empty"
    line = f"{label} {who} — {finding.fix.verb} by {_when(finding.deadline, tz)}"
    if finding.replacements:
        line += f"\n    start {finding.replacements[0]}"
    elif finding.ir_candidates:
        line += f"\n    nothing on the bench; on IR: {finding.ir_candidates[0]}"
    else:
        line += "\n    nothing on the bench fits"
    return line


def notification_for(
    result: CheckResult,
    tz: dt.tzinfo,
    fixes: list | None = None,
) -> Notification | None:
    """What to send, or `None` when nothing has earned an interruption.

    `fixes` overrides which findings go in the message, so the repeat policy
    (`notify/policy.py`) can hand over the subset that is allowed to interrupt
    right now. The count in the title then describes what is *being sent*, not
    what exists -- a title saying "6 lineup fixes" above two lines would read
    as truncation rather than as policy.
    """
    fixes = result.actionable if fixes is None else fixes
    if not fixes:
        return None

    count = len(fixes)
    noun = "fix" if count == 1 else "fixes"
    title = f"{count} lineup {noun} — week {result.week}"

    shown = fixes[:_MAX_LINES]
    parts = [_line(f, tz) for f in shown]
    if len(fixes) > len(shown):
        parts.append(f"+{len(fixes) - len(shown)} more — run `ffcoach check`")

    if result.blind_spots:
        parts.append(
            "Could not check everything: " + "; ".join(result.blind_spots)
        )

    return Notification(title=title, body="\n".join(parts), tier="interrupt")
