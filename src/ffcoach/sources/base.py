"""What every source returns: the bytes, plus how much to trust them.

Sources used to return bare text. That threw away the one fact the rest of the
system needed most on a Sunday morning -- **whether this is live data or the
last copy we happened to keep.** Every module called `Cache.get_stale()`,
discarded the age it returns, and handed back a string indistinguishable from a
fresh fetch. The report layer then stamped it `stale: false` with a current
timestamp, so week-old roster data was published as current.

`SourceResult` makes freshness travel with the value, the same way provenance
travels on `WeekResolution` and `LineupLock`. A caller cannot accidentally drop
it, because there is no bare string to pass along instead.

No clock of its own: `age_seconds` is measured by the `Cache`'s injected clock,
which is how staleness is tested without sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass

from ffcoach.cache import Cache


@dataclass(frozen=True)
class SourceResult:
    """Raw response text and its provenance.

    `age_seconds` is 0.0 for a live fetch and the cache entry's true age for
    anything served from cache. `stale` is reserved for the serious case: the
    live fetch failed and we fell back to an entry that is *past its TTL*. A
    cache hit inside its TTL is not stale -- that is the cache working.
    """

    text: str
    age_seconds: float = 0.0
    stale: bool = False
    # Why the live fetch failed, when it did. Carried so the health panel can
    # say "ESPN returned 500" rather than only "old".
    error: str | None = None

    @property
    def is_live(self) -> bool:
        return self.age_seconds == 0.0 and not self.stale


def freshest(*results: SourceResult | None) -> tuple[float | None, bool]:
    """Fold several sources into one `(age_seconds, any_stale)` for a payload.

    The *oldest* age wins, not the newest: a page built from a fresh schedule
    and a three-day-old roster is a three-day-old page. Reporting the newest
    component would be a flattering lie, which is the failure this whole type
    exists to prevent.
    """
    present = [r for r in results if r is not None]
    if not present:
        return None, False
    return max(r.age_seconds for r in present), any(r.stale for r in present)


def stale_fallback(
    cache: Cache,
    key: str,
    exc: Exception,
    unavailable: type[Exception],
    what: str,
) -> SourceResult:
    """Serve the last copy we kept, or admit we have nothing.

    Reached from two places, and the second one is the point: a failed HTTP
    request, **and a 200 whose body will not parse.** An ESPN session-expiry
    page or a truncated CSV arrives with a perfectly good status code, and
    before this the raw body was written to the cache before anyone tried to
    read it -- destroying the last known-good copy at precisely the moment it
    was needed. Validating first and falling back here means a garbage 200
    costs us nothing.
    """
    kept = cache.get_stale(key)
    if kept is not None:
        text, age = kept
        return SourceResult(text=text, age_seconds=age, stale=True, error=str(exc))
    raise unavailable(f"could not fetch {what} and no cached copy exists: {exc}") from exc
