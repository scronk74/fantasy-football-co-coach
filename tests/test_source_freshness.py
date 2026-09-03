"""Freshness travels with the data, and a bad 200 cannot destroy a good cache.

Both properties were absent and both failed silently, which is why they get a
file of their own rather than a few lines appended to each source's tests.
"""

from __future__ import annotations

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.leagues.espn_client import EspnAuthError, fetch_league
from ffcoach.leagues.espn_client import _cache_key as espn_key
from ffcoach.sources.base import SourceResult, freshest
from ffcoach.sources.ffcalc import AdpUnavailable, fetch_adp
from ffcoach.sources.ffcalc import _cache_key as adp_key
from ffcoach.sources.schedule import ScheduleUnavailable, fetch_schedule


def client_returning(body: str, status: int = 200):
    def handler(request):
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


GOOD_ADP = '{"status": "Success", "players": [' \
    '{"name": "A Back", "position": "RB", "team": "KC", "adp": 1.2, "bye": 6}]}'

# A 200 with a body that is not what we asked for. This is what an expired
# session, a captive portal, or a CDN error page actually looks like.
LOGIN_PAGE = "<html><body>Please log in</body></html>"


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- a garbage 200 must not evict the last usable copy ---


def test_an_unparseable_200_does_not_replace_a_good_cached_copy(tmp_path):
    clock = FakeClock()
    cache = Cache(tmp_path / "c.sqlite3", now=clock)
    fetch_adp("ppr", 12, 2026, cache, client=client_returning(GOOD_ADP))

    clock.t += 10**6  # push the good entry past its TTL
    got = fetch_adp("ppr", 12, 2026, cache, client=client_returning(LOGIN_PAGE))

    assert got.text == GOOD_ADP, "the login page overwrote data we could still use"
    assert got.stale is True
    assert cache.get_stale(adp_key("ppr", 12, 2026))[0] == GOOD_ADP


def test_an_unparseable_200_with_no_cache_raises_rather_than_caching_it(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(AdpUnavailable):
        fetch_adp("ppr", 12, 2026, cache, client=client_returning(LOGIN_PAGE))
    assert cache.get_stale(adp_key("ppr", 12, 2026)) is None


def test_espn_session_expiry_page_does_not_poison_the_roster_cache(tmp_path):
    """ESPN answers a dead session with a 200, not a 401. That is the trap."""
    clock = FakeClock()
    cache = Cache(tmp_path / "c.sqlite3", now=clock)
    good = '{"seasonId": 2026, "teams": [], "settings": {"name": "L"}}'
    fetch_league("9", 2026, "s2", "{sw}", cache, client=client_returning(good))

    clock.t += 10**6
    got = fetch_league("9", 2026, "s2", "{sw}", cache, client=client_returning(LOGIN_PAGE))

    assert got.text == good
    assert got.stale is True
    assert cache.get_stale(espn_key("9", 2026))[0] == good


def test_a_truncated_schedule_download_does_not_replace_a_good_one(tmp_path):
    clock = FakeClock()
    cache = Cache(tmp_path / "c.sqlite3", now=clock)
    good = (
        "game_id,season,game_type,week,gameday,gametime,away_team,home_team\n"
        "x,2025,REG,1,2025-09-04,20:20,DAL,PHI\n"
    )
    fetch_schedule(2025, cache, client=client_returning(good))

    clock.t += 10**6
    got = fetch_schedule(2025, cache, client=client_returning("game_id,season\n"))

    assert got.text == good
    assert got.stale is True


def test_a_failed_fetch_with_no_cache_still_raises_the_modules_own_exception(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(ScheduleUnavailable):
        fetch_schedule(2025, cache, client=client_returning("", status=500))


# --- freshness is reported, not discarded ---


def test_a_live_fetch_reports_itself_as_live(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    got = fetch_adp("ppr", 12, 2026, cache, client=client_returning(GOOD_ADP))
    assert got.is_live is True
    assert got.age_seconds == 0.0
    assert got.stale is False


def test_a_cache_hit_inside_its_ttl_is_not_stale_but_is_not_live_either(tmp_path):
    clock = FakeClock()
    cache = Cache(tmp_path / "c.sqlite3", now=clock)
    fetch_adp("ppr", 12, 2026, cache, client=client_returning(GOOD_ADP))

    clock.t += 300
    got = fetch_adp("ppr", 12, 2026, cache, client=client_returning("", status=500))

    assert got.stale is False, "a hit inside the TTL is the cache working"
    assert got.age_seconds == pytest.approx(300)
    assert got.is_live is False


def test_stale_fallback_reports_its_true_age_and_the_error(tmp_path):
    """The whole point: this used to be indistinguishable from a live fetch."""
    clock = FakeClock()
    cache = Cache(tmp_path / "c.sqlite3", now=clock)
    fetch_adp("ppr", 12, 2026, cache, client=client_returning(GOOD_ADP))

    clock.t += 3 * 24 * 3600
    got = fetch_adp("ppr", 12, 2026, cache, client=client_returning("", status=500))

    assert got.stale is True
    assert got.age_seconds == pytest.approx(3 * 24 * 3600)
    assert "500" in got.error


def test_espn_auth_failure_never_falls_back_to_stale_cache(tmp_path):
    """Old rosters cannot repair dead cookies; serving them hides the one
    failure that needs a human."""
    clock = FakeClock()
    cache = Cache(tmp_path / "c.sqlite3", now=clock)
    good = '{"seasonId": 2026, "teams": [], "settings": {"name": "L"}}'
    fetch_league("9", 2026, "s2", "{sw}", cache, client=client_returning(good))

    clock.t += 10**6
    with pytest.raises(EspnAuthError):
        fetch_league("9", 2026, "s2", "{sw}", cache, client=client_returning("", status=401))


# --- folding several sources into one page-level number ---


def test_the_oldest_source_sets_the_pages_age():
    """A page is as old as its oldest input, not its newest."""
    age, stale = freshest(
        SourceResult("a", age_seconds=0.0),
        SourceResult("b", age_seconds=86400.0, stale=True),
        SourceResult("c", age_seconds=60.0),
    )
    assert age == 86400.0
    assert stale is True


def test_all_fresh_sources_report_no_staleness():
    assert freshest(SourceResult("a"), SourceResult("b")) == (0.0, False)


def test_no_sources_at_all_yields_no_claim_about_age():
    assert freshest(None) == (None, False)


def test_a_lookup_tables_age_does_not_age_the_page():
    """A crosswalk hit inside its TTL must not make a live board look old.

    The DynastyProcess crosswalk has a seven-day TTL; ADP has six hours. On
    2026-09-03 the crosswalk was 5.9 days old and every displayed number was
    minutes old, and the board announced "data 6d old" -- a false alarm four
    days before a draft, which is how a reader learns to ignore the banner.
    """
    age, stale = freshest(
        SourceResult("adp", age_seconds=120.0),
        lookups=(SourceResult("crosswalk", age_seconds=513668.0),),
    )
    assert age == 120.0
    assert stale is False


def test_a_stale_lookup_still_marks_the_page_stale():
    """Past its TTL a lookup is serving a fallback, and a wrong bind is visible
    on the page: the wrong player's bye week, the wrong injury badge."""
    age, stale = freshest(
        SourceResult("adp", age_seconds=0.0),
        lookups=(SourceResult("crosswalk", age_seconds=10**7, stale=True),),
    )
    assert age == 0.0
    assert stale is True


def test_a_page_built_only_from_lookups_claims_no_age():
    age, stale = freshest(lookups=(SourceResult("crosswalk", age_seconds=99.0),))
    assert age is None
    assert stale is False
