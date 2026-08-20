import pytest

from ffcoach.model.players import POSITIONS, Player, normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ja'Marr Chase", "jamarrchase"),
        ("JA'MARR CHASE", "jamarrchase"),
        ("Ja Marr  Chase", "jamarrchase"),
        ("Kenneth Walker III", "kennethwalker"),
        ("Michael Pittman Jr.", "michaelpittman"),
        ("Marvin Harrison Jr", "marvinharrison"),
        ("Amon-Ra St. Brown", "amonrastbrown"),
        ("  Bijan Robinson  ", "bijanrobinson"),
        ("Eddy Pineiro", "eddypineiro"),
        ("Eddy Piñeiro", "eddypineiro"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_positions_are_the_agreed_set():
    assert POSITIONS == ("QB", "RB", "WR", "TE", "K", "DEF")


def test_player_is_hashable_and_frozen():
    p = Player(
        name="Bijan Robinson",
        position="RB",
        team="ATL",
        adp=1.7,
        stdev=0.8,
        bye=11,
        times_drafted=1154,
        injury_status=None,
        sleeper_id="9509",
    )
    assert hash(p)
    with pytest.raises(AttributeError):
        p.adp = 2.0


def test_player_key_matches_normalized_name_and_position():
    p = Player(
        name="Kenneth Walker III",
        position="RB",
        team="SEA",
        adp=30.2,
        stdev=5.0,
        bye=8,
        times_drafted=400,
        injury_status=None,
        sleeper_id=None,
    )
    assert p.key == ("kennethwalker", "RB")
