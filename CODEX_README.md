# Codex README — review brief

**If you are an AI reviewing this repo: read this first, then give concise, opinionated feedback.**

This is a personal fantasy football tool — one ESPN league, one user. It is mid-flight
(14 of 42 planned steps). I am not looking for validation. I want the things I have talked
myself into that are wrong, and the things I have not thought of at all.

**Read this before you judge the shape of the repo.** The product is **in-season alerting
that prevents missed points** — nothing else. The draft board that dominates Stage A and a
third of the test suite is **legacy scaffolding** (`ROADMAP.md` D-050): it was built while
the league invite was outstanding because it was the only thing buildable without a league,
and on 2026-09-03 the user said he does not want draft help at all. It stays because
deleting it costs a day this week does not have. So: reviewing the draft board is wasted
budget, and "Phase 1 complete" does not mean the valuable half is done — `advisors/lineup.py`
is 543 tested lines with **no production caller**, and every notifier, all scheduling, all
logging and the Week page are unbuilt with the first kickoff on **Wed 2026-09-09** (R-4).

**A full review was done on 2026-08-31** ([`docs/end-to-end-review-2026-08-31.md`](docs/end-to-end-review-2026-08-31.md))
and its confirmed findings are fixed ([`docs/review-reply-2026-08-31.md`](docs/review-reply-2026-08-31.md)
says what was implemented, what was challenged, and what it missed). **Read the reply before
reviewing** — re-finding those costs your budget and tells me nothing.

## What I want back

Be blunt and rank ruthlessly. I would rather have **five findings that change what I build**
than forty that are technically true.

- **Lead with the three things you would change first**, and say why in one sentence each.
- Say plainly if a design decision is wrong. Disagreeing with a recorded decision is welcome —
  name the `D-NNN` from `ROADMAP.md` §6 you are overturning so I can see the collision.
- **Skip style nits.** There is no linter configured yet; that is a known gap, not a finding.
  Do not report import order, docstring formatting, or line length.
- **Skip "X is not implemented yet"** unless you think the *plan* has it in the wrong place.
  Stages D–H are deliberately unbuilt; see `ROADMAP.md` §3.3. The one place that critique
  *is* wanted: R-4 asks what to cut from D/E/F to guard Week 1, and an argument about the
  right cut is worth more to me than anything else in this repo right now.
- **Skip the draft board entirely** — `web/index.html`, `advisors/draft.py`,
  `model/value.py`, `model/tiers.py`, `sources/ffcalc.py`. Legacy, per D-050 above.
- For a correctness claim, give a **failure scenario**: concrete inputs → wrong output. If you
  cannot construct one, say it is a suspicion rather than a bug.

## Orient yourself in five minutes

```bash
uv sync && uv run pytest      # 359 tests, fully offline, no credentials needed
npm test                      # 53 browser tests; node --test, no npm packages
uv run ffcoach league --fixture tests/fixtures/espn_league.json   # end-to-end, no ESPN access
uv run ffcoach doctor
```

Everything runs with **no network and no secrets**. If something needs either, that is a bug.

Start with `CLAUDE.md` (architecture and the non-obvious traps), then `ROADMAP.md`
(43 decisions, 40 steps, roadblocks), then `docs/superpowers/specs/` (two design docs).

## The shape of it

```
sources/ → cache (SQLite) → model/ → advisors/ → report/ → web/data/*.json → web/
```

The governing rule: **deterministic Python core, judgment left to a Claude skill.** If it is the
same every time it is a script; if it needs judgment it is not in this repo yet. Advisors emit
structured findings, never prose.

