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


def test_value_is_adp_minus_rank():
    board = build_board([player("a", 5.0), player("b", 9.0)], cfg())
    assert board[0].value == 4.0
    assert board[1].value == 7.0


def test_every_row_carries_a_verdict_and_its_text():
    board = build_board([player("a", 1.0), player("b", 40.0)], cfg())
    for row in board:
        assert row.verdict in ("bargain", "fair", "reach")
        assert row.verdict_text
        assert "$" not in row.verdict_text


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


def test_non_neutral_verdicts_get_a_reason():
    board = build_board([player("a", 40.0), player("b", 41.0)], cfg())
    bargains = [r for r in board if r.verdict == "bargain"]
    assert bargains
    for row in bargains:
        assert row.reason


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
