# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**How to read this file.** It carries invariants, traps, and commands — what changes what you do
*this turn*. The reasoning behind each one lives in `ROADMAP.md` §6 as a numbered decision; a
`D-NNN` reference means "go read that before arguing with this." Do not copy rationale back
into this file: it is loaded into every session, and the decision log is not.

## What this project is for

**In-season alerting that prevents missed points.** One ESPN league, one user. A starter is on
bye, is OUT, or a slot is empty — and you find out while you can still fix it.

**The draft board is legacy scaffolding, not the product** (D-050). `web/draft.html`,
`advisors/draft.py`, `model/value.py`, `model/tiers.py`, `sources/ffcalc.py`. It stays — deleting
it is a third of the test suite — but it earns no new features. "Phase 1 complete" in the older
planning docs does not mean the valuable half is done.

## Commands

```bash
uv sync                          # install; Python 3.12 is pinned via .python-version
uv run pytest                    # full Python suite (offline, no network)
uv run pytest tests/test_match.py::test_enrich_attaches_crosswalk_ids -v   # single test
npm test                         # browser logic; installs no npm packages
```

`npm test` runs `node --test web/*.test.js`. **The glob matters**: `node --test web/` fails on
Node 26, which treats a bare path as a module entry point rather than a directory to scan.

```bash
uv run ffcoach notify --init     # write notify.yaml with a fresh, unguessable topic
uv run ffcoach notify --test     # prove alerts reach your phone before relying on them
uv run ffcoach check             # this week's lineup: what to fix, by when
uv run ffcoach check --notify    # ...and send it
uv run ffcoach check --notify --dry-run            # ...and print what it would have sent
uv run ffcoach check --notify --ignore-quiet-hours # ...even at 3am
uv run ffcoach check --fixture tests/fixtures/espn_league.json \
      --my-swid '{ABCDEF12-3456-7890-ABCD-EF1234567890}' --season 2025 \
      --now 2025-10-01T09:00-04:00        # the whole decision, offline
uv run ffcoach build             # fetch data -> web/data/board.json
uv run ffcoach league            # ESPN league/rosters -> web/data/league.json
uv run ffcoach league --fixture tests/fixtures/espn_league.json   # no ESPN access needed
uv run ffcoach refresh           # populate the cache only
uv run ffcoach init              # create the config files, list what is still missing
uv run ffcoach doctor            # config, cache, alert channel + prefs, last run, setup left
uv run ffcoach serve             # pages at http://127.0.0.1:8765/ (incl. /alerts.html, /health.html)
uv run ffcoach serve --lan       # ...reachable from other devices (opt-in)
uv run ffcoach schedule --print  # the launchd plist, without installing it
uv run ffcoach schedule --install   # ...and load it
uv run ffcoach schedule --status    # loaded? and has it actually run?
```

Exit codes: `0` all clear · `1` could not run · `2` still actionable · `3` not a clean look.

View pages with `uv run ffcoach serve` (or any static server) — **not** by opening the file.
`file://` blocks the `fetch()` of local JSON under CORS.

## Architecture

### The dividing rule

Deterministic Python core; Claude as the coach. **If it is the same every time it is a script;
if it needs judgment it is the skill** (D-001). Advisors emit structured findings, never prose —
a Claude Code skill (not yet built) reads the CLI's JSON and turns findings into coaching. This
also controls token cost: scripts fetch and cache megabytes, the skill receives a compact summary.

### Pipeline

```
sources/ -> cache (SQLite) -> model/ -> advisors/ -> report/ -> web/data/*.json -> web/
```

`model/` is pure: no network, no filesystem, no clock. That is the layer that must never be wrong,
so it has no moving parts.

### Every source module follows one template

`sources/ffcalc.py` is canonical; `sleeper.py`, `crosswalk.py`, and `leagues/espn_client.py` copy
it. New sources must too:

