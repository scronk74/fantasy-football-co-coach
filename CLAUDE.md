# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                          # install; Python 3.12 is pinned via .python-version
uv run pytest                    # full Python suite (offline, no network)
uv run pytest tests/test_match.py::test_enrich_attaches_crosswalk_ids -v   # single test
npm test                         # browser logic; installs no npm packages
```

`npm test` runs `node --test web/*.test.js`. The glob matters: `node --test web/` fails on
Node 26, which treats a bare path as a module entry point rather than a directory to scan.

```bash
uv run ffcoach build             # fetch data -> web/data/board.json
uv run ffcoach league            # ESPN league/rosters -> web/data/league.json
uv run ffcoach league --fixture tests/fixtures/espn_league.json   # no ESPN access needed
uv run ffcoach refresh           # populate the cache only
uv run ffcoach doctor            # print config and cache state
```

View pages through VS Code Live Server, not by opening the file. `file://` blocks the
`fetch()` of local JSON under CORS.

## Architecture

### The dividing rule

Deterministic Python core; Claude as the coach. **If it is the same every time it is a
script; if it needs judgment it is the skill.** Advisors emit structured findings, never
prose — a Claude Code skill (not yet built) reads the CLI's JSON and turns findings into
coaching. This also controls token cost: scripts fetch and cache megabytes, the skill
receives a compact summary.

### Pipeline

```
sources/ -> cache (SQLite) -> model/ -> advisors/ -> report/ -> web/data/*.json -> web/
```

`model/` is pure: no network, no filesystem, no clock. That is the layer that must never be
wrong, so it has no moving parts.

### Every source module follows one template

`sources/ffcalc.py` is the canonical example; `sleeper.py`, `crosswalk.py`, and
`leagues/espn_client.py` all copy it. New sources should too:

- `*_URL` constant, `TTL_SECONDS`, and either a `CACHE_KEY` constant or a `_cache_key()`
  function when the resource is parameterized
- a module-specific `*Unavailable(Exception)`
- a **`fetch_*` / `parse_*` split**: `fetch_*` does I/O and returns raw response text;
  `parse_*` is pure, text in, typed objects out, and raises the module's exception with
  "parse" in the message on malformed input (tests match on that word)
- injectable `cache` and `client: httpx.Client | None = None`, with the `owns_client`
  ownership dance and **stale-cache fallback on failure** — a failed fetch on a Sunday
  morning serves old data rather than crashing

`Cache` also takes an injectable clock (`now: Callable[[], float]`), which is how TTL
expiry is tested without sleeping.

### Player identity is resolved before matching

Sources have unrelated ID spaces. `sources/crosswalk.py` (DynastyProcess) maps one player
across MFL / Sleeper / ESPN / GSIS / FantasyPros / PFR / CBS at once, so identity is
resolved **once, by ID**, rather than by matching names pairwise between every pair of
sources. Name matching has already failed here twice — accented characters, and nicknames.

Non-obvious properties of that file, all verified against live data:

- Missing values are the literal string `"NA"`, not empty cells. Every ID column reads
  "100% populated" until you account for it; real coverage is 52–65%.
- `merge_name` is a **curated alias**, not a lowercased `name`: "Andres Borregales" carries
  "andy borregales". Both fields are indexed, and it is the only reason nickname-using
  sources resolve.
- Ambiguity is broken by preferring entries with a modern platform ID, then by team. That
  is what separates Marvin Harrison Jr. from his Hall-of-Fame father — `normalize_name`
  strips the "Jr." suffix, so both collapse to one key.
- **Team defenses are absent from the crosswalk entirely.** They match by name only and
  will always report as `unresolved`. This is structural, not a bug.

`enrich()` returns an `EnrichResult` (players / unmatched / **fuzzy**). Surname-only matches
are reported as fuzzy rather than applied silently, so a wrong bind is visible.

### Nothing is dropped or guessed silently

A failed source serves stale cache and marks the payload stale. Unmatched players are
reported, never omitted. When identity is still ambiguous, `resolve()` returns
`unresolved` rather than picking one. This is a deliberate, load-bearing property.

### Browser layer

No framework, no build step, no npm packages shipped. The split is enforced:

**If it computes, it lives in `render.js` / `league_render.js` and has a test. If it touches
the DOM, it lives in `main.js` / `league_main.js` and stays trivial enough to read.**

`web/nav.js` holds one `PAGES` list driving the nav on every page — adding a section is one
entry, not per-page markup edits. A test fails if page names get hardcoded back into
`navHtml`.

## Binding UX rules (enforced by tests, not just convention)

These come from direct user feedback and have executable assertions behind them:

1. **Standard terminology is never hidden or renamed.** The interface says "ADP", not
   "Typical pick". Terms are *annotated*, never replaced —
   `render.test.js` asserts ADP is never renamed away.
2. **Explain mode annotates only.** Turning it on never changes layout or ordering, only
   what is annotated. Default view assumes a seasoned player.
3. **No dollar figures.** The league uses waiver priority, not a bidding budget. Both
   `test_report.py` and `render.test.js` assert no `$` is ever emitted.
4. **Every recommendation states its reason inline**, in both modes. No unexplained stars
   or flags — see `advisors/draft.py::_reason`.

## Config

- `league.yaml` — league settings. Gitignored; copy from `league.example.yaml`.
- `espn.yaml` — ESPN `espn_s2` / `SWID` session cookies. Gitignored; copy from
  `espn.example.yaml`. Kept **separate** from `league.yaml` so that file stays safe to share
  or screenshot. These cookies authenticate as the user; there is no documented expiry and
  no refresh endpoint, so `EspnAuthError` (401/403) is raised distinctly and deliberately
  does **not** fall back to stale cache.

Nothing about league format may be hardcoded — scoring, roster slots, team count, and
waiver system all come from config.

## Testing

Every module ships with tests, including browser code. Sources are tested against committed
fixtures with a mocked `httpx.MockTransport`, so the suite is deterministic and offline.
See the `client_returning()` helper duplicated across source tests.

`tests/fixtures/espn_league.json` is **hand-built and unverified against a live ESPN
league** — the league invite has not arrived. Tests passing proves the parser is internally
consistent, not that it matches ESPN. Its header comment says so; replace it with a real
cookie-scrubbed capture when possible.

## Workflow

Feature branches with PRs into `main` — never a direct merge. CI (`.github/workflows/test.yml`)
runs both suites on every PR.

Design docs live in `docs/superpowers/specs/`; the spec records phasing and deliberately
deferred work (smack talk, per-alert notification toggles) with rationale.
