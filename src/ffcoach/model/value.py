"""Value verdicts and availability odds.

Spec UX rules 1 and 3: the raw number is always shown, and this module
supplies the plain-language reading that sits beside it under explain mode.
No output here ever mentions currency.
"""

from __future__ import annotations

import math

VERDICT_TEXT = {
    "bargain": (
        "He is lasting later than the rest of the fantasy world usually "
        "takes him, so you are getting him below his normal cost."
    ),
    "fair": (
        "He is going right about where he normally goes. No bargain, "
        "no mistake."
    ),
    "reach": (
        "You would be taking him earlier than he usually goes. Fine if you "
        "love him, but you could probably wait a round."
    ),
}

AVAILABILITY_TEXT = {
    "gone": "Almost certainly drafted before pick {pick}. Take him now or move on.",
    "toss-up": "Roughly a coin flip whether he lasts to pick {pick}.",
    "likely": "Very likely still available at pick {pick}, so you can wait.",
}


def verdict(rank: int, adp: float, threshold: float = 6.0) -> str:
    """Compare our ranking to the market's average draft position.

    Positive difference means he is falling past where he should go.
    """
    difference = adp - rank
    if difference > threshold:
        return "bargain"
    if difference < -threshold:
        return "reach"
    return "fair"


def verdict_text(v: str) -> str:
    try:
        return VERDICT_TEXT[v]
    except KeyError:
        raise ValueError(f"unknown verdict: {v!r}") from None


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
