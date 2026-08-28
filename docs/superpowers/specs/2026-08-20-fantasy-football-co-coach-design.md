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

- **Platform: ESPN** (resolved 2026-08-28; was deliberately deferred at first
  because the league invite hadn't arrived). ESPN's fantasy API is
  unofficial and community reverse-engineered -- no docs, no API key.
  Private leagues (the common case) need the `espn_s2`/`SWID` session
  cookies pulled from a logged-in browser; there is no refresh endpoint, so
  an auth failure is surfaced as its own error rather than retried. See
  `src/ffcoach/leagues/espn_client.py` and `espn.example.yaml`.
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

### The league adapter

`LeagueAdapter` is a protocol (`fetch_league() -> League`) so that report
building and the UI never import a specific platform. `espn.py` /
`espn_client.py` is the first and, for now, only implementation. Its parser
was built and fully tested against a hand-built fixture matching ESPN's
documented (unofficial) JSON shape, before the league invite arrived --
`ffcoach league --fixture ...` demonstrates the whole page with zero ESPN
access. The fixture gets replaced with a real captured response, and the
parser re-verified, once the league is actually joined.

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
    base.py              internal model (League, Team, RosterEntry) + LeagueAdapter protocol
    espn.py              ESPN JSON -> internal model (pure; the one speculative module)
    espn_client.py        authenticated fetch, cache, EspnAuthError
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
  index.html  league.html      one page per view
  nav.js                       shared site nav, driven by one PAGES list
  render.js  league_render.js  pure functions — all logic, unit-tested
  main.js  league_main.js      thin DOM wiring only
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
| ESPN Fantasy API (unofficial, cookie auth) | League settings, teams, rosters | League/roster view, later lineup and waivers |
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

Three views, more expected over time (lineup, waivers, trades):

- **Draft board** — one ranked list in overall value order, tier breaks across
  it, position filters, and columns for rank, ADP, value, and availability at
  next pick. **Value** is `ADP − our rank`: positive means he is lasting later
  than the consensus expects, which is the signal worth acting on.
- **My League** — every team's record, points for/against, and roster (starters
  vs. bench/IR), sourced from the ESPN adapter. Your own team is pinned to the
  top and visually marked.
- **Weekly dashboard** — attention list on the left ordered by severity, current
  lineup on the right with problem slots highlighted, suggested pickups, and a
  preview of the notification text.

Every page shares a small nav bar (`web/nav.js`) driven by one `PAGES` list, so
adding a future section is one entry, not a per-page markup hunt.

The draft board carries the **explain-mode toggle** described in the UX
requirements (off by default, state persisted in `localStorage`); newer views
adopt the same annotation pattern as they gain content worth explaining. My
League is deliberately plain today -- team/roster facts, not judgment calls.

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
| **1** ✅ | Draft strategy — tiers, targets, round plan, draft board page | FFC ADP, Sleeper players, config | Before the draft |
| **1.5** ✅ | ESPN league adapter, internal league model, My League page (teams + rosters), shared site nav | Platform resolved (ESPN) | — |
| **1.6** | Validate the ESPN parser against a real league; replace the hand-built fixture; fill in `espn.yaml` | **League invite** | Whenever invited |
| **2** | Lineup + waiver advisors, dashboard, notifications with per-type on/off toggles, smack talk delivery | Real rosters, projections | Before Week 1 |
| **3** | Trade evaluation, season strategy | Full league rosters | In-season |

Phase 1 was deliberately first: it is the most time-constrained, it depends on
neither the league adapter nor weekly projections, and it forces the data layer
and config system to be built anyway. Phase 1.5 followed once the platform
question resolved, ahead of schedule relative to the original Phase 4 slot,
because it unblocks nothing else and stands alone.

Each phase ships something usable on its own.

Phase 1 scope: config system, SQLite cache, the FFC and Sleeper sources plus
their join, the tier and value models, the draft advisor, the JSON report
writer, the CLI, and the draft board page with explain mode and live recompute.

Phase 1.5 scope: `leagues/base.py` (internal model + `LeagueAdapter`
protocol), `leagues/espn_client.py` (cookie auth, cache, `EspnAuthError`),
`leagues/espn.py` (parser, tested only against a fixture until a real league
confirms it), `report/build.py::league_payload`, the `ffcoach league`
subcommand (with a `--fixture` escape hatch needing no ESPN access), and
`web/league.html` + `web/league_render.js`.

Explicitly deferred past Phase 1.5, recorded here rather than acted on yet:

- **Smack talk.** League-wide broadcast lines about the week's worst
  decisions and outcomes (never personal attributes) -- sharp but friendly,
  delivered via notification/email/web. Needs real rosters and completed
  weeks to have anything to talk about, so it waits for Phase 2.
- **Per-alert notification toggles.** The user wants independent on/off
  switches for at least: injury alerts, bye-week-in-lineup, bench-upgrade
  suggestions, trade offers, and smack talk. Agreed shape:

  ```yaml
  notifications:
    channels:
      push: ntfy          # or pushover
      email: <address>
    alerts:
      injury:         {enabled: true, channel: push,  urgency: high}
      bye_in_lineup:  {enabled: true, channel: push,  urgency: high}
      bench_upgrade:  {enabled: true, channel: push,  urgency: normal}
      trade_offer:    {enabled: true, channel: email, urgency: low}
      smack_talk:     {enabled: true, channel: email, urgency: low}
      espn_auth:      {enabled: true, channel: push,  urgency: high}
  ```

  `espn_auth` fires on `EspnAuthError` -- ESPN cookies break unpredictably
  with no documented lifetime, so that exception is defined now as the future
  hook, even though nothing consumes it yet. Building the toggle schema
  itself waits until there's a notifier to wire it into.

Explicitly not yet built at all: weekly projections, and `model/scoring.py`.
Scoring converts stat lines into fantasy points, and nothing built so far has
stat lines to convert — Phase 1 ranks on ADP (which the source already
returns per scoring format), and Phase 1.5 shows rosters, not scores. The
scoring model arrives with projections in Phase 2. It may also need
`LeagueConfig.scoring`'s coarse `standard`/`half-ppr`/`ppr` enum to grow into
a real per-stat table, if the league turns out to use custom scoring —
deferred until real ESPN settings JSON is in hand rather than guessed at now.

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
- `leagues/` — `base.py` is tested directly (record formatting, starter/bench
  classification, protocol conformance). `espn.py` is tested against a
  hand-built fixture matching ESPN's documented shape, marked in the fixture
  itself as unverified against a live league until Phase 1.6 confirms it.
  `espn_client.py` is tested with a mocked HTTP transport, same pattern as
  `sources/ffcalc.py` and `sources/sleeper.py`.
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

- **League settings.** Scoring, roster slots, and team count are still
  placeholder defaults in `league.yaml` until the league is confirmed and the
  user is invited. Once invited, ESPN's `mSettings` view (already fetched by
  `leagues/espn_client.py`) may be able to populate these automatically,
  rather than the user retyping a points breakdown -- worth revisiting in
  Phase 1.6 alongside the fixture-vs-live parser verification.
- **Carrier**, needed if the email-to-SMS gateway channel is chosen.
