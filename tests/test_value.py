import pytest

from ffcoach.model.value import (
    availability,
    availability_text,
    verdict,
    verdict_text,
)


def test_falling_past_adp_is_a_bargain():
    # Ranked 5th but the market takes him around 20 -> he is falling to you.
    assert verdict(rank=5, adp=20.0) == "bargain"


def test_going_near_adp_is_fair():
    assert verdict(rank=10, adp=11.0) == "fair"
    assert verdict(rank=10, adp=5.0) == "fair"


def test_taking_someone_early_is_a_reach():
    assert verdict(rank=30, adp=10.0) == "reach"


def test_threshold_is_configurable():
    assert verdict(rank=10, adp=17.0, threshold=6.0) == "bargain"
    assert verdict(rank=10, adp=17.0, threshold=20.0) == "fair"


def test_verdict_text_is_plain_language_and_mentions_no_money():
    for v in ("bargain", "fair", "reach"):
        text = verdict_text(v)
        assert text and text[0].isupper()
        assert "$" not in text


def test_verdict_text_rejects_unknown_verdict():
    with pytest.raises(ValueError, match="unknown verdict"):
        verdict_text("amazing")


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
