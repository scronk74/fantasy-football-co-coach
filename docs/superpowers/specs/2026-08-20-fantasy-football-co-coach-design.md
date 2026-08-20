# Fantasy Football Co-Coach — Design

**Date:** 2026-08-20
**Status:** Approved for planning

## Problem

The user is joining a fantasy football league and does not reliably remember to
set weekly lineups, evaluate trades, or work the waiver wire. Missed deadlines,
not poor analysis, are the failure mode.

The product must therefore do two things, in this order of importance:

1. **Interrupt the user at the right moment** with a decision already made.
2. **Explain the reasoning** clearly enough for a non-expert to trust and act on.

The user is not yet a fantasy football expert, but wants to become one. The
interface therefore uses real terminology at full density and makes its meaning
available on demand, rather than paraphrasing the vocabulary away. See UX
requirements.

## Non-goals

- Live draft assistance (pick tracking against a running clock). Pre-draft
  strategy only.
- Paid data subscriptions. Free sources exclusively.
- Automatic submission of lineups, claims, or trades. The tool recommends; the
  user acts.
- A hosted service, login, or multi-user support. Single user, local.

## Constraints

- **Platform unknown.** The league was assumed to be CBS Sports, but this is
  unconfirmed. CBS has no public fantasy API; access would require authenticated
  scraping, which is brittle. The design must not depend on resolving this.
- **Free data only.** No FantasyPros, no paid projection feeds.
- **Season timing.** Spec written 2026-08-20. Draft expected within 2–4 weeks;
  Week 1 roughly three weeks out.
- **iPhone** for notifications.
- **Toolchain.** Python 3.12 via `uv`; the system Python is 3.7 and unusable.
  Node 26 installed for its built-in test runner only — no npm packages are
  installed, and none are shipped to the browser.

## Architecture

Deterministic Python core, Claude as the coach.

```
  sources/ ──→ cache (SQLite) ──→ model/ ──→ advisors/
                                                 │
                            ┌────────────────────┼────────────────────┐
                            ▼                    ▼                    ▼
                      web/data/*.json      notify/ (push)      --standalone
                      (Live Server)        (self-sufficient)   (portable HTML)
```

Arithmetic that must be reproducible lives in tested Python. Judgment that
benefits from nuance lives in a Claude Code skill that reads the CLI's JSON
output. The dividing rule: **if it is the same every time, it is a script; if it
needs judgment, it is the skill.**

This split also controls token cost. Raw player data is fetched and cached by
scripts; the skill receives a compact JSON summary rather than a multi-megabyte
payload.

### The manual league adapter

`LeagueAdapter` is an interface with several implementations. The first is
`manual`, which reads the roster from a local YAML file the user fills in once
after the draft.

Every advisor runs against that interface and does not know or care where the
roster came from. **The entire product is therefore functional without solving
platform access.** A CBS or Sleeper scraper becomes a convenience upgrade that
saves ten minutes a week, not a prerequisite. The project's largest unknown is
removed from the critical path.

### Package layout

```
src/ffcoach/
  config.py            league settings, scoring rules, paths
  cache.py             SQLite cache with per-source TTLs
  sources/             external data in
    ffcalc.py            ADP with stdev, by scoring format and team count
    sleeper.py           player database, injury status, trending adds/drops
    match.py             joins FFC and Sleeper records on name/position/team
    nflverse.py          historical stats, schedules, snap counts
    projections.py       weekly projections (Phase 2)
  leagues/             the user's team in
    base.py              LeagueAdapter protocol
    manual.py            YAML file — works day one
    sleeper.py  cbs.py   scrapers, later
  model/               pure functions, no I/O, no clock
    scoring.py           stat line + league rules -> fantasy points
    tiers.py             rankings -> tiers with meaningful gaps
    replacement.py       value over replacement by position
  advisors/            analysis -> structured findings
    draft.py  lineup.py  waivers.py  trades.py  season.py
  report/build.py      findings -> web/data/*.json
  notify/              email · ntfy · sms_gateway · pushover
  cli.py               ffcoach <command> --json
web/
  index.html
  render.js            pure functions — all logic, unit-tested
  render.test.js       node --test
  main.js              thin DOM wiring only
  style.css
  data/                generated, gitignored
tests/                 pytest
```

### Design rules

1. **`model/` is pure.** No network, no filesystem, no clock. Deterministic and
   unit-tested. This is the part that must never be wrong, so it has no moving
   parts.
2. **Advisors emit findings, not prose.** Structured JSON — *this player is on
   bye*, *this bench player out-projects a starter by 6.2*. Claude turns findings
   into coaching. Arithmetic stays reproducible; judgment stays flexible.
