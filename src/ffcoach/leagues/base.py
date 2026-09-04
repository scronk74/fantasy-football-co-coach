"""The internal league/team model every adapter maps into.

Pure module: no I/O, no clock. ESPN is today's only implementation of
`LeagueAdapter`; this is the seam that keeps report building and the UI
from knowing that -- a second platform later satisfies the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

IR_SLOT = "IR"
BENCH_SLOTS = ("BN", IR_SLOT)

# What a roster entry's slot or pro team becomes when ESPN sends an id we do
# not recognize. Never "BN" and never "FA": defaulting an unknown slot to bench
# hides a real starter from every check, and defaulting an unknown pro team to
# free agent makes him look like someone with no game. Both are false silence,
# which is the one failure mode this product cannot tolerate. UNKNOWN is not a
# bench slot, so an unknown-slot player is still evaluated as a starter, and it
# matches no schedule row, so his lock time reads as unknown rather than absent.
UNKNOWN = "UNKNOWN"


# Statuses that guarantee a zero. QUESTIONABLE and DOUBTFUL are deliberately
# absent: they are uncertain, and acting on them is the inactives sweep's job,
# not this one's.
CERTAIN_OUT = ("OUT", "INJURY_RESERVE", "SUSPENSION", "IR")


@dataclass(frozen=True)
class RosterEntry:
    player_name: str
    position: str
    nfl_team: str
    lineup_slot: str
    injury_status: str | None = None

    @property
    def is_starter(self) -> bool:
        return self.lineup_slot not in BENCH_SLOTS

    @property
    def is_certainly_out(self) -> bool:
        if not self.injury_status:
            return False
        return self.injury_status.strip().upper() in CERTAIN_OUT


@dataclass(frozen=True)
class Team:
    team_id: str
    name: str
    owner: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    roster: tuple[RosterEntry, ...]
    is_user_team: bool = False

    @property
    def record(self) -> str:
        if self.ties:
            return f"{self.wins}-{self.losses}-{self.ties}"
        return f"{self.wins}-{self.losses}"


@dataclass(frozen=True)
class WaiverSettings:
    """When claims process, and whether the league bids money for them.

    Read rather than assumed: the ESPN default league processes waivers on
    *six* days a week at 11:00, not the "Wednesday morning" a reasonable
    person would guess. Getting this wrong means alerting after the claim
    window rather than before it, which is the whole point of the deadline.
    """

    process_days: tuple[str, ...] = ()
    process_hour: int = 0
    # False means waiver priority rather than FAAB. Spec UX rule 5: never
    # render a dollar figure unless the league actually uses one.
    uses_budget: bool = False

    @property
    def is_known(self) -> bool:
        return bool(self.process_days)


class LockMode(Enum):
    """When a starting slot stops being changeable."""

    # Each player locks at his own kickoff. ESPN's default, and the only value
    # verified against a live league.
    PER_PLAYER = "per_player"
    # The whole lineup locks at the week's first kickoff. Under this rule a
    # Sunday alert about a Monday-night starter is pointless -- he locked on
    # Thursday -- which is why the mode has to be read rather than assumed.
    WEEKLY = "weekly"


# The value ESPN returned on a live public league. Recognizing *this* string is
# what makes the mode knowable: the per-player case is confirmed, so anything
# else present is by elimination the weekly one. That inverts the dependency --
# we never needed the weekly spelling, only the default's.
PER_PLAYER_LOCKTIME = "INDIVIDUAL_GAME"


@dataclass(frozen=True)
class LineupLock:
    """The lock mode plus how confidently we know it.

    Provenance travels with the value for the same reason it does on
    `WeekResolution`: this setting silently changes every deadline the product
    emits, so a guess must be visible as a guess rather than presented as fact.
    """

    mode: LockMode = LockMode.PER_PLAYER
    raw: str | None = None
    # True when the league published nothing and PER_PLAYER was assumed.
    assumed: bool = False
    # True when the league published a value we do not recognize.
    unrecognized: bool = False

    @property
    def is_weekly(self) -> bool:
        return self.mode is LockMode.WEEKLY

    @property
    def note(self) -> str | None:
        """What to log, or None when the setting was read and understood."""
        if self.assumed:
            return (
                "league published no lineupLocktimeType; assuming each player "
                "locks at his own kickoff (ESPN's default). If this league "
                "locks all lineups at the week's first game, deadlines will "
                "read later than they are."
            )
        if self.unrecognized:
            return (
                f"unrecognized lineupLocktimeType {self.raw!r}; treating it as "
                "a weekly lock, which deadlines earlier and so fails safe."
            )
        return None


@dataclass(frozen=True)
class League:
    name: str
    season: int
    teams: tuple[Team, ...]
    # Lineup slot -> how many the league starts, from ESPN's
    # rosterSettings.lineupSlotCounts. Empty when settings were not fetched,
    # in which case the empty-slot check is skipped rather than guessed.
    roster_slots: dict[str, int] = field(default_factory=dict)
    # ESPN's own week number. Taken rather than derived: computing it from the
    # calendar means owning the rollover moment, and a rollover bug alerts
    # about the wrong week entirely.
    current_week: int | None = None
    waivers: WaiverSettings = WaiverSettings()
    lineup_lock: LineupLock = LineupLock()
    # ESPN's `draftDetail.drafted`. `None` means the field was absent, which is
    # not the same as False -- an unknown draft state must not suppress checks.
    # Before the draft every starting slot is legitimately empty, and reporting
    # nine "claim someone by Friday" findings for a roster the draft will fill
    # on Monday is the exact wolf-crying that makes an alert channel worthless.
    draft_completed: bool | None = None
    # Things the adapter could not interpret: an unrecognized lineup slot id, a
    # pro team we have no abbreviation for, a waiver hour outside 0-23. Carried
    # on the model rather than logged at the parse site so they survive into the
    # payload and the CLI, where someone will actually see them.
    diagnostics: tuple[str, ...] = ()

    @property
    def starting_slots(self) -> dict[str, int]:
        return {s: n for s, n in self.roster_slots.items() if s not in BENCH_SLOTS}


@runtime_checkable
class LeagueAdapter(Protocol):
    """Anything that can produce the current state of the league.

    `manual` (a hand-filled YAML roster) and platform scrapers are both
    expected implementations eventually; nothing downstream should import
    a specific adapter.
    """

    def fetch_league(self) -> League: ...
