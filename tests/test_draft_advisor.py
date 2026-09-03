from ffcoach.advisors.draft import BoardRow, build_board
from ffcoach.config import LeagueConfig
from ffcoach.model.players import Player


def cfg(**over):
    base = dict(
        name="T",
        season=2026,
        teams=12,
        scoring="ppr",
        my_pick=7,
        roster={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 6},
    )
    base.update(over)
    return LeagueConfig(**base)


def player(name, adp, position="RB", stdev=2.0):
    return Player(
        name=name,
        position=position,
        team="ATL",
        adp=adp,
        stdev=stdev,
        bye=11,
        times_drafted=100,
        injury_status=None,
        sleeper_id=None,
    )


def test_empty_input_produces_empty_board():
    assert build_board([], cfg()) == []


def test_rank_is_sequential_from_one():
    board = build_board([player("a", 1.0), player("b", 2.0), player("c", 3.0)], cfg())
    assert [r.rank for r in board] == [1, 2, 3]


def test_rows_are_sorted_by_adp():
    board = build_board([player("b", 9.0), player("a", 1.0)], cfg())
    assert [r.name for r in board] == ["a", "b"]


def test_no_row_carries_a_value_or_verdict():
    """A row states ADP and availability; it does not grade the price.

    `value` was `adp - rank` where `rank` was the index of the ADP sort, so
    the number was an artifact of list depth, not an opinion about the
    player. See test_value.py::test_no_bargain_or_reach_verdict_is_offered.
    """
    board = build_board([player("a", 5.0), player("b", 9.0)], cfg())
    fields = set(vars(board[0]))
    assert not fields & {"value", "verdict", "verdict_text"}


def test_every_row_carries_availability_text_naming_next_pick():
    board = build_board([player("a", 1.0)], cfg(my_pick=7))
    # 12 teams picking 7th: next pick after 7 is 18.
    assert "18" in board[0].availability_text


def test_tier_break_flag_is_set_on_the_last_row_of_each_tier():
    players = [player("a", 1.0), player("b", 2.0), player("c", 30.0)]
    board = build_board(players, cfg())
    assert board[1].tier_break_after is True
    assert board[2].tier_break_after is False


def test_last_row_never_flags_a_tier_break():
    board = build_board([player("a", 1.0), player("b", 50.0)], cfg())
    assert board[-1].tier_break_after is False


def test_a_row_that_is_gone_by_your_next_pick_states_that_as_its_reason():
    """UX rule 4: nothing is highlighted without saying why, in either mode."""
    board = build_board([player("a", 1.0, stdev=1.0)], cfg(my_pick=7))
    row = board[0]
    assert row.availability == "gone"
    assert "next pick" in row.reason


def test_a_row_with_nothing_to_flag_carries_no_reason():
    board = build_board([player("a", 400.0, stdev=1.0)], cfg(my_pick=7))
    assert board[0].reason == ""


def test_injury_status_is_carried_through():
    hurt = Player(
        name="Hurt Guy",
        position="RB",
        team="ATL",
        adp=5.0,
        stdev=1.0,
        bye=9,
        times_drafted=10,
        injury_status="Questionable",
        sleeper_id="1",
    )
    board = build_board([hurt], cfg())
    assert board[0].injury_status == "Questionable"
    assert "Questionable" in board[0].reason


def test_board_row_is_frozen():
    board = build_board([player("a", 1.0)], cfg())
    assert isinstance(board[0], BoardRow)