- `*_URL`, `TTL_SECONDS`, and either `CACHE_KEY` or a `_cache_key()` function when parameterized
- a module-specific `*Unavailable(Exception)`
- a **`fetch_*` / `parse_*` split**: `fetch_*` does I/O and returns a `SourceResult`; `parse_*` is
  pure, text in, typed objects out, and raises the module's exception with **"parse"** in the
  message on malformed input (tests match on that word)
- injectable `cache` and `client: httpx.Client | None = None`, the `owns_client` ownership dance,
  and **stale-cache fallback on failure** — a failed fetch on a Sunday morning serves old data
  rather than crashing

Four invariants, each of which was once violated and produced a clean-looking wrong answer:

- **`fetch_*` returns `SourceResult`, never bare text** (`sources/base.py`). It carries
  `age_seconds`, `stale`, and the fetch error. → D-044
- **`freshest()` folds sources by taking the oldest — except a `lookups=` argument**, which is
  exempt from the *age* but not the *staleness*. A lookup is a join table: nothing on the page
  comes from it, it only resolves ids. → D-053
- **The cache key encodes the request, not just the resource** — `espn_client._cache_key` includes
  the sorted view list. → D-069
- **`fetch_*` parses before it caches.** A 200 is not proof of a usable body: a session-expiry
  page, a captive portal, and a truncated CSV all arrive with a good status code. On an
  unparseable 200 the source falls back to cache like any other failure; `stale_fallback()` in
  `sources/base.py` is the shared implementation. → D-044

`Cache` takes an injectable clock (`now: Callable[[], float]`), which is how TTL expiry and
staleness are tested without sleeping. `get()` answers "may I use this"; `get_with_age()` answers
"may I use this, and how old is it" — sources use the latter.

### Player identity is resolved before matching

`sources/crosswalk.py` (DynastyProcess) maps one player across MFL / Sleeper / ESPN / GSIS /
FantasyPros / PFR / CBS at once, so identity resolves **once, by ID** (D-008). Name matching has
already failed here twice — accented characters, and nicknames.

Non-obvious properties of that data, all verified against live rows:

- Missing values are the literal string `"NA"`, not empty cells. Every ID column reads "100%
  populated" until you account for it; real coverage is 52–65%.
- `merge_name` is a **curated alias**, not a lowercased `name`: "Andres Borregales" carries
  "andy borregales". Both fields are indexed, and it is the only reason nickname-using sources
  resolve.
- Ambiguity breaks by preferring a modern platform ID, then team — that is what separates Marvin
  Harrison Jr. from his father, since `normalize_name` strips the "Jr." suffix.
- **Team defenses are absent from the crosswalk entirely.** They match by name only and always
  report `unresolved`. Structural, not a bug.

`enrich()` returns an `EnrichResult` (players / unmatched / **fuzzy**). Surname-only matches are
reported as fuzzy rather than applied silently.

### Nothing is dropped or guessed silently

A failed source serves stale cache and marks the payload stale. Unmatched players are reported,
never omitted. When identity is ambiguous, `resolve()` returns `unresolved` rather than picking.

**The recurring way this gets violated is a plausible default**, not an omission (D-047). Four
found so far, each producing a clean-looking run: an unknown `lineupSlotId` defaulting to `"BN"`;
an unknown `proTeamId` defaulting to `"FA"`; a blank kickoff time dropping the schedule row, after
which "no game row" read as **bye** (D-048); and team names read from ESPN's pre-2023
`nickname`/`location` pair (D-067).

The rule: **an unusable value becomes `UNKNOWN` plus a diagnostic, and a diagnostic must reach
somewhere a human looks.** `League.diagnostics` travels into the payload and onto the page, not
just to the stderr of a run nobody watched. Absence is not evidence; only a positive signal is.
`Schedule.status()` returns `playing` / `bye` / `unknown` for this reason, and a bye additionally
requires being the team's *single* missing week.

### An all-clear must be earned, not inferred from silence

`check.py` composes the whole safety decision — `ffcoach check` is the only thing that runs the
detection Stage C built. `CheckResult.all_clear` requires **no findings *and* no blind spots**
(D-054), because a check that finds nothing is not a check that found nothing wrong. Without
`lineupSlotCounts` the empty-slot check never runs and an empty slot looks exactly like a healthy
roster. `blind_spots` records each, giving four statuses:

```
problems    findings you can still act on            -> interrupt
pre_draft   the roster does not exist yet            -> nothing to check
unverified  nothing found, but we were partly blind  -> say so, do not reassure
all_clear   nothing found, and we looked everywhere  -> silence is honest
```

`pre_draft` reads ESPN's `draftDetail.drafted` and tests **`is False`**, never truthiness: an
absent field is `None`, and treating absence as "not drafted" would mute every alert for a season
the first time ESPN renamed it (D-055). `--now` refuses a naive instant rather than reading it as
UTC and moving every deadline.

### Delivery: silence is the common case, and it has to be deliberate

`notify/` is `base.py` (the `Notification` + `Notifier` interface), `message.py` (pure —
`CheckResult` in, `Notification` or `None` out), and `ntfy.py` (the one channel, plus
`ConsoleNotifier` for `--dry-run`).

`Notification` carries a **tier** — `interrupt` or `digest` — never a raw priority number, because
every service scales urgency differently (ntfy 1–5, Pushover −2..2). There are deliberately only
two: a third is a slider nobody calibrates, and the interrupt tier is only worth anything while it
stays rare. → D-016

**What is never sent**, each for its own reason:

- a clean week — zero interrupts is the system working (D-016)
- `pre_draft` — there is no roster yet
- locked findings — reported on screen (D-011), useless on a phone
- **blind spots alone** (D-057) — a stale ESPN fetch persists across every run of a day; they ride
  *inside* a message that was going out anyway

`--dry-run` returns a real `ConsoleNotifier` rather than setting a flag the caller branches on, so
the dry run walks the same path as a live send. It still loads and validates the config.

**Setup is a command, not a ritual.** `ffcoach notify --init` generates the topic with `secrets`
and writes `notify.yaml` at mode 600. Generated rather than asked for: left to a human it becomes
"ffcoach". `--init` **refuses to clobber** an existing file — overwriting changes the topic out
from under a phone that is already subscribed. A test asserts the template it writes is one the
loader accepts.

**The ntfy topic name is the credential** (D-058). A public topic has no authentication: whoever
knows the name can read your alerts and publish to them. So `notify.yaml` is gitignored, obvious
names are refused at load, `doctor` reports *that* a channel is configured and never which, and
`DeliveryError` messages omit it.

One trap already paid for: ntfy is published as **JSON to the server root**, not as
`{server}/{topic}` with a `Title:` header. HTTP headers are ASCII and every title this tool
generates contains an em dash. → D-059

### What may reach you is a separate file, on purpose

`alerts.yaml` — per-kind switches, quiet hours, and a mute — is **not** part of `notify.yaml`, and
the split is structural rather than tidy. The Alerts page writes this file over HTTP; `notify.yaml`
holds the topic, which is the credential. Separate files mean the write endpoint has no field that
could redirect where alerts go. → D-077

- **It records what is switched *off*, never what is on.** A kind this build has not heard of still
  alerts. Same closed-list direction as `HEALTHY`: an unrecognized kind costs one message you did
  not need, not one you did.
- **A mute is an instant, never a flag.** Every preset on the page expires by itself.
- **An unreadable `alerts.yaml` refuses the run** rather than defaulting to alerting on everything.
- **`allowed_by_prefs` runs before `decide`**, or a switched-off kind spends a strike on its way to
  being suppressed.
- **A preference governs the phone, never the check.** A disabled kind still appears in
  `ffcoach check` and on the Week page (the D-011 precedent), and is **never** a blind spot — we
  looked, and we found it, so `all_clear` keeps meaning what D-054 says.
- **Silence you asked for is still reported.** `doctor` and the health panel name an active mute and
  any switched-off kinds, and the panel drops the Alerts row to *unknown* rather than a green tick.
  Without that, "I muted it and forgot" and "the cookies expired" look identical. → D-078
