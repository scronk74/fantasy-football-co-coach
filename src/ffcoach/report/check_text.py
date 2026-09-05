"""Render a `CheckResult` for a terminal.

Kept out of `check.py`, which stays structured (design rule 2: advisors and
the composition above them emit findings, never prose), and out of `cli.py`,
which stays thin enough to read. Pure: lines in, lines out, no clock.

Two rules from the UX list apply even here. **Status is never carried by
colour** -- there is no ANSI in this file at all; every state is a word. And
**every recommendation states its reason inline**, so no line names a player
without saying what is wrong with him.
"""

from __future__ import annotations

import datetime as dt

from ffcoach.check import CheckResult

_STATUS_LINE = {
    "all_clear": "All clear — nothing to fix, and every check ran.",
    "unverified": "Nothing found — but this run could not see everything.",
    "pre_draft": (
        "Draft has not happened yet — an empty roster is expected, "
        "so the lineup checks did not run."
    ),
}

_KIND_LABEL = {
    "empty_slot": "EMPTY",
    "out": "OUT",
    # Not "QUESTIONABLE": the label is the tool's judgement, and the player's
    # actual designation is named in the reason line underneath. Six characters
    # keeps the column aligned with the widest of the others.
    "at_risk": "RISK",
    "bye": "BYE",
    "bye_next_week": "BYE+1",
}


def _when(moment: dt.datetime | None, tz: dt.tzinfo) -> str:
    """A time a human can act on. No seconds: they imply precision we lack."""
    if moment is None:
        return "unknown"
    return moment.astimezone(tz).strftime("%a %b %-d, %-I:%M %p %Z")


def _age(seconds: float) -> str:
    if seconds <= 0:
        return "live"
    if seconds < 90:
        return f"{int(seconds)}s old"
    if seconds < 5400:
        return f"{round(seconds / 60)}m old"
    if seconds < 172800:
        return f"{round(seconds / 3600)}h old"
    return f"{round(seconds / 86400)}d old"


def _finding_lines(finding, tz: dt.tzinfo) -> list[str]:
    label = _KIND_LABEL.get(finding.kind, finding.kind.upper())
    # An empty slot has no player and no NFL team. Printing "(nobody) ()" for
    # the absent ones reads like missing data rather than the finding itself.
    who = (
        f"{finding.player_name} ({finding.nfl_team})"
        if finding.player_name
        else "no one in this slot"
    )
    head = f"  {label:<6} {finding.lineup_slot:<5} {who}"
    if not finding.is_actionable():
        head += "  — LOCKED, too late"
    else:
        head += f"  — {finding.fix.verb} by {_when(finding.deadline, tz)}"
    lines = [head, f"         {finding.reason}"]
    if finding.lock_is_estimated:
        lines.append("         (kickoff time not published yet; deadline is an estimate)")
    if finding.replacements:
        lines.append(f"         bench: {', '.join(finding.replacements)}")
    elif finding.ir_candidates:
        lines.append(
            f"         nothing on the bench fits; on IR: {', '.join(finding.ir_candidates)} "
            "(activate first — ESPN will not start a player out of IR)"
        )
    else:
        lines.append("         nothing on the bench fits")
    return lines


def render_check(result: CheckResult, tz: dt.tzinfo, league_name: str = "") -> list[str]:
    """The whole run as terminal lines, most urgent first."""
    header = f"{league_name} — " if league_name else ""
    lines = [
        f"{header}week {result.week} (from {result.week_source})",
        f"{result.team_name}",
        "",
    ]

    if result.status == "problems":
        actionable = len(result.actionable)
        total = len(result.findings)
        summary = f"{total} to fix"
        if actionable < total:
            summary += f" — {actionable} still fixable, {total - actionable} past the deadline"
        lines.append(summary)
    else:
        lines.append(_STATUS_LINE[result.status])
    lines.append("")

    for finding in result.findings:
        lines.extend(_finding_lines(finding, tz))
        lines.append("")

    # A clean week still has a deadline. Saying so is the difference between
    # "nothing is wrong" and "nothing is wrong *yet*".
    if result.next_lock is not None:
        lines.append(f"Next slot freezes: {_when(result.next_lock, tz)}")
    if result.waiver_deadline is not None:
        lines.append(f"Waivers next process: {_when(result.waiver_deadline, tz)}")

    # Never below the fold: a blind spot is why an empty finding list must not
    # be read as reassurance.
    if result.blind_spots:
        lines.append("")
        lines.append(f"Could not check everything ({len(result.blind_spots)}):")
        lines.extend(f"  - {spot}" for spot in result.blind_spots)

    if result.sources:
        lines.append("")
        lines.append(
            "Sources: "
            + " · ".join(f"{s.name} {_age(s.age_seconds)}" for s in result.sources)
        )
    return lines