| Area | Files | How much I trust it |
|---|---|---|
| `model/` — pure: no network, filesystem, or clock | `week.py`, `deadlines.py`, `value.py`, `tiers.py`, `players.py` | **High.** Correctness fully determined by the code. Best place to find real bugs. |
| `advisors/` — the detection logic | `lineup.py` (543 lines), `roster_plan.py`, `draft.py` | **Medium.** Recently grown; most likely to hide a logic hole. |
| `sources/` — I/O with cache + stale fallback | `schedule.py`, `crosswalk.py`, `sleeper.py`, `ffcalc.py`, `match.py` | **Medium-high.** All verified against live endpoints. |
| `leagues/espn.py` — ESPN JSON parser | ~290 lines | **Low, and unavoidably so.** See below. Now fails *safely* — see invariant 9. |
| `web/` — vanilla ES modules, no build step | `render.js`, `league_render.js` compute; `main.js`, `league_main.js` touch DOM | **Medium.** Only two pages exist. |

## Do not spend budget here — I already know

1. **`leagues/espn.py` field names — settled 2026-09-03.** It was built from community docs
   against a hand-written fixture, and it has now run against the real league: 12 teams,
   **zero diagnostics**. The names match. You still cannot see the API and neither can I, so
   reviewing it for "correctness against ESPN" still produces confident guesses. Useful
   instead: **does it fail safely when a field is missing or renamed?** — invariant 9.
2. **No linter, no formatter, no type checker, no coverage measurement.** Known; planned.
3. **The ESPN fixture has only two teams**, one with an empty roster. Small on purpose.
4. **Vegas odds are parked** until the season starts (`Q-3`), because the endpoint returns empty
   in the offseason and cannot be checked yet.
5. **Everything in the 2026-08-31 review's "Prioritized findings".** Confirmed and fixed, or
   confirmed and explicitly deferred with a reason. `docs/review-reply-2026-08-31.md` §1 and §2
   say which is which; §3 lists what that review missed, which is a better place to start.
6. **Anything about the draft board.** Legacy per D-050 — see the top of this file. Its
   a11y and mobile gaps are known and will not be fixed there; the responsive patterns get
   settled on the Week page (F1). Its "Value"/bargain-reach model was removed on 2026-09-03
   because `rank` came from the ADP sort, so `adp - rank` graded ADP against itself.
7. **Team defenses never resolve in the crosswalk.** They are absent from the upstream data
   entirely. Structural, documented, not a bug.

## Load-bearing invariants — please try to break these

Each is enforced by a test. If you can construct a case that violates one, that is a top finding.

1. **Nothing is dropped or guessed silently.** A failed source serves stale cache and marks the
   payload stale. Unmatched players are reported, never omitted. Ambiguous identity returns
   `unresolved` rather than a pick. A missing setting disables a check rather than defaulting it.
2. **No dollar figures, ever.** The league uses waiver priority, not a bidding budget.
   Asserted in both `test_report.py` and `render.test.js`.
3. **Standard terminology is never renamed.** The UI says "ADP", not "Typical pick". Terms are
   *annotated*, never replaced. Asserted in `render.test.js`.
4. **Explain mode annotates only** — never changes layout or ordering.
5. **Every recommendation states its reason inline**, in both modes.
6. **`model/` is pure** — no network, no filesystem, no clock. Clocks are injected as `now`.
7. **A deadline never falls after the lock, and never describes an impossible action.**
   `model/deadlines.py` returns a *kind* of fix, not just a time — a waiver claim that cannot
   process before the lock is reported as `ADD_BEFORE_LOCK`, not as a claim with an earlier
   deadline.
8. **Nothing about league format is hardcoded** — scoring, roster slots, team count, and waiver
   schedule all come from config or the league API. *One known, documented exception:
   `_SLOT_ELIGIBILITY` in `advisors/lineup.py`. See CLAUDE.md's config section.*
9. **An unusable external value becomes `UNKNOWN` plus a diagnostic, never a plausible default.**
   Unknown ESPN slot ids do not become `BN`; unknown pro teams do not become `FA`; a schedule row
   we cannot read does not become a bye. Each of those defaults produced a clean run and an
   unguarded lineup.