- **`POST /api/alerts` is refused while `--lan` is on**, derived from the bind address rather than a
  flag a caller can forget. Letting a network peer silence your alerts is a different order of bad
  from letting one spend an ESPN fetch.

There is deliberately **no per-kind tier and no threshold**: nothing produces a digest, and nothing
numeric reaches a finding until G4 exists. A knob with nothing behind it is D-014's mistake.

### Repeats: two strikes, and the second one is spent late

`notify/policy.py` is pure and answers what detection cannot: the same finding appears on **every**
run until it is fixed, and a scheduler runs many times an hour.

- **Quiet hours defer, they never drop** (D-018). Nothing is queued — the problem is still on the
  roster, so the next run after 08:00 finds it again. **Exception: quiet hours yield to a deadline
  that falls inside them.**
- **Two strikes, then nothing** (D-019). `LAST_CALL` (3h) — the reminder waits until it is useful.
  `MIN_GAP` (45m) — **and waits for air after strike one**, or a problem first seen inside the
  last-call window burns both strikes in one scheduler cycle. → D-060

Three ordering rules, all load-bearing (D-061):

- **Decide, send, then record.** Recording first spends a strike on a message that never arrived.
- **A dry run records nothing.**
- **`AlertHistory` takes the check's clock, not the wall clock.** With `--now` they differ, and
  every "how long since the last alert" comparison is then wrong everywhere the flag is used and
  invisible in production.

History lives in the same SQLite file as the cache (D-041) in its own `alerts` table, **not** via
`Cache`: a TTL store's contract is that entries expire, and an expired alert record hands a fixed
problem a fresh pair of strikes. Every held alert prints its reason.

### Deadlines: the kind of fix comes before the time

`model/deadlines.py` returns a `FixPlan` (`BENCH_SWAP` / `WAIVER_CLAIM` / `ADD_BEFORE_LOCK` /
`UNKNOWN`), each with a one-word verb, **not** a bare `(deadline, needs_waiver)` pair — which
could describe an impossible transaction as a plausible one ("claim someone by Thursday 8:15" for
a claim that cannot process until Friday). There is deliberately **no `FREE_AGENT_ADD`**: nothing
fetches the free-agent pool, and a kind that can never be emitted is a promise the code does not
keep. → D-014

**A finding with no kickoff is not a finding that never locks.** Bye and empty-slot findings are
bounded by the week's *last* kickoff. `actionable(findings, now)` checks the deadline, not only
the `locked` flag.

### Replacements are allocated across the roster, not per slot

`find_replacements()` answers one slot's question well and every slot's question badly: run per
finding it has no memory, so two OUT receivers and one healthy bench WR produced two cards each
naming him — individually true, jointly impossible. `advisors/roster_plan.py` allocates once
across all openings, most-constrained-first. → D-045

IR is excluded from direct swaps (ESPN will not start a player out of an IR slot) and reported as
`ir_candidates`, a prerequisite action. **A replacement whose own game has kicked off is not a
replacement** — `find_replacements`/`find_ir_candidates` take an optional `now`, optional because
`find_upcoming_byes` asks about *next* week. → D-076

### The inactives sweep is the one check that is a matter of timing

Every other finding is true all week. **QUESTIONABLE and DOUBTFUL are the exception** (D-010):
most Questionable players play, so benching one on Wednesday loses points more often than it saves
them — but ninety minutes before the slot locks, the inactives are out and the swap is still
legal. So `at_risk` is the only opening whose **existence** depends on `now`. → D-075

- **The window tracks the slot's lock, not the kickoff.** Under a weekly lock a Sunday starter
  froze on Thursday.
- **`RosterEntry.is_uncertain` treats an unrecognized status as doubt.** `HEALTHY` is a *closed*
  list, so a designation ESPN adds costs one wasted alert rather than dropping a starter out of
  the only check that runs while he is still swappable.
- **It reports even when the bench cannot cover it** — a claim cannot process in ninety minutes
  but a free agent can be added instantly, and `plan_fix` already says so.
- **It sorts above `bye`** despite being less certain, because its slot freezes sooner.

