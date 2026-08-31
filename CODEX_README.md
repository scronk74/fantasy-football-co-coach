# Codex README — review brief

**If you are an AI reviewing this repo: read this first, then give concise, opinionated feedback.**

This is a personal fantasy football tool — one ESPN league, one user. It is mid-flight
(13 of 40 planned steps). I am not looking for validation. I want the things I have talked
myself into that are wrong, and the things I have not thought of at all.

## What I want back

Be blunt and rank ruthlessly. I would rather have **five findings that change what I build**
than forty that are technically true.

- **Lead with the three things you would change first**, and say why in one sentence each.
- Say plainly if a design decision is wrong. Disagreeing with a recorded decision is welcome —
  name the `D-NNN` from `ROADMAP.md` §6 you are overturning so I can see the collision.
- **Skip style nits.** There is no linter configured yet; that is a known gap, not a finding.
  Do not report import order, docstring formatting, or line length.
- **Skip "X is not implemented yet"** unless you think the *plan* has it in the wrong place.
  Stages D–H are deliberately unbuilt; see `ROADMAP.md` §3.3.
- For a correctness claim, give a **failure scenario**: concrete inputs → wrong output. If you
  cannot construct one, say it is a suspicion rather than a bug.

## Orient yourself in five minutes

```bash
uv sync && uv run pytest      # 295 tests, fully offline, no credentials needed
npm test                      # 38 browser tests; node --test, no npm packages
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
| `advisors/` — the detection logic | `lineup.py` (362 lines), `draft.py` | **Medium.** Recently grown; most likely to hide a logic hole. |
| `sources/` — I/O with cache + stale fallback | `schedule.py`, `crosswalk.py`, `sleeper.py`, `ffcalc.py`, `match.py` | **Medium-high.** All verified against live endpoints. |
| `leagues/espn.py` — ESPN JSON parser | 221 lines | **Low, and unavoidably so.** See below. |
| `web/` — vanilla ES modules, no build step | `render.js`, `league_render.js` compute; `main.js`, `league_main.js` touch DOM | **Medium.** Only two pages exist. |

## Do not spend budget here — I already know

1. **`leagues/espn.py` is unverified against a real league.** I have not been invited to the
   league yet, so there are no cookies and no live data. It was built from community docs against
   a **hand-written fixture** (`tests/fixtures/espn_league.json`). Tests passing proves internal
   consistency, *not* that field names match ESPN. You cannot verify this either — neither of us
   can see the API. Reviewing it for "correctness against ESPN" produces confident guesses.
   Useful instead: **does it fail safely when a field is missing or renamed?**
2. **No linter, no formatter, no type checker, no coverage measurement.** Known; planned.
3. **The ESPN fixture has only two teams**, one with an empty roster. Small on purpose.
4. **Vegas odds are parked** until the season starts (`Q-3`), because the endpoint returns empty
   in the offseason and cannot be checked yet.
5. **Team defenses never resolve in the crosswalk.** They are absent from the upstream data
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
7. **A deadline can never fall after the lock.** Added recently; see below.
8. **Nothing about league format is hardcoded** — scoring, roster slots, team count, and waiver
   schedule all come from config or the league API. *(I suspect this one is already violated —
   see the suspicions list.)*

## The defect class — my sharpest prior, use it

Four real bugs have been found so far. **Three were unchecked assumptions**, not coding errors,
and none would have been caught by the tests as written:

| What I assumed | What was true | How it would have failed |
|---|---|---|
| Waivers process "Wednesday morning" | ESPN's default is **six days a week at 11:00** | Confidently wrong deadlines all season |
| Every roster slot has a player in it | Empty starting slots exist and are the most elementary failure | Advisor iterated the roster; a slot with nobody in it has no entry to iterate, so it was **invisible** |
| The deadline is kickoff | The deadline belongs to the *available fix* — a swap and a waiver claim have different deadlines | Alerts arriving four days after the claim window closed |
| A deadline is bounded by nothing | It cannot fall after the lineup locks | A locked slot advertising a future deadline reads as "you still have time" |

**The most useful thing you can do: find the next one.** What else in this codebase is *assumed*
rather than read from data or verified against a source?

## Suspicions I already have — confirm, dismiss, or prioritize

I would rather hand you these than have you spend the budget rediscovering them. Tell me which
actually matter.

1. **Two broken starters can be offered the same replacement.** `find_replacements()` is called
   independently per finding with no accounting for prior assignment. Two OUT wide receivers with
   one healthy bench WR produce two findings that each name him. Fix one and the other is still
   broken. How much does this matter in practice?
2. **`_SLOT_ELIGIBILITY` in `advisors/lineup.py` is hardcoded** (`FLEX` = RB/WR/TE). That appears
   to violate invariant 8. Superflex and IDP leagues would be silently wrong. Does this matter for
   a single-league personal tool, or is it a real portability defect?
3. **Bye look-ahead only scans week + 1.** If the waiver deadline is further out than that, is one
   week of warning enough?
4. **A healthy player parked in an IR slot may be offered as a replacement**, but ESPN will not let
   you start directly from IR. Real, or can't-happen?
5. **`derive_week()` assumes a 4-hour maximum game length.** Arbitrary. Does it break anywhere?
6. **`advisors/lineup.py` is 362 lines** and has grown three times. Should it be split, and where?

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
`ROADMAP.md` §3.3 has 40 steps across stages A–H, with 43 decisions in §6 and roadblocks in §7.

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
