# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is for

**In-season alerting that prevents missed points.** One ESPN league, one user. The
value is: a starter is on bye, is OUT, or a slot is empty — and you find out while you
can still fix it.

**The draft board is legacy scaffolding, not the product.** `web/index.html`,
`advisors/draft.py`, `model/value.py`, `model/tiers.py` and `sources/ffcalc.py` were
built while the league invite was outstanding, because they were the only thing
buildable without a league. On 2026-09-03 the user said, unprompted: *"I do not need
this application to help me with the draft in any way."* That code stays (deleting it
is a third of the test suite) but it earns no new features, and **"Phase 1 complete"
in the planning docs does not mean the valuable half is done** — as of 2026-09-03
`advisors/lineup.py` is 543 tested lines with no production caller at all.

If you are picking up work here, the critical path is `ffcoach check` → a notifier →
the Week page. See `ROADMAP.md` §1, D-050, and R-4.

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
uv run ffcoach notify --init     # write notify.yaml with a fresh, unguessable topic
uv run ffcoach notify --test     # prove alerts reach your phone before relying on them
uv run ffcoach check             # this week's lineup: what to fix, by when
uv run ffcoach check --notify    # ...and send it
uv run ffcoach check --notify --dry-run   # ...and print what it would have sent
uv run ffcoach check --notify --ignore-quiet-hours   # ...even at 3am
uv run ffcoach check --fixture tests/fixtures/espn_league.json \
      --my-swid '{ABCDEF12-3456-7890-ABCD-EF1234567890}' --season 2025 \
      --now 2025-10-01T09:00-04:00        # the whole decision, offline
uv run ffcoach build             # fetch data -> web/data/board.json
uv run ffcoach league            # ESPN league/rosters -> web/data/league.json
uv run ffcoach league --fixture tests/fixtures/espn_league.json   # no ESPN access needed
uv run ffcoach refresh           # populate the cache only
uv run ffcoach doctor            # config, cache, alert channel, last run
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
- a **`fetch_*` / `parse_*` split**: `fetch_*` does I/O and returns a `SourceResult`;
  `parse_*` is pure, text in, typed objects out, and raises the module's exception with
  "parse" in the message on malformed input (tests match on that word)
- injectable `cache` and `client: httpx.Client | None = None`, with the `owns_client`
  ownership dance and **stale-cache fallback on failure** — a failed fetch on a Sunday
  morning serves old data rather than crashing

Two properties of that template are load-bearing and were both absent until 2026-08-31:

- **`fetch_*` returns `SourceResult`, never bare text** (`sources/base.py`). It carries
  `age_seconds`, `stale`, and the fetch error. Bare text made a live fetch and a week-old
  cache indistinguishable, and both report paths then hardcoded `stale_seconds=None` — so
  stale data was published with a current timestamp and `stale: false`. `freshest()` folds
  several sources into one page-level age by taking the **oldest**, because a page is as
  old as its oldest input — except a **lookup** passed as `lookups=`, which is exempt from
  the age and not from the staleness. A lookup is a join table: nothing on the page comes
  from it, it only resolves ids. The crosswalk's TTL is seven days and ADP's is six hours,
  so folding them by age made a board whose every number was minutes old announce
  "data 6d old", four days before a draft. A false alarm is how a reader learns to ignore
  the banner. Past its TTL a lookup still flips `stale`, because a wrong bind shows up on
  the page as the wrong player's bye week.
- **`fetch_*` parses before it caches.** A 200 is not proof of a usable body: an ESPN
  session-expiry page, a captive portal, and a truncated CSV all arrive with a good status
  code. Caching the raw body first destroyed the last known-good copy at exactly the moment
  it was needed. On an unparseable 200 the source falls back to cache like any other
  failure. `stale_fallback()` in `sources/base.py` is the shared implementation.

`Cache` also takes an injectable clock (`now: Callable[[], float]`), which is how TTL
expiry and staleness are tested without sleeping. `get_with_age()` is what sources use:
`get()` answers "may I use this", `get_with_age()` answers "may I use this, and how old
is it".

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