`assign_replacements` takes `priorities` (severity doubles as the value) as a tiebreak **after**
most-constrained-first, so a certain zero beats a maybe for the same bench player without a
one-option slot losing its only candidate.

### The scheduler: everything checkable is checked

`agent.py` builds the launchd plist and is pure; `cli.py` calls `launchctl`. R-2 says launchd
correctness is untestable in CI — true of the *loading*, not of the plist, which is a function of
two paths and an interval. A wrong plist is the worst outcome available: launchd will happily
"run" it and fail silently every interval forever.

**launchd, not cron** (D-022): cron skips a job it missed while the Mac was asleep. **A fixed
interval, not one derived from kickoffs** (D-064).

`build_agent` refuses more than it accepts, and every guard maps to a *silent* failure:

- **absolute paths only** — launchd has no shell, no PATH, no working directory
- **`league.yaml` / `espn.yaml` / `notify.yaml` must exist** — otherwise you are scheduling silence
- **interval clamped to 5–240 minutes** — below hammers an unofficial API; above cannot catch a
  Sunday inactives ruling before kickoff
- **no `KeepAlive`** — it restarts the job the moment it exits: an infinite loop against ESPN
- **`plistlib`, never a format string** — a directory named `Tom & Jerry` is ordinary

Install does `bootout` then `bootstrap`. `--status` reports **loaded** *and* **whether anything
has actually run** — R-2 is precisely the gap between those two facts.

### One machine alerts, and the other one says so

`host.py` answers "is this the machine that is supposed to be alerting?" Two machines alerting
sends everything twice (alert history is a local SQLite file). Worse: **a laptop that checks even
occasionally keeps the heartbeat green while the scheduler machine is face-down** — E3 defeated by
its own mechanism. → D-072

`scheduler_host` is **empty by default** (one machine is the common case); `schedule --install`
records the host automatically. A non-scheduler run **still checks and still writes the page**; it
only declines to send and to ping, and says so. Hostnames are normalised — macOS returns
`MacBook-Air.local` on one network and `MacBook-Air` on another.

### The dead-man's switch has two halves

**Expired ESPN cookies produce no alert, which is indistinguishable from "nothing is wrong."** The
better this product gets at staying quiet, the more dangerous its silence becomes. → D-023, D-063

**On-host** (`watchdog.py`, pure, always active). Reads the run log *after* the line is written and
trips on either signal: **three failed runs in a row** (the cookie case), or **no *successful* run
within `max_silence_hours`** — measured from the last success, never the last run, since a machine
erroring every fifteen minutes since Thursday is not alive. Escalating keys
(`watchdog:failing:2`) mean one alert per severity step. `_watch` runs in a `finally` and swallows
its own exceptions: it must never replace the real failure with a confusing one.

**Off-host** (`notify/heartbeat.py`, optional). A process on a dead machine reports nothing about
the machine being dead; the only construction that works is one where **absence is the signal**.
Deliberately a bare URL, not an integration. `fail_url` is separate and **never** guessed by
appending `/fail`, which is one vendor's convention. The heartbeat fires regardless of `--notify`
— it is monitoring, not an alert. When unconfigured, `doctor` reports it as an **exposure**. Ping
URLs are credentials and are redacted from the run log alongside the topic and the cookies.

### Every run leaves a line

`runlog.py` appends one JSON object per `ffcoach check` (D-041: JSONL, because the first reader is
a person with `grep` at 9am on a Sunday). Nothing recorded anything before this, which is why **E3
could not be built**: a dead-man's switch is the question *when did a run last succeed?* Three
properties are load-bearing (D-062):

- **The logging wraps the run in a `finally`**, not appended at the end — the runs worth
  diagnosing are the ones that crash. `_run_check` is a thin wrapper; `_check_body` holds the logic.
- **Secrets never reach it.** `RunLog` scrubs its `secrets` from every string at any depth; empty
  and `None` are dropped, since scrubbing `""` would replace every gap between characters.
- **A logging failure never takes down the check.** Write errors warn on stderr and the run
  continues.