3. **Every external source sits behind an interface with a cache.** One file
   fails loudly rather than the system silently producing confident nonsense.
   Stale cache is served rather than crashing on a Sunday morning.

## Data sources

All free, no authentication, no API keys. Verified working 2026-08-20.

| Source | Provides | Used by |
|---|---|---|
| Fantasy Football Calculator | ADP with standard deviation, high/low, bye week, by scoring format and team count | Draft |
| Sleeper API | Player database (12k players), injury status, depth chart, trending adds/drops | Draft, waivers, lineup |
| nflverse | Historical stats, schedules, snap counts, target share | Projections, adjustments |
| ESPN public JSON | Weekly projections | Lineup, waivers |

**ADP comes from Fantasy Football Calculator, not Sleeper.** Sleeper exposes no
public aggregate-ADP endpoint. FFC does:
`https://fantasyfootballcalculator.com/api/v1/adp/{format}?teams={n}&year={yyyy}`
where format is `standard`, `half-ppr`, or `ppr`. It returns `adp`, `stdev`,
`high`, `low`, `times_drafted`, and `bye` per player. The `stdev` field is what
makes a real availability calculation possible rather than a guess.

Player identity is joined between the two sources on normalized name plus
position plus team, since their IDs are unrelated. Unmatched players are
reported, never silently dropped.

`ffcoach refresh` populates the SQLite cache from all sources. Each source
declares its own TTL; player metadata refreshes slowly, injury status quickly.

Projections start as free public consensus. A later adjustment layer — injury
recovery timelines, weather for outdoor games, projected game script,
three-week snap-count trends — is an upgrade path, not a v1 requirement. Raw
projection accuracy is not where the user's edge comes from; not missing
deadlines is.

## UX requirements

These are binding, and derive directly from user feedback on the mockups.

1. **Standard terminology is never hidden or renamed.** The interface says
   "ADP", not "Typical pick". The user's league-mates will use the real
   vocabulary, and an interface that paraphrases it away keeps the user
   dependent on the tool instead of teaching the language of the game. Terms are
   *annotated*, never replaced.
2. **"Explain mode" toggle.** The default view is dense and assumes a seasoned
   player. A persistent toggle — state saved in `localStorage`, so it survives
   reloads — reveals definitions for every term of art, plus plain-language
   interpretation alongside raw numbers. Turning it on never changes the
   *layout*, only what is annotated, so the user is not learning two different
   screens.
3. **Raw numbers keep a plain-language reading available.** A signed decimal
   like `+10.5` was misread as currency, so the column shows the number *and*,
   under explain mode, its interpretation: **Bargain / Fair / Reach**. Neither
   representation replaces the other.
4. **Every recommendation states its reason inline.** No unexplained stars,
   flags, or highlights. A recommendation that cannot be interrogated is an
   assertion. This applies in both modes — reasons are not an explain-mode
   feature.
5. **Nothing about league format is hardcoded.** Scoring, roster slots, team
   count, and waiver system all come from config. The user's league uses waiver
   *priority*, not a bidding budget; the UI must render whichever applies and
   never display a dollar figure unless the league actually uses one.
6. **Each screen opens with a plain "how to use this" line.** One sentence
   stating the action to take.
7. **Notifications are self-sufficient.** The recommended fix appears in the
   message body. The user must be able to act from a phone without opening
   anything, because the local page is served on localhost and unreachable from
   a phone.

## Interface

### Local page

A static HTML page in the repo, viewed through VS Code Live Server. Page and data
are separate: `ffcoach refresh` rewrites `web/data/*.json`, and the user reloads
the browser. No build step, no framework, no restart.

Live Server is required rather than opening the file directly because `file://`
blocks `fetch()` of local JSON under CORS.

Two views:

- **Draft board** — one ranked list in overall value order, tier breaks across
  it, position filters, and columns for rank, ADP, value, and availability at
  next pick. **Value** is `ADP − our rank`: positive means he is lasting later
  than the consensus expects, which is the signal worth acting on.
- **Weekly dashboard** — attention list on the left ordered by severity, current
  lineup on the right with problem slots highlighted, suggested pickups, and a
  preview of the notification text.

Both views carry the **explain-mode toggle** described in the UX requirements.
Off by default; state persisted in `localStorage`.

**The draft board recomputes live.** The user marks players off as they are
drafted, and availability, tier counts, and the recommended pick update
immediately. This depends on browser state that Python cannot precompute, so
this logic lives in JavaScript and is unit-tested there. Marked players persist
in `localStorage` so an accidental refresh mid-draft does not lose the board.