10. **Data freshness travels with the data.** `SourceResult` carries age and staleness; a page's
    age is its *oldest* input; a source parses before it caches, so a garbage HTTP 200 cannot
    evict the last usable copy.
11. **One bench player is offered to at most one opening.** `advisors/roster_plan.py`.

## The defect class — my sharpest prior, use it

Four real bugs have been found so far. **Three were unchecked assumptions**, not coding errors,
and none would have been caught by the tests as written:

| What I assumed | What was true | How it would have failed |
|---|---|---|
| Waivers process "Wednesday morning" | ESPN's default is **six days a week at 11:00** | Confidently wrong deadlines all season |
| Every roster slot has a player in it | Empty starting slots exist and are the most elementary failure | Advisor iterated the roster; a slot with nobody in it has no entry to iterate, so it was **invisible** |
| The deadline is kickoff | The deadline belongs to the *available fix* — a swap and a waiver claim have different deadlines | Alerts arriving four days after the claim window closed |
| A deadline is bounded by nothing | It cannot fall after the lineup locks | A locked slot advertising a future deadline reads as "you still have time" |
| Clamping the deadline to the lock fixes that | It fixes the *number* and leaves the advice false | "Claim someone by Thu 8:15" for a claim that processes Friday — plausible, impossible, survives inspection |
| A finding with no kickoff never locks | It is bounded by the week's last game | A Week 5 empty slot still reported as actionable on New Year's Day |
| A cached response is a usable response | A 200 can be a login page | Caching it before parsing destroyed the last copy that worked |

**The most useful thing you can do: find the next one.** What else in this codebase is *assumed*
rather than read from data or verified against a source?

## Suspicions I already have — confirm, dismiss, or prioritize

I would rather hand you these than have you spend the budget rediscovering them. Tell me which
actually matter.

Three of the original six were confirmed by the 2026-08-31 review and are now fixed: the shared
replacement, the IR-as-bench-swap case, and where to split `lineup.py`. Still open:

1. **`_SLOT_ELIGIBILITY` in `advisors/lineup.py` is hardcoded** (`FLEX` = RB/WR/TE), the one
   documented exception to invariant 8. Superflex and IDP leagues would be silently wrong. A real
   portability defect, or acceptable for a one-league tool? *(The last review did not address
   this.)*
2. **Bye look-ahead only scans week + 1.** If the waiver deadline is further out than that, is one
   week of warning enough?
3. **`derive_week()` assumes a 4-hour maximum game length.** Arbitrary. Does it break anywhere?
4. **`_reason()` builds user-facing prose inside an advisor** whose stated contract is "structured
   findings, never prose". Reason codes rendered per channel, or advisor-owned sentences? Deferred
   to D2, but the argument is worth having now.
5. **`slot_lock()` falls back to the week's *first* kickoff when a game's time is unpublished**, to
   fail toward alerting early. Is failing early right when the real kickoff might be three days
   later and the early alert is unactionable noise?
6. **A cache hit inside its TTL is reported as not-stale but carries a nonzero age.** Is one
   `stale` boolean plus an age enough for the health panel, or does it need per-source state?
   *(Partly answered the hard way on 2026-09-03: one page-level age was actively wrong. The
   crosswalk's TTL is seven days and ADP's is six hours, so folding them by age made a board
   whose every number was two minutes old announce "data 6d old". `freshest()` now exempts
   lookup tables from the age but not from the staleness — D-053. The general question stands:
   does the health panel need per-source rows?)*
7. **`league.diagnostics` is a tuple of free-text strings.** It reached the payload and the page
   as designed, and on the first live run it was empty — so the mechanism has never actually
   carried anything real. Is untyped prose the right shape for something a UI must group,
   count, and let the user dismiss?

## Review tracks

Cover all six. Weight them by where you actually find something.