`doctor` prints the last run **and**, when it failed, the last one that succeeded. A recent *run*
proves the scheduler is alive; a recent *success* proves it would have told you something. A
corrupt half-written line is skipped rather than allowed to blind every reader.

### The health panel is built per request, and unknown is not healthy

`GET /api/health` is composed **per request and never written to a file** — a panel served from a
snapshot would report "last run 3 minutes ago" out of a file written three hours ago. **Unknown is
its own state**: `agent_loaded` is `True`/`False`/`None`, and `None` renders as "could not be
determined" rather than a green tick. Any unknown drags the overall state below OK; any bad beats
any unknown. **No secret is ever in the payload** — only whether each is configured; a test
asserts the generated topic and ping URL are both absent. `POST /api/refresh` is **POST only** (a
GET with a side effect can be fired by an `<img>` tag) and rate-limited to one run per 30 seconds,
answering **429**. → D-074

### `ffcoach serve` is rooted at `web/`, and that is the point

`espn.yaml` and `notify.yaml` live in the **project root, one directory above the pages**. So
`web_root()` resolves and checks for `index.html` before a socket is opened, and **refuses rather
than falling back** — the plausible fallback is exactly the directory holding the credentials.
Five traversal shapes are tested against a real running server. → D-071

`.json` is served `Cache-Control: no-store`; HTML is not. `--lan` binds every interface and **says
what that means in the output**, not only in `--help`. Default is localhost.

### Setup is a checklist, and both commands read the same one

`_setup_steps()` returns `(done, what, how to fix it)` and is rendered by **both** `ffcoach init`
and `ffcoach doctor`, so "what is missing" and "how do I fix it" cannot drift apart. → D-073

### Browser layer

No framework, no build step, no npm packages shipped. The split is enforced: **if it computes, it
lives in `render.js` / `league_render.js` / `week.js` and has a test. If it touches the DOM, it
lives in `*_main.js` and stays trivial enough to read.**

**Team logos are deliberately not shown** (D-070) — so nobody adds them again. A league's *default*
logo is a public SVG, but a **user-uploaded** one lives on `mystique-api.fantasy.espn.com` and
returns **401** to a plain `<img>`: the browser will not send ESPN's cookies on a cross-site
subresource. So the teams who bothered to customise are exactly the ones whose image cannot load.
`abbrev` carries the same identity in text, for every team.

`web/nav.js` holds one `PAGES` list driving the nav on every page (D-007). A test asserts
**`index.html` is the Week page** — the front door was the draft board until 2026-09-04 (D-051).

`week.js` **re-derives nothing** (D-066). `actionable`, `verb`, `status` and `blind_spots` all
arrive from Python where they are tested. `blindSpotsHtml` renders **above** the findings, never
below.

## Binding UX rules (enforced by tests, not just convention)

1. **Standard terminology is never hidden or renamed.** The interface says "ADP", not "Typical
   pick". Terms are *annotated*, never replaced. `render.test.js` asserts ADP is never renamed
   away. → D-003
2. **Explain mode annotates only.** Turning it on never changes layout or ordering. → D-004
3. **No dollar figures.** The league uses waiver priority, not a bidding budget. Both
   `test_report.py` and `render.test.js` assert no `$` is ever emitted.
4. **Every recommendation states its reason inline**, in both modes. Each clause must trace to
   something *computed* — which is why the board carries no bargain/reach verdict (D-052:
   `rank` *is* the ADP sort order, so `adp - rank` graded ADP against itself). `availability`, a
   normal CDF over FFC's `stdev`, stays because it is real.
5. **Status is never carried by colour alone.** The injury badge is a letter plus a `title`;
   `league_render.test.js` asserts both.

## Config

- `league.yaml` — league settings. Gitignored; copy from `league.example.yaml`.
- `notify.yaml` — where alerts go. Gitignored; copy from `notify.example.yaml`. **The ntfy topic
  name is a credential** (D-058).
- `alerts.yaml` — *what* may reach you. Gitignored, holds **no credential** (that is the point of
  the split, D-077), written by the Alerts page, and **optional**: absent means the pre-D4
  defaults. No example file — `save_alert_prefs` generates its own comments.