`ffcoach report --standalone` inlines the JSON into a single self-contained HTML
file that opens over `file://` and can be AirDropped to a phone.

### Notifications

`Notifier` is an interface; the channel is a config value. Implementations:
email-to-SMS gateway and ntfy first (both free), Pushover ($5 once) as an escape
hatch if free delivery proves unreliable. Pushover supports iOS Critical Alerts,
which bypass Do Not Disturb — relevant for a 90-minutes-to-kickoff warning.

Email carries the full weekly report; push carries short, urgent, actionable
text.

Scheduling runs through Claude Code scheduled agents, with a plain local cron
invoking the CLI as a fallback. Alerts fire only when something needs attention.

## Phasing

| Phase | Delivers | Depends on | Target |
|---|---|---|---|
| **1** | Draft strategy — tiers, targets, round plan, draft board page | FFC ADP, Sleeper players, config | Before the draft |
| **2** | Lineup + waiver advisors, dashboard, notifications | Manual adapter, projections | Before Week 1 |
| **3** | Trade evaluation, season strategy | Full league rosters | In-season |
| **4** | Platform scraper — removes manual roster entry | Platform resolved | Whenever |

Phase 1 is deliberately first: it is the most time-constrained, it depends on
neither the platform adapter nor weekly projections, and it forces the data layer
and config system to be built anyway.

Each phase ships something usable on its own.

**The implementation plan that follows this spec covers Phase 1 only.** Later
phases get their own plans once Phase 1 is working and the league is confirmed.

Phase 1 scope: config system, SQLite cache, the FFC and Sleeper sources plus
their join, the tier and value models, the draft advisor, the JSON report
writer, the CLI, and the draft board page with explain mode and live recompute.

Explicitly **not** in Phase 1: notifications, the roster adapter, weekly
projections, and `model/scoring.py`. Scoring converts stat lines into fantasy
points, and Phase 1 has no stat lines — it ranks on ADP, which the source
already returns per scoring format. The scoring model arrives with projections
in Phase 2.

## Testing

**Every module ships with tests from the first task.** There is no untested
layer, including the browser code.

### Toolchain

- **Python 3.12**, pinned through `uv`. The system Python is 3.7 and is not
  used.
- **pytest** for the Python side.
- **`node --test`**, Node's built-in runner, for the browser side. No npm
  packages are installed and none are shipped to the browser; Node exists purely
  to execute tests.

### Python

- `model/` — unit tests over fixed fixtures. Scoring, tiers, and replacement
  value are pure functions with known inputs and known outputs.
- `sources/` — recorded HTTP fixtures committed to the repo. No live network in
  tests, so the suite is deterministic and works offline.
- `leagues/` — the `manual` adapter is tested against sample YAML; contract tests
  run against every adapter implementation so scrapers added later must satisfy
  the same interface.
- `advisors/` — given fixture roster and player data, assert the expected
  findings appear. Bye weeks, injuries, and out-projected starters are each a
  case.
- `report/` — assert the emitted JSON matches the documented schema, so the
  browser's contract is enforced on the Python side.
- `notify/` — a fake notifier asserts message content and that alerts fire only
  when findings exist.

### JavaScript

`web/` is split so that logic is testable and DOM wiring is trivial:

- `render.js` — pure functions, exported as ES modules. Row rendering, filtering,
  sorting, tier banding, explain-mode annotation, live availability recompute.
  No DOM access.
- `main.js` — thin DOM wiring and event listeners. Imports `render.js`.
- `render.test.js` — `node --test` against `render.js`.

The rule: **if it computes, it lives in `render.js` and has a test; if it touches
the DOM, it lives in `main.js` and stays trivial enough to read.**

## Error handling

- A failed source serves stale cache and marks the data as stale in `meta.json`,
  surfaced in the page header. It does not crash the run.
- A failed source with no cached data produces a finding of its own, so a silent
  data outage becomes a visible problem rather than absent recommendations.
- Roster data that does not satisfy league roster rules produces a loud
  validation error rather than partial analysis.

## Open questions

- **Which platform hosts the league.** Deliberately deferred; the manual adapter
  makes it non-blocking. Revisit before Phase 4.
- **League settings.** Scoring, roster slots, and team count are unknown until
  the league is confirmed. Config file with commented defaults; the user fills it
  in. Phase 1 cannot produce accurate rankings until scoring is known, since PPR
  and standard scoring rank players differently.
- **Carrier**, needed if the email-to-SMS gateway channel is chosen.