**The recurring way it gets violated is a plausible default**, not an omission. Three
found so far, all of which produced a clean-looking run and an unguarded lineup:

- An unknown ESPN `lineupSlotId` defaulted to `"BN"`, so a starter whose slot id ESPN
  renamed was skipped by every check.
- An unknown `proTeamId` defaulted to `"FA"`, which matches no schedule row, so the player
  looked like someone with nothing to worry about.
- A schedule row with a blank kickoff time was dropped, after which "this team has no game
  row" meant **bye** — a data-quality gap emitted as the single most certain fact the
  product makes, at interrupt priority.

The rule that came out of it: **an unusable value becomes `UNKNOWN` plus a diagnostic, and
a diagnostic must reach somewhere a human looks** — `League.diagnostics` travels into the
payload and onto the page, not just to the stderr of a run nobody watched. Absence is not
evidence; only a positive signal is. `Schedule.status()` returns `playing` / `bye` /
`unknown` for this reason, and a bye additionally requires being the team's *single*
missing week, so a truncated feed cannot manufacture byes.

### An all-clear must be earned, not inferred from silence

`check.py` composes the whole safety decision — `ffcoach check` is the only thing that
runs the detection Stage C built. Its central type is `CheckResult`, and the property
worth understanding is `all_clear`, which requires **no findings *and* no blind spots**.

A check that finds nothing is not a check that found nothing wrong. Without ESPN's
`lineupSlotCounts` the empty-slot check never runs, and an empty starting slot produces
exactly the same empty list as a healthy roster. A week-old cached roster, a derived
week, and an unrecognized slot id fail the same way. `blind_spots` records each, so the
statuses are:

```
problems    findings you can still act on        -> interrupt
pre_draft   the roster does not exist yet        -> nothing to check
unverified  nothing found, but we were partly blind -> say so, do not reassure
all_clear   nothing found, and we looked everywhere -> silence is honest
```

This is the `UNKNOWN`-plus-diagnostic rule applied one level up: to the run, not the
field. `pre_draft` was not designed — the first live run, four days before the real
draft, emitted **nine** "claim someone by Friday" findings for a roster the draft would
fill on Monday. It reads ESPN's `draftDetail.drafted` and tests `is False`, never
truthiness: an absent field is `None`, and treating absence as "not drafted" would mute
every alert for a season the first time ESPN renamed it.

Exit codes, because the check runs unattended long before anyone reads its output:
`0` all clear · `1` could not run · `2` still actionable · `3` not a clean look.
`--now` refuses a naive instant rather than reading it as UTC and moving every deadline.

### Delivery: silence is the common case, and it has to be deliberate

`notify/` is three small files: `base.py` (the `Notification` + `Notifier`
interface), `message.py` (pure — `CheckResult` in, `Notification` or `None` out),
and `ntfy.py` (the one channel, plus `ConsoleNotifier` for `--dry-run`).

`Notification` carries a **tier** — `interrupt` or `digest` — never a raw priority
number, because every service scales urgency differently (ntfy 1–5, Pushover −2..2).
Mapping a tier onto a service's scale is the channel's job; deciding what deserves to
buzz a phone during dinner is not. There are deliberately only two tiers: a third is a
slider nobody calibrates, and the interrupt tier is only worth anything while it stays
rare.

**What is never sent**, each for its own reason:

- a clean week — zero interrupts is the system working (D-016)
- `pre_draft` — there is no roster yet
- locked findings — reported on screen (D-011), useless on a phone
- **blind spots alone** (D-057) — a stale ESPN fetch persists across every run of a
  day, and until D3's repeat policy exists that is a spam machine. They ride *inside*
  a message that was going out anyway

`--dry-run` returns a real `ConsoleNotifier` rather than setting a flag the caller
branches on, so the dry run walks the same path as a live send and cannot drift from
it. It still loads and validates the config: a dry run that skipped validation would
happily "succeed" against a broken topic.

