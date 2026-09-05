from ffcoach.leagues.base import LeagueAdapter, League, RosterEntry, Team


def entry(**over):
    base = dict(player_name="A Player", position="RB", nfl_team="ATL", lineup_slot="RB")
    base.update(over)
    return RosterEntry(**base)


def test_starter_slots_are_starters():
    for slot in ("QB", "RB", "WR", "TE", "FLEX", "K", "DEF"):
        assert entry(lineup_slot=slot).is_starter is True


def test_bench_and_ir_are_not_starters():
    assert entry(lineup_slot="BN").is_starter is False
    assert entry(lineup_slot="IR").is_starter is False


def team(**over):
    base = dict(
        team_id="1",
        name="T",
        owner="Steve",
        wins=5,
        losses=3,
        ties=0,
        points_for=650.0,
        points_against=600.0,
        roster=(),
    )
    base.update(over)
    return Team(**base)


def test_record_omits_ties_when_zero():
    assert team(wins=5, losses=3, ties=0).record == "5-3"


def test_record_includes_ties_when_nonzero():
    assert team(wins=5, losses=3, ties=1).record == "5-3-1"


def test_is_user_team_defaults_to_false():
    assert team().is_user_team is False


def test_league_holds_its_teams():
    t = team()
    league = League(name="The League", season=2026, teams=(t,))
    assert league.teams == (t,)


def test_espn_adapter_satisfies_league_adapter_protocol():
    class FakeAdapter:
        def fetch_league(self) -> League:
            return League(name="T", season=2026, teams=())

    assert isinstance(FakeAdapter(), LeagueAdapter)


def test_something_without_fetch_league_does_not_satisfy_protocol():
    class NotAnAdapter:
        pass

    assert not isinstance(NotAnAdapter(), LeagueAdapter)


# --- uncertain, which is neither out nor healthy (E6) ---------------------


def test_questionable_and_doubtful_are_uncertain_not_out():
    """D-010's split, from the other side.

    Treating these as OUT would bench players who mostly go on to play; not
    classifying them at all is what left the inactives sweep with no input.
    """
    for status in ("QUESTIONABLE", "DOUBTFUL"):
        assert entry(injury_status=status).is_certainly_out is False
        assert entry(injury_status=status).is_uncertain is True


def test_a_certain_out_is_not_also_uncertain():
    """Otherwise one starter yields both an `out` and an `at_risk` finding."""
    for status in ("OUT", "INJURY_RESERVE", "SUSPENSION", "IR"):
        assert entry(injury_status=status).is_uncertain is False


def test_no_status_at_all_is_healthy():
    """ESPN omits injuryStatus for the fit, which is most of a roster."""
    assert entry(injury_status=None).is_uncertain is False
    assert entry(injury_status="").is_uncertain is False
    assert entry(injury_status="   ").is_uncertain is False


def test_active_is_healthy():
    for status in ("ACTIVE", "active", "NORMAL"):
        assert entry(injury_status=status).is_uncertain is False


def test_an_unrecognized_status_counts_as_doubt_rather_than_health():
    """The direction this defaults in is the whole point.

    ESPN has renamed fields under this project twice. A new designation read as
    healthy would drop a starter out of the one check that runs while he is
    still swappable, silently. Read as doubt it costs at most one alert about a
    player who was fine.
    """
    assert entry(injury_status="GAME_TIME_DECISION").is_uncertain is True
    assert entry(injury_status="SOMETHING_ESPN_ADDED").is_uncertain is True
