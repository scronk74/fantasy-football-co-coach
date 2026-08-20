from ffcoach.model.players import Player
from ffcoach.model.tiers import assign_tiers


def p(name, adp):
    return Player(
        name=name,
        position="RB",
        team="X",
        adp=adp,
        stdev=1.0,
        bye=None,
        times_drafted=1,
        injury_status=None,
        sleeper_id=None,
    )


def test_empty_input_returns_empty():
    assert assign_tiers([]) == []


def test_single_player_is_tier_one():
    assert assign_tiers([p("a", 1.0)]) == [1]


def test_evenly_spaced_players_stay_in_one_tier():
    players = [p(str(i), float(i)) for i in range(1, 8)]
    assert assign_tiers(players) == [1] * 7


def test_large_gap_starts_a_new_tier():
    players = [p("a", 1.0), p("b", 2.0), p("c", 3.0), p("d", 20.0), p("e", 21.0)]
    assert assign_tiers(players) == [1, 1, 1, 2, 2]


def test_multiple_cliffs_produce_multiple_tiers():
    players = [p("a", 1.0), p("b", 2.0), p("c", 15.0), p("d", 16.0), p("e", 40.0)]
    assert assign_tiers(players) == [1, 1, 2, 2, 3]


def test_lower_multiplier_splits_more_aggressively():
    players = [p("a", 1.0), p("b", 2.0), p("c", 4.5)]
    assert assign_tiers(players, gap_multiplier=1.2) == [1, 1, 2]
    assert assign_tiers(players, gap_multiplier=5.0) == [1, 1, 1]


def test_input_order_is_preserved_not_sorted():
    players = [p("a", 1.0), p("b", 2.0), p("c", 3.0)]
    assert len(assign_tiers(players)) == len(players)
