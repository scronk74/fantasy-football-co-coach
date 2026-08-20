from ffcoach.model.players import Player
from ffcoach.sources.match import enrich


def player(name, position="RB"):
    return Player(
        name=name,
        position=position,
        team="ATL",
        adp=10.0,
        stdev=2.0,
        bye=11,
        times_drafted=100,
        injury_status=None,
        sleeper_id=None,
    )


META = {
    ("bijanrobinson", "RB"): {"player_id": "9509", "injury_status": None},
    ("kennethwalker", "RB"): {"player_id": "8151", "injury_status": "Questionable"},
}


def test_enrich_attaches_sleeper_id_and_injury():
    out, unmatched = enrich([player("Bijan Robinson")], META)
    assert out[0].sleeper_id == "9509"
    assert unmatched == []


def test_enrich_carries_injury_status():
    out, _ = enrich([player("Kenneth Walker III")], META)
    assert out[0].injury_status == "Questionable"


def test_enrich_reports_unmatched_rather_than_dropping():
    out, unmatched = enrich([player("Nobody Here")], META)
    assert len(out) == 1
    assert out[0].sleeper_id is None
    assert unmatched == ["Nobody Here"]


def test_enrich_does_not_match_across_positions():
    out, unmatched = enrich([player("Bijan Robinson", position="WR")], META)
    assert out[0].sleeper_id is None
    assert unmatched == ["Bijan Robinson"]


def test_enrich_preserves_order_and_length():
    players = [player("Bijan Robinson"), player("Nobody Here"), player("Kenneth Walker III")]
    out, _ = enrich(players, META)
    assert [p.name for p in out] == [p.name for p in players]
