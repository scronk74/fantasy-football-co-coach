"""Find starters who cannot score, and who on the bench could replace them.

Pure module: no I/O, no clock of its own -- `now` is passed in. Emits
structured findings, never prose (spec design rule 2).

**Everything here is a fact, not an estimate.** A player whose team is on bye
scores zero. A player ruled OUT scores zero. Neither conclusion depends on a
projection being any good, which is why this ships before the projection
aggregation work and why its alerts are allowed to interrupt the user.

Replacement suggestions are held to the same standard: this module says *"this
bench player is healthy and actually plays this week"*, never *"this bench
player will score more"*. The latter needs projections and belongs to a later
phase.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ffcoach.leagues.base import RosterEntry, Team
from ffcoach.sources.schedule import Schedule

# Which bench positions may fill a starting slot.
_SLOT_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "QB": ("QB",),
    "RB": ("RB",),
    "WR": ("WR",),
    "TE": ("TE",),
    "FLEX": ("RB", "WR", "TE"),
    "K": ("K",),
    "DEF": ("DEF",),
}

# Lower sorts first. A bye is knowable days ahead; an OUT ruling often is not,
# so it is the more urgent surprise.
_SEVERITY = {"out": 0, "bye": 1}


@dataclass(frozen=True)
class LineupFinding:
    kind: str  # "bye" | "out"
    player_name: str
    position: str
    lineup_slot: str
    nfl_team: str
    reason: str
    replacements: tuple[str, ...]
    kickoff: dt.datetime | None
    locked: bool

    @property
    def severity(self) -> int:
        return _SEVERITY.get(self.kind, 9)


def _eligible(slot: str, position: str) -> bool:
    return position in _SLOT_ELIGIBILITY.get(slot, (slot,))


def _reason(kind: str, player: RosterEntry, replacements: tuple[str, ...]) -> str:
    """One short sentence explaining the finding.

    Mirrors the clause-joining idiom in advisors/draft.py:_reason -- spec UX
    rule 4, no unexplained flag in either mode.
    """
    if kind == "bye":
        head = f"{player.nfl_team} is on bye"
    else:
        status = (player.injury_status or "OUT").replace("_", " ").title()
        head = f"Listed {status}"

    if not replacements:
        return f"{head}, and no healthy bench player fits this slot."
    if len(replacements) == 1:
        return f"{head}. {replacements[0]} is available and plays this week."
    listed = ", ".join(replacements[:2])
    return f"{head}. Available this week: {listed}."


def find_replacements(
    team: Team, slot: str, schedule: Schedule, week: int
) -> tuple[str, ...]:
    """Bench players who fit the slot, are healthy, and actually play.

    No projections involved -- purely "can this person score at all".
    """
    out: list[str] = []
    for entry in team.roster:
        if entry.is_starter or not _eligible(slot, entry.position):
            continue
        if entry.is_certainly_out:
            continue
        if schedule.is_on_bye(entry.nfl_team, week):
            continue
        out.append(entry.player_name)
    return tuple(out)


def find_problems(
    team: Team,
    schedule: Schedule,
    week: int,
    now: dt.datetime,
) -> list[LineupFinding]:
    """Starters who cannot score this week, most urgent first.

    Findings whose kickoff has already passed are still returned, flagged
    `locked`, so callers can report them without alerting. Silently dropping
    them would make a missed player indistinguishable from a clean lineup.
    """
    findings: list[LineupFinding] = []

    for entry in team.roster:
        if not entry.is_starter:
            continue

        on_bye = schedule.is_on_bye(entry.nfl_team, week)
        if entry.is_certainly_out:
            kind = "out"
        elif on_bye:
            kind = "bye"
        else:
            continue

        kickoff = schedule.kickoff(entry.nfl_team, week)
        replacements = find_replacements(team, entry.lineup_slot, schedule, week)

        findings.append(
            LineupFinding(
                kind=kind,
                player_name=entry.player_name,
                position=entry.position,
                lineup_slot=entry.lineup_slot,
                nfl_team=entry.nfl_team,
                reason=_reason(kind, entry, replacements),
                replacements=replacements,
                kickoff=kickoff,
                locked=kickoff is not None and kickoff <= now,
            )
        )

    findings.sort(key=lambda f: (f.locked, f.severity, f.player_name))
    return findings


def actionable(findings: list[LineupFinding]) -> list[LineupFinding]:
    """Only what the user can still do something about."""
    return [f for f in findings if not f.locked]
