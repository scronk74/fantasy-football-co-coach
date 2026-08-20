"""The Player record every layer passes around.

Pure module: no network, no filesystem, no clock.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

_SUFFIXES = ("jr", "sr", "ii", "iii", "iv", "v")
_NON_ALPHA = re.compile(r"[^a-z]+")


def normalize_name(name: str) -> str:
    """Collapse a display name to a stable join key.

    Two sources with unrelated ID spaces are matched on this plus position,
    so it must survive punctuation, casing, spacing, and generational
    suffixes. Diacritics are transliterated rather than dropped -- sources
    disagree on whether "Pineiro" carries an accent, so both must reduce to
    the same plain-ASCII key.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    lowered = ascii_name.lower().strip()
    words = [_NON_ALPHA.sub("", w) for w in lowered.split()]
    words = [w for w in words if w]
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return "".join(words)


@dataclass(frozen=True)
class Player:
    name: str
    position: str
    team: str
    adp: float
    stdev: float
    bye: int | None
    times_drafted: int
    injury_status: str | None
    sleeper_id: str | None

    @property
    def key(self) -> tuple[str, str]:
        return normalize_name(self.name), self.position