### 1. Logic and correctness — highest value
`model/` and `advisors/`. Pure, offline, fully determined by the code. Deadline arithmetic,
timezone handling (everything is `America/New_York`), bye derivation, week rollover, empty-slot
counting, lock-mode collapse. This is where a second opinion is worth the most.

### 2. Architecture and code
Are the boundaries right? Every source module follows one template (`sources/ffcalc.py` is the
canonical example) — is that template sound, and is it followed consistently? Is the
`sources → model → advisors → report` layering real or nominal? Anything that will be painful in
three months?

### 3. UI and UX
Two pages exist: `web/index.html` (draft board) and `web/league.html` (teams and rosters).
No framework, no build step, no npm packages shipped. `web/nav.js` holds one `PAGES` list driving
the nav everywhere.

- Is the compute/DOM split (`render.js` vs `main.js`) actually holding?
- Accessibility, mobile, and dark mode have had **no attention at all**. How bad is it?
- The real UI is still ahead: Stage F designs a week dashboard with an action queue, a
  notification control panel, and a source-health panel. **Review that plan, not just the
  two pages that exist.** Is an "action queue" the right primary object for a page whose job is
  "tell me what to do before Sunday"?
- The stated goal is *"see my team's situation at a glance."* Does the plan deliver that?

### 4. Plan and sequencing
`ROADMAP.md` §3.3 has 42 steps across stages A–H, with 53 decisions in §6 and four roadblocks in §7.

- **The question I most want answered: what would you cut?** R-4 — the first Week 1 kickoff is
  **Wed 2026-09-09 20:20 ET**, and C7, every notifier, all scheduling, all logging and the Week
  page are unbuilt. My candidate cut is E2/E3/E4 (launchd, dead-man's switch, delivery-failure
  fallback) in favour of C7 + D1 + F1 — a check I run and read, before a check that runs itself.
  Argue me out of it, or tell me what I am cutting that I will regret in Week 3.
- Is the stage order right? Notifications (D) come before the dashboard (F). My stated V1 goal
  weights user experience and control as heavily as the alerts themselves.
- **A specific tension I want challenged:** the feature I originally described as most important —
  *"if I have a player on the bench who is expected to score more, notify me"* — is `G4`, tagged
  V1-nice and gated behind projection aggregation. My reasoning was that projections are the
  weakest input available (a 12-season study found aggregation beats every single source, and ESPN
  went from best to last for QBs), so an alert built on one source would be confidently wrong on a
  schedule, and a wolf-crying channel is the same channel carrying "your starter is on bye."
  **Is that reasoning sound, or did I just defer the thing I actually wanted?**
- `E2` (launchd scheduling) is marked high-risk and is untestable in CI. Is there a better shape?
- Anything sequenced too late to be useful, or built too early to be trusted?

### 5. Valuable features I am missing
Already considered and deliberately deferred, so do not just re-suggest these: smack talk (`H1`),
league-wide intelligence for trade targets (`H4`), waiver wire (`H3`), playoff awareness (`H2`),
Vegas game context (`H5`), multi-league (`H6`).

What is genuinely missing? Think about the full season: draft, weekly lineup, waivers, trades,
playoff push, and the parts of playing fantasy football that have nothing to do with optimization.

### 6. Making it fun
This is a game played with friends, and the tool is currently all utility. What would make it
something I *want* to open on a Tuesday rather than something that only pings me when I have a
problem? Be specific and opinionated. Ideas that require no additional data source are worth more
than ideas that need one.

## Where review genuinely cannot help

The single biggest risk in this repo is that `leagues/espn.py` may not match the real ESPN API,
and **no amount of review resolves that** — it needs a league invite and real cookies. Do not
simulate confidence about it. What *is* useful: does the parser degrade gracefully when a field is
absent, renamed, or the wrong type?

## Reporting

For each finding: **file:line · one-sentence claim · concrete failure scenario · what you would
do.** Rank by what changes my next commit. If a section produced nothing worth reporting, say so
in one line rather than padding it.
