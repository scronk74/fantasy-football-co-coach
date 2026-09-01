"""Hand out bench players so no two problems are told to use the same one.

`find_replacements` answers one slot's question well and every slot's question
badly. Run independently per broken slot, it has no memory: two OUT receivers
with one healthy bench WR produce two findings that each name him, and fixing
either leaves the other exactly as broken as before. Each card is individually
true and the set is jointly impossible -- the worst kind of wrong, because
every part of it survives inspection.

So assignment is a roster-level decision, made once across all openings, and it
lives here rather than in the advisor: detection says what is broken, planning
says who covers it.

**Most-constrained-first.** Openings are served in order of how few candidates
they have. A league starting RB and FLEX with one healthy bench RB and one
healthy bench WR should send the RB to the RB slot; served in roster order the
RB slot might get nothing while FLEX -- which the WR could have filled -- takes
him. Ordering by candidate count gets that right without a full matching
solver, and ties break on the caller's original order so the output is
deterministic.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Assignment:
    """Who is reserved for one opening, and who else is going spare."""

    # The bench player this opening may use. None when the pool ran out --
    # which is a finding in itself: the slot needs an acquisition, not a swap.
    assigned: str | None
    # Eligible candidates nobody was assigned. Safe to show: every opening
    # already holds its own reservation, so following the primary suggestion
    # can never double-book. Shown so a single problem with a deep bench still
    # reads as a choice rather than an order.
    alternates: tuple[str, ...] = ()

    @property
    def offered(self) -> tuple[str, ...]:
        """Assignment first, then alternates -- what the finding may name."""
        return ((self.assigned,) if self.assigned else ()) + self.alternates


def assign_replacements(
    candidates_per_opening: list[tuple[str, ...]],
) -> list[Assignment]:
    """Reserve at most one candidate per opening; returns results in input order.

    Takes each opening's eligible-candidate list rather than the roster, so the
    eligibility rules stay in the advisor and this stays a pure allocation
    problem.
    """
    order = sorted(
        range(len(candidates_per_opening)),
        key=lambda i: (len(candidates_per_opening[i]), i),
    )

    taken: dict[int, str] = {}
    claimed: set[str] = set()
    for i in order:
        for name in candidates_per_opening[i]:
            if name not in claimed:
                taken[i] = name
                claimed.add(name)
                break

    return [
        Assignment(
            assigned=taken.get(i),
            alternates=tuple(n for n in names if n not in claimed),
        )
        for i, names in enumerate(candidates_per_opening)
    ]
