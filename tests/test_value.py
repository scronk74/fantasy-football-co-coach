import pytest

from ffcoach.model.value import availability, availability_text


def test_no_bargain_or_reach_verdict_is_offered():
    """The board may not claim value it cannot compute.

    `rank` came from sorting by ADP, so `adp - rank` compared an ADP-derived
    rank against ADP itself. It measured the gap between a continuous scale
    and a dense integer index -- growing with depth, so a deep DEF at ADP 196
    on row 271 was labelled "reach". Grading market price needs an
    independent ranking, and this project has no projection model.
    """
    import ffcoach.model.value as value

    for gone in ("verdict", "verdict_text", "VERDICT_TEXT"):
        assert not hasattr(value, gone), f"{gone} is back; it cannot be computed honestly"


def test_player_well_past_his_adp_is_gone():
    # ADP 10, tight spread, your next pick is 31 -> no chance.
    assert availability(adp=10.0, stdev=2.0, pick=31) == "gone"


def test_player_well_after_your_pick_is_likely_there():
    assert availability(adp=60.0, stdev=5.0, pick=31) == "likely"


def test_player_near_your_pick_is_a_toss_up():
    assert availability(adp=31.0, stdev=4.0, pick=31) == "toss-up"


def test_wide_spread_softens_a_gone_verdict():
    tight = availability(adp=20.0, stdev=1.0, pick=31)
    wide = availability(adp=20.0, stdev=30.0, pick=31)
    assert tight == "gone"
    assert wide in ("toss-up", "likely")


def test_zero_stdev_does_not_divide_by_zero():
    assert availability(adp=10.0, stdev=0.0, pick=31) == "gone"
    assert availability(adp=90.0, stdev=0.0, pick=31) == "likely"


def test_availability_text_names_the_pick_number():
    assert "31" in availability_text("likely", pick=31)


def test_availability_text_rejects_an_unknown_bucket():
    with pytest.raises(ValueError, match="unknown availability"):
        availability_text("amazing", pick=31)