**Setup is a command, not a ritual.** `ffcoach notify --init` generates the topic with
`secrets` and writes `notify.yaml` at mode 600. The topic is generated rather than asked
for: left to a human it becomes "ffcoach" or a name plus a surname, and a public ntfy
topic has no authentication. `--init` refuses to clobber an existing file, because
overwriting changes the topic out from under a phone that is already subscribed —
alerts would go on being "delivered" to a topic nobody is listening to, which is the
worst failure this particular file has. A test asserts the template it writes is one the
loader accepts, so the two cannot drift.

**The ntfy topic name is the credential.** A public topic has no authentication at
all — whoever knows the name can read your alerts and publish to them. So `notify.yaml`
is gitignored, obvious names are refused at load, `doctor` reports that a channel is
configured and never which topic, and `DeliveryError` messages omit it because an error
string is the thing most likely to get pasted into an issue.

One trap already paid for: ntfy is published as **JSON to the server root**, not as
`{server}/{topic}` with a `Title:` header. HTTP headers are ASCII, and every title this
tool generates contains an em dash, so the header form raises `UnicodeEncodeError`
before anything is sent. A test caught it; the first alert of the season would have
otherwise.

### The dead-man's switch has two halves, and only one of them can work alone

D-023's case is exact: **expired ESPN cookies produce no alert, which is
indistinguishable from "nothing is wrong."** Every silent failure has that shape — a
check that errors sends nothing, and sending nothing is what a clean week looks like. The
better this product gets at staying quiet, the more dangerous its silence becomes.

**On-host** (`watchdog.py`, pure, always active). Reads the run log after the line is
written — this run is part of what it must see — and trips on either signal:

- **three failed runs in a row.** Unambiguous, and needs no assumption about the
  schedule. This is the cookie case.
- **no *successful* run within `max_silence_hours`.** Catches what failures cannot: a
  scheduler that was never loaded, or was unloaded, logs nothing at all, so there are no
  failures to count. Measured from the last **success**, never the last run — a machine
  erroring every fifteen minutes since Thursday is not alive.

Escalating keys (`watchdog:failing:2`) mean one alert per severity step, so a long outage
is re-raised as it worsens without being repeated on every scheduler cycle. `_watch` runs
in a `finally` and swallows its own exceptions: it must never replace the real failure
with a confusing one.

**Off-host** (`notify/heartbeat.py`, optional). Nothing above survives its own host
dying: a process on a dead machine reports nothing about the machine being dead. The only
construction that does is one where **absence is the signal** — ffcoach GETs a URL after
every successful run and an external service alerts when the pings stop. Deliberately a
bare URL, not an integration: healthchecks.io, Cronitor, Better Stack and Uptime Kuma all
accept "GET this to say I am alive". `fail_url` is separate and **never** guessed by
appending `/fail`, which is one vendor's convention and silently wrong for the others.

The heartbeat fires regardless of `--notify`: it is monitoring, not an alert, and
suppressing it on a non-notifying run would fake a dead machine. When it is unconfigured
`doctor` says so as an **exposure** — "if this machine dies, nothing will tell you" —
because silence about missing monitoring reads as coverage. Ping URLs are credentials
(a forged heartbeat makes a dead machine look alive) so they are redacted from the run
log alongside the ntfy topic and the ESPN cookies.

### Every run leaves a line

`runlog.py` appends one JSON object per `ffcoach check` (D-041: JSONL, because the
first reader is a person with `grep` at 9am on a Sunday and the second is a UI history
view). Nothing recorded anything before this, which made a quiet Sunday morning
indistinguishable between "your lineup is clean" and "the cookies expired at 6am and
every run since has errored" — the product's main failure mode once a scheduler runs it
unattended, and the reason **E3 could not be built**: a dead-man's switch is the question
*when did a run last succeed?*, and that had no answer.

Three properties are load-bearing:

- **The logging wraps the run in a `finally`**, not appended at the end. The runs worth
  diagnosing are the ones that crash; a check that raised and left no trace is exactly
  the silence E3 must be able to tell apart from a clean week. `_run_check` is a thin
  wrapper; `_check_body` holds the logic.
