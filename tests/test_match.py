from pathlib import Path

from ffcoach.model.players import Player
from ffcoach.sources.crosswalk import parse_crosswalk
from ffcoach.sources.match import enrich

CROSSWALK_FIXTURE = Path(__file__).parent / "fixtures" / "db_playerids.csv"


def player(name, position="RB", team="ATL"):
    return Player(
        name=name,
        position=position,
        team=team,
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


def crosswalk():
    return parse_crosswalk(CROSSWALK_FIXTURE.read_text())


# --- name-only behavior, unchanged from before the crosswalk existed ---


def test_enrich_attaches_sleeper_id_and_injury():
    result = enrich([player("Bijan Robinson")], META)
    assert result.players[0].sleeper_id == "9509"
    assert result.unmatched == []


def test_enrich_carries_injury_status():
    result = enrich([player("Kenneth Walker III")], META)
    assert result.players[0].injury_status == "Questionable"


def test_enrich_reports_unmatched_rather_than_dropping():
    result = enrich([player("Nobody Here")], META)
    assert len(result.players) == 1
    assert result.players[0].sleeper_id is None
    assert result.unmatched == ["Nobody Here"]


def test_enrich_does_not_match_across_positions():
    result = enrich([player("Bijan Robinson", position="WR")], META)
    assert result.players[0].sleeper_id is None
    assert result.unmatched == ["Bijan Robinson"]


def test_enrich_preserves_order_and_length():
    players = [player("Bijan Robinson"), player("Nobody Here"), player("Kenneth Walker III")]
    result = enrich(players, META)
    assert [p.name for p in result.players] == [p.name for p in players]


def test_enrich_reports_no_fuzzy_matches_without_a_crosswalk():
    result = enrich([player("Bijan Robinson")], META)
    assert result.fuzzy == []


# --- crosswalk-backed identity ---


def test_enrich_attaches_crosswalk_ids():
    result = enrich([player("Bijan Robinson")], META, crosswalk=crosswalk())
    ids = result.players[0].ids
    assert ids.sleeper_id == "9509"
    assert ids.espn_id
    assert ids.gsis_id
    assert ids.mfl_id


def test_enrich_marks_exact_matches_as_exact():
    result = enrich([player("Bijan Robinson")], META, crosswalk=crosswalk())
    assert result.players[0].match_confidence == "exact"
    assert result.fuzzy == []


def test_enrich_reports_surname_only_matches_as_fuzzy():
    # FFC says "Kenny Gainwell"; the crosswalk says "Kenneth Gainwell".
    result = enrich([player("Kenny Gainwell", team="PIT")], META, crosswalk=crosswalk())
    assert result.players[0].match_confidence == "fuzzy"
    assert result.fuzzy == ["Kenny Gainwell"]


def test_enrich_resolves_nicknames_through_the_curated_alias():
    result = enrich(
        [player("Andy Borregales", position="K", team="NE")], META, crosswalk=crosswalk()
    )
    assert result.players[0].ids.sleeper_id == "12713"
    assert result.players[0].match_confidence == "exact"
    assert result.fuzzy == []


def test_enrich_prefers_metadata_looked_up_by_id_over_name():
    # Name index deliberately holds the wrong injury status; the id index
    # must win.
    by_name = {("bijanrobinson", "RB"): {"player_id": "WRONG", "injury_status": "Out"}}
    by_id = {"9509": {"player_id": "9509", "injury_status": None}}
    result = enrich([player("Bijan Robinson")], by_name, crosswalk=crosswalk(), meta_by_id=by_id)
    assert result.players[0].sleeper_id == "9509"
    assert result.players[0].injury_status is None


def test_enrich_falls_back_to_name_when_id_lookup_misses():
    by_id = {}
    result = enrich([player("Bijan Robinson")], META, crosswalk=crosswalk(), meta_by_id=by_id)
    assert result.players[0].sleeper_id == "9509"


def test_enrich_marks_team_defenses_unresolved_without_calling_them_fuzzy():
    # Team defenses are absent from the crosswalk by design.
    result = enrich([player("Ravens", position="DEF", team="BAL")], META, crosswalk=crosswalk())
    assert result.players[0].match_confidence == "unresolved"
    assert result.fuzzy == []
