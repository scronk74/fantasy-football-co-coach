"""One bench player cannot fix two slots, and the planner has to know it."""

from __future__ import annotations

from ffcoach.advisors.roster_plan import assign_replacements


def test_the_only_candidate_goes_to_exactly_one_opening():
    """The defect this module exists for.

    Two OUT receivers and one healthy bench WR used to produce two findings
    that each named him. Each card was true; the pair was impossible.
    """
    a, b = assign_replacements([("Solo WR",), ("Solo WR",)])
    assigned = [x.assigned for x in (a, b)]
    assert sorted(x for x in assigned if x) == ["Solo WR"]
    assert None in assigned


def test_the_uncovered_opening_offers_nobody_at_all():
    a, b = assign_replacements([("Solo WR",), ("Solo WR",)])
    loser = a if a.assigned is None else b
    assert loser.offered == ()


def test_a_deep_bench_covers_every_opening():
    result = assign_replacements([("X", "Y"), ("X", "Y")])
    assert {r.assigned for r in result} == {"X", "Y"}


def test_the_most_constrained_opening_is_served_first():
    """A dedicated RB slot must not lose its only option to FLEX.

    Served in roster order, FLEX (which the WR could also fill) would take the
    RB and leave the RB slot with nothing.
    """
    flex, rb = assign_replacements([("A Back", "A Receiver"), ("A Back",)])
    assert rb.assigned == "A Back"
    assert flex.assigned == "A Receiver"


def test_results_come_back_in_the_order_they_were_given():
    """Assignment order is an internal detail; callers zip against findings."""
    result = assign_replacements([(), ("X",), ()])
    assert [r.assigned for r in result] == [None, "X", None]


def test_leftovers_are_offered_as_alternates_to_everyone_eligible():
    """With more bench than openings, a single problem still reads as a choice."""
    (only,) = assign_replacements([("X", "Y", "Z")])
    assert only.assigned == "X"
    assert only.alternates == ("Y", "Z")


def test_an_assigned_player_is_never_anyone_elses_alternate():
    """Following any card's primary suggestion can never double-book."""
    a, b = assign_replacements([("X", "Y"), ("X", "Y")])
    for one in (a, b):
        assert one.assigned not in one.alternates
    assert a.alternates == () and b.alternates == ()


def test_no_openings_is_not_an_error():
    assert assign_replacements([]) == []


def test_assignment_is_deterministic():
    args = [("X", "Y"), ("Y", "Z"), ("X", "Z")]
    assert assign_replacements(args) == assign_replacements(args)


# --- certainty breaks ties (E6) ------------------------------------------


def test_a_tie_goes_to_the_more_certain_problem():
    """A definite zero beats a maybe for the last usable bench player.

    Before the inactives sweep every opening was a certain zero, so the tie
    fell to input order -- arbitrary, but never wrong. With `at_risk` in the
    mix it would be wrong: benching a Questionable starter who then plays
    costs points, leaving an OUT starter in the lineup guarantees losing them.
    """
    out, at_risk = assign_replacements(
        [("Solo RB",), ("Solo RB",)], priorities=[0, 1]
    )
    assert out.assigned == "Solo RB"
    assert at_risk.assigned is None


def test_certainty_does_not_override_being_the_only_option():
    """Constraint still comes first, and that is what serves both openings.

    The certain zero has two candidates and the doubtful one has a single
    candidate they share. Priority-first would hand the shared player to the
    certain zero and leave the other opening empty; most-constrained-first
    gives each of them somebody.
    """
    certain, doubtful = assign_replacements(
        [("Shared", "Spare"), ("Shared",)], priorities=[0, 1]
    )
    assert doubtful.assigned == "Shared"
    assert certain.assigned == "Spare"


def test_priorities_are_optional_and_default_to_equal():
    with_none = assign_replacements([("A",), ("A",), ("B", "A")])
    with_flat = assign_replacements([("A",), ("A",), ("B", "A")], priorities=[0, 0, 0])
    assert with_none == with_flat


def test_a_priority_list_of_the_wrong_length_is_refused():
    """Silently zipping short would give later openings an unstated priority."""
    try:
        assign_replacements([("A",), ("B",)], priorities=[0])
    except ValueError as exc:
        assert "one per opening" in str(exc)
    else:
        raise AssertionError("expected ValueError")