- **Secrets never reach it.** The ntfy topic is a credential and the ESPN cookies
  authenticate as the user, and a log is what gets pasted into an issue. `RunLog` scrubs
  its `secrets` from every string at any depth; empty and `None` are dropped, since
  scrubbing `""` would replace every gap between characters.
- **A logging failure never takes down the check.** A full disk must not cost you the
  alert: write errors warn on stderr and the run continues.

`doctor` prints the last run **and**, when it failed, the last one that succeeded. Both
deliberately: a recent *run* proves the scheduler is alive, a recent *success* proves it
would have told you something. Reporting only the first is how a machine erroring every
fifteen minutes since Thursday reads as healthy. A corrupt half-written line is skipped
rather than allowed to blind every reader.

### Repeats: two strikes, and the second one is spent late

`notify/policy.py` is pure and answers the question detection cannot: the same finding
appears on **every** run until it is fixed, and a scheduler runs the check many times an
hour. Without it, "alert on actionable findings" means "alert every fifteen minutes
until Sunday".

**Quiet hours defer, they never drop** (D-018). Nothing is queued — the problem is still
on the roster, so the next run after 08:00 finds it again. That is D-019's "the roster is
the acknowledgment" applied to deferral. The exception: **quiet hours yield to a deadline
that falls inside them.** Holding past the last moment something could be acted on
produces silence indistinguishable from a clean week.

**Two strikes, then nothing** (D-019). The exception is *when* strike two is spent —
inside a three-hour last-call window before the deadline, not on the next run. Two
constants guard it, and the second was found by a test rather than by reasoning:

- `LAST_CALL` (3h) — the reminder waits until it is useful.
- `MIN_GAP` (45m) — **and waits for air after strike one.** Without this, a problem
  first seen *inside* the last-call window burns both strikes in one scheduler cycle
  and then goes quiet for the three hours that mattered.

Three ordering rules that are load-bearing:

- **Decide, send, then record.** Recording first spends a strike on a message that never
  arrived, and strike two is the one that lands ninety minutes before kickoff. A failed
  delivery records nothing, so the next run retries.
- **A dry run records nothing.** It delivered nothing, so it must not count as having
  told you.
- **`AlertHistory` takes the check's clock, not the wall clock.** With `--now` they
  differ, and every "how long since the last alert" comparison is then between a
  simulated instant and a real one — wrong everywhere the flag is used, invisible in
  production where the two agree.

History lives in the same SQLite file as the cache (D-041) in its own `alerts` table,
**not** via `Cache`: a TTL store's whole contract is that entries expire, and an expired
alert record hands a fixed problem a fresh pair of strikes.

Every held alert prints its reason. A suppressed alert is a decision, and a decision
nobody can see is a bug report waiting to happen.

### Deadlines: the kind of fix comes before the time

`model/deadlines.py` returns a `FixPlan` (`BENCH_SWAP` / `WAIVER_CLAIM` /
`ADD_BEFORE_LOCK` / `UNKNOWN`), each with a one-word verb, **not** a bare
`(deadline, needs_waiver)` pair. The pair could describe an impossible transaction as a
plausible one: with no bench option and waivers processing after the lock, clamping the
deadline to the lock yields "claim someone by Thursday 8:15" for a claim that cannot
process until Friday. A time alone cannot express "a claim is the wrong instrument". There
is deliberately no `FREE_AGENT_ADD` kind — nothing fetches the free-agent pool, and a kind
that can never be emitted is a promise the code does not keep.

Relatedly: **a finding with no kickoff is not a finding that never locks.** Bye and
empty-slot findings are bounded by the week's *last* kickoff, after which no addition can
score. `actionable(findings, now)` checks the deadline, not only the `locked` flag.

### Replacements are allocated across the roster, not per slot

