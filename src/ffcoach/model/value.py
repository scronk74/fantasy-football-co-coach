"""Availability odds: will he still be there at my next pick?

Spec UX rules 1 and 3: the raw number is always shown, and this module
supplies the plain-language reading that sits beside it under explain mode.
No output here ever mentions currency.

There is deliberately **no bargain/reach verdict**. Calling a pick a bargain
requires a ranking derived independently of the market; this project has no
projection model, so its only ordering *is* ADP order. A verdict computed
from `adp - rank` against an ADP-derived rank measures the gap between a
continuous scale and a dense integer index -- an artifact that grows with
depth, not a judgment. See docs/review-reply-2026-08-31.md.
"""

from __future__ import annotations

import math

AVAILABILITY_TEXT = {
    "gone": "Almost certainly drafted before pick {pick}. Take him now or move on.",
    "toss-up": "Roughly a coin flip whether he lasts to pick {pick}.",
    "likely": "Very likely still available at pick {pick}, so you can wait.",
}


def _probability_available_at(adp: float, stdev: float, pick: int) -> float:
    """P(this player is still on the board at `pick`)."""
    if stdev <= 0:
        return 1.0 if adp > pick else 0.0
    z = (adp - pick) / (stdev * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def availability(adp: float, stdev: float, pick: int) -> str:
    p = _probability_available_at(adp, stdev, pick)
    if p >= 0.65:
        return "likely"
    if p <= 0.25:
        return "gone"
    return "toss-up"


def availability_text(a: str, pick: int) -> str:
    try:
        return AVAILABILITY_TEXT[a].format(pick=pick)
    except KeyError:
        raise ValueError(f"unknown availability: {a!r}") from None