- `espn.yaml` — ESPN `espn_s2` / `SWID` session cookies. Gitignored; copy from
  `espn.example.yaml`. Kept **separate** from `league.yaml` so that file stays safe to share or
  screenshot. These cookies authenticate as the user; there is no documented expiry and no refresh
  endpoint, so `EspnAuthError` (401/403) is raised distinctly and deliberately does **not** fall
  back to stale cache.

**Nothing about league format may be hardcoded** — scoring, roster slots, team count, waiver
system, **and the league's timezone** all come from config. ESPN publishes `waiverProcessHour` as a
bare integer with **no timezone field anywhere in the payload**, so an unknown zone is refused
rather than defaulted, and an unreadable config is recorded as a **blind spot**. → D-065

**The live league, read from ESPN on 2026-09-03** (league `1076479097`). Every fixture and default
should be checked against this, not against a guess:

| | |
|---|---|
| Teams / scoring | 12 · full PPR (`scoringItems` statId 53 = 1.0), H2H points |
| Starters | QB 1 · RB 2 · WR 2 · TE 1 · FLEX 1 · K 1 · DEF 1 |
| Bench | BN 7 · **IR 1** (`config.py`'s `VALID_SLOTS` has no IR — nothing is drafted into it) |
| Waivers | Priority, **no budget**. Processes **six days a week at 11:00** — every day but Tuesday. 24h claim window |
| Lineup lock | `INDIVIDUAL_GAME` → per-player, at each player's kickoff |
| Timezone | **Eastern**, confirmed by the user against ESPN's own UI on 2026-09-04 |

`my_pick` fed only the legacy draft board, and ESPN cannot supply it: `draftSettings.orderType` is
`DRAFT_START`, so the published `pickOrder` is the identity list `[1..12]`, a placeholder.

**One knowing exception**, recorded rather than hidden: `_SLOT_ELIGIBILITY` in
`advisors/lineup.py` hardcodes `FLEX = RB/WR/TE`, so superflex and IDP leagues would be silently
wrong. Slot *names* still come from ESPN, and an unrecognized slot falls through to "only its own
position fits" — conservative rather than fabricated. A portability defect, not a live one, and
the first thing to fix if this repo is ever pointed at a second league. → D-038

## Testing

Every module ships with tests, including browser code. Sources are tested against committed
fixtures with a mocked `httpx.MockTransport`, so the suite is deterministic and offline. See the
`client_returning()` helper duplicated across source tests.

**`tests/conftest.py` chdirs every test into a scratch directory**, and that is not tidiness.
`--log`, `--notify-config` and `--cache` all default to paths relative to the working directory, so
any test not overriding all three read and wrote the developer's real files: 463 test records had
accumulated in the actual run log, and `_watch` was loading the real `notify.yaml` on every check
test — with a heartbeat URL configured there, the suite would have been pinging a live monitoring
service and faking a healthy machine. Chdir-per-test rather than per-call-site fixes, because the
defaults are the point of those options and the next test written will forget again.

**When a fixture and the code agree, they can be wrong together.** Twice now the hand-built ESPN
fixture encoded the same wrong assumption as the parser, so a green suite proved only that they
matched each other. **Check a *new* field against a live response, not against the fixture.**

`tests/fixtures/espn_league.json` is hand-built, but the parser is no longer unverified: `ffcoach
league` ran against the real league and returned 12 teams with **zero diagnostics**. It is still
only two teams. Replacing it with a real cookie-scrubbed capture is worth doing — and **`SWID` is
both the owner id in `members[]` and half the auth pair**, so any capture tool must scrub member
ids, not just display names.

## Workflow

Feature branches with PRs into `main` — **never a direct merge** (D-039). CI
(`.github/workflows/test.yml`) runs both suites on every PR.

`ROADMAP.md` is the planning board: §1 status, §3 registry, **§6 the decision log** (the `D-NNN`
references throughout this file), §7 roadblocks. Design docs live in `docs/superpowers/specs/`.