`find_replacements()` answers one slot's question well and every slot's question badly:
run per finding it has no memory, so two OUT receivers and one healthy bench WR produced
two cards each naming him — individually true, jointly impossible.
`advisors/roster_plan.py` allocates once across all openings, most-constrained-first, so
a dedicated RB slot is served before FLEX. IR is excluded from direct swaps (ESPN will not
start a player out of an IR slot) and reported as `ir_candidates`, a prerequisite action.

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
   or flags — see `advisors/draft.py::_reason`. Each clause must trace to something
   *computed*: the board carries no bargain/reach verdict, because `rank` is the ADP sort
   order, so `adp - rank` graded ADP against itself and drifted with list depth (a DEF at
   ADP 196 on row 271 read "reach"). Grading market price needs an independent ranking,
   and there is no projection model. `availability` — a normal CDF over FFC's `stdev` —
   stays, because it is real.
5. **Status is never carried by colour alone.** The injury badge is a letter plus a
   `title`; `league_render.test.js` asserts both. A red dot is invisible to a screen reader
   and to roughly one man in twelve.

## Config

- `league.yaml` — league settings. Gitignored; copy from `league.example.yaml`.
- `notify.yaml` — where alerts go. Gitignored; copy from `notify.example.yaml`. The ntfy
  topic name is a credential: a public topic has no auth, so it must be long and random.
- `espn.yaml` — ESPN `espn_s2` / `SWID` session cookies. Gitignored; copy from
  `espn.example.yaml`. Kept **separate** from `league.yaml` so that file stays safe to share
  or screenshot. These cookies authenticate as the user; there is no documented expiry and
  no refresh endpoint, so `EspnAuthError` (401/403) is raised distinctly and deliberately
  does **not** fall back to stale cache.

Nothing about league format may be hardcoded — scoring, roster slots, team count, and
waiver system all come from config.

**The live league, read from ESPN on 2026-09-03** (league `1076479097`). Recorded here
because every fixture and every default should be checked against it, not against a
guess:

| | |
|---|---|
| Teams / scoring | 12 · full PPR (`scoringItems` statId 53 = 1.0), H2H points |
| Starters | QB 1 · RB 2 · WR 2 · TE 1 · FLEX 1 · K 1 · DEF 1 |
| Bench | BN 7 · **IR 1** (`config.py`'s `VALID_SLOTS` has no IR — nothing is drafted into it) |
| Waivers | Priority, **no budget**. Processes **six days a week at 11:00** — every day but Tuesday. 24h claim window |
| Lineup lock | `INDIVIDUAL_GAME` → per-player, at each player's kickoff |

`my_pick` in `league.yaml` fed only the legacy draft board, and ESPN cannot supply it
anyway: `draftSettings.orderType` is `DRAFT_START`, so the order is drawn when the draft
opens and the published `pickOrder` is the identity list `[1..12]`, a placeholder.

**One knowing exception**, recorded rather than hidden: `_SLOT_ELIGIBILITY` in
`advisors/lineup.py` hardcodes `FLEX = RB/WR/TE`, so superflex and IDP leagues would be
silently wrong. The slot *names* still come from ESPN, and an unrecognized slot falls
through to "only its own position fits" — conservative rather than fabricated. It is a
portability defect, not a live one, and it is the first thing to fix if this repo is ever
pointed at a second league.

## Testing

Every module ships with tests, including browser code. Sources are tested against committed
fixtures with a mocked `httpx.MockTransport`, so the suite is deterministic and offline.
See the `client_returning()` helper duplicated across source tests.

`tests/fixtures/espn_league.json` is **hand-built**, but as of 2026-09-03 the parser it
exercises is no longer unverified: `ffcoach league` ran against the real league and
returned 12 teams with **zero diagnostics**, so the field names guessed from community
docs match live ESPN. The fixture is still only two teams and still proves internal
consistency rather than fidelity — replacing it with a real cookie-scrubbed capture is
worth doing, and **`SWID` is both the owner id in `members[]` and half the auth pair**,
so any capture tool must scrub member ids, not just display names.

## Workflow

Feature branches with PRs into `main` — never a direct merge. CI (`.github/workflows/test.yml`)
runs both suites on every PR.

Design docs live in `docs/superpowers/specs/`; the spec records phasing and deliberately
deferred work (smack talk, per-alert notification toggles) with rationale.
