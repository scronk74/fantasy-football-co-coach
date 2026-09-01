# Reply to the end-to-end review

**Date:** 2026-08-31 · **Reviewing:** [`end-to-end-review-2026-08-31.md`](end-to-end-review-2026-08-31.md)
· **Implemented on:** `review-fixes-truth-and-viability`

The review was good. It found four things that were live defects, and its central
observation — that "13 of 40 steps" measures code written rather than anything the user can
run — is the most useful sentence anyone has written about this project.

This document says what was implemented, what was challenged and why, and what the review
did not find.

**Tests:** 295 → **356** Python, 38 → **53** JS. Both suites green, still fully offline.

---

## 1. Accepted and implemented

### 1.1 Stale data was published as fresh · P0 · **confirmed, fixed**

The review is exactly right, and the wording matters: this was not "we forgot to display an
age", it was a violation of the invariant the project advertises most loudly. Every source
called `Cache.get_stale()` and threw away the age it returns. Both report paths then passed
`stale_seconds=None` unconditionally, and the payload computed `"stale": stale_seconds is not
None` — so a Sunday-morning fallback to Friday's roster was published with a current
`generated_at` and `stale: false`.

**What was built.** `sources/base.py` introduces `SourceResult(text, age_seconds, stale,
error)`. Every `fetch_*` returns one; there is no bare string left to accidentally pass along.
`freshest()` folds several sources into one page-level number by taking the **oldest**, on the
reasoning that a page built from a fresh schedule and a three-day-old roster is a three-day-old
page — reporting the newest component would be a flattering lie of the same family as the
original bug.

One distinction the review did not draw, which turned out to matter: **a cache hit inside its
TTL is not stale.** That is the cache working. `stale` is reserved for the serious case — the
live fetch failed and we fell back to an entry past its TTL. Conflating the two would have made
the flag fire constantly and stop meaning anything. `Cache.get_with_age()` exists for this:
`get()` answers "may I use this", `get_with_age()` answers "may I use this, and how old is it".

**Where it surfaces.** The CLI prints a warning naming the age and the underlying error; the
payload carries `age_seconds` and `stale` separately; the page shows "stale — showing data from
7d ago; run ffcoach league" and turns the status line red.

### 1.2 An invalid HTTP 200 could poison the cache · P0 · **confirmed, fixed**

The sharpest finding in the review, and the one I would not have found on my own, because the
failure requires the fetch to *succeed*. Raw response text was written to the cache before any
parser looked at it. A login page, a captive portal, a truncated CSV — all arrive with a 200
and all would evict the last known-good copy, after which parsing fails and there is nothing to
fall back on. The cache was least reliable exactly when it was most needed.

**What was built.** Every source now parses before it caches, and treats an unparseable 200 as
a fetch failure — falling back to cache like any other. `stale_fallback()` in `sources/base.py`
is the shared implementation. `leagues/espn_client.py` imports `parse_league` lazily inside the
function to avoid the import cycle, commented.

This is a real change to the source template, so **CLAUDE.md was amended** — the template is
copied by every future source and a template with this hole in it would propagate.

Five tests, including the specific scenario the review described: a good cached ESPN response,
a clock advanced past its TTL, and a login page returned with status 200. The good copy
survives.

### 1.3 The deadline model described impossible transactions · P0 · **confirmed; my own fix was wrong**

I should be direct about this one. I found this defect five days ago during C5, and the fix I
shipped was insufficient in a way the review names precisely.

The symptom was a finding printing `LOCKED` while advertising a Friday deadline for a lineup
that froze Thursday. I clamped: `min(waiver_deadline, slot_locks_at)`. That stopped the number
from printing after the lock — and left `needs_waiver=True` attached to it. So the message
became *"claim someone by Thursday 8:15"* for a claim that cannot process until Friday.

I fixed the number and left the advice false. That is worse than the original, because the
original looked wrong and this survives inspection.

The reason the clamp cannot work is structural: **a time cannot express "a claim is the wrong
instrument."** Only a kind can.

**What was built.** `model/deadlines.py` returns a `FixPlan`:

| Kind | Meaning | Verb |
|---|---|---|
| `BENCH_SWAP` | A named bench player fits, is healthy, and plays | Swap |
| `WAIVER_CLAIM` | Nobody on the bench fits, but waivers process before the lock | Claim |
| `ADD_BEFORE_LOCK` | Nobody fits and the next waiver run is *after* the lock — a claim cannot land; only a free agent can | Add |
| `UNKNOWN` | Nobody fits and the league publishes no waiver schedule | Review |

The verb answers the review's UI point about never making the user infer the transaction type
from prose, at no extra cost.

Ties fail safe: a waiver run at the *exact* lock moment is `ADD_BEFORE_LOCK`, because a claim
processing as the lineup freezes did not make the lineup.

**D-014's principle survives** — the deadline belongs to the available fix, not to the problem.
Only its implementation is replaced. The roadmap records this as D-046 amending D-014 rather
than overturning it.

**One kind was deliberately omitted.** The review suggested `FREE_AGENT_ADD` alongside
`WAIVER_CLAIM`. Nothing in this project fetches the free-agent pool, so that kind could never
be emitted from data on hand. A variant the code can never produce is a promise it does not
keep. `ADD_BEFORE_LOCK` says what we actually know: a claim cannot land, and adding a free
agent is the only remaining path — without pretending to know whether one is available.

### 1.4 Bye and empty-slot findings never expired · P0 (part of the same finding) · **confirmed, fixed**

The review found this inside its deadline finding and it deserves separating, because it is a
different bug with a different cause. A bye starter has no kickoff (his team does not play). An
empty slot has no player, so no kickoff either. `locks_at` was `None` for both, and
`_is_locked()` read `None` as *never locks*.

So a Week 5 empty-slot finding still reported itself as actionable on New Year's Day. Two tests
asserted that this was correct. They were wrong and have been rewritten to say so in their
docstrings.

**What was built.** `slot_lock()` bounds a slot with no occupant kickoff by the week's **last**
kickoff — the point past which no addition can put a point in it. And `actionable(findings,
now)` now asks the whole question rather than only `locked`:

1. is the slot frozen,
2. has the fix's *own* deadline passed (a bench replacement whose game kicked off is no longer
   a replacement),
3. does any action remain.

Demonstrated end to end on the fixture: at Jan 1 2026 for Week 5, **6 findings, 0 actionable**.
Before this, all six read as still fixable.

### 1.5 Replacements were individually valid and jointly impossible · P1 · **confirmed, fixed**

This confirms a suspicion already listed in `CODEX_README.md`; the review's contribution was
answering "does it matter in practice" with yes, and connecting it to the IR case.

`find_replacements()` ran independently per broken slot with no memory of prior assignment. Two
OUT receivers and one healthy bench WR produced two findings that each named him. Fix either
and the other is exactly as broken. Every card true, the set impossible.

**What was built.** `advisors/roster_plan.py` allocates once across all openings — empty slots
and broken starters together, since they compete for the same bench. **Most-constrained-first:**
openings are served in order of how few candidates they have, so a dedicated RB slot is not
stripped of its only option by a FLEX slot that a WR could have filled. Ties break on input
order, so output is deterministic.

Leftover candidates are still offered as `alternates`, because with a deep bench a single
problem should read as a choice rather than an order. Every opening holds its own reservation
first, so following the primary suggestion can never double-book.

**IR.** ESPN will not start a player out of an IR slot, so naming a healthy IR occupant as a
replacement describes a move the site refuses. He is now excluded from `replacements` — and
reported in `ir_candidates` with the reason line noting he would have to come off IR first,
because dropping him silently would violate the same invariant this whole exercise is about.

### 1.6 A missing kickoff time was read as a bye · P1 · **confirmed, fixed, and widened**

Rows with a blank `gametime` were dropped at parse. `is_on_bye()` then defined "no row for this
team this week" as a bye. So a Week 2 KC–DEN game whose time was still TBD made both teams read
as on bye — a data-quality gap emitted as the single most certain fact this product makes, at
interrupt priority.

**What was built.** `Game.kickoff` is now nullable and rows with teams but no time are kept.
`Schedule.status()` returns `playing` / `bye` / `unknown`, and `kickoff_known()` distinguishes
"no game" from "time not published". A game with an unpublished time contributes no lock window
— a blank cell must not become a deadline. When a starter's kickoff is unknown, his lock falls
back to the week's *first* kickoff and the finding is flagged `lock_is_estimated`, matching the
precedent C5 set for an unrecognized lock setting: fail toward the earlier deadline, alert too
soon rather than too late.

**The part the review did not reach.** Writing the test made it obvious the same defect is
broader than the case that found it: **any** dropped or missing row becomes a bye, not just an
untimed one. A download truncated after Week 3 turns every remaining week into a bye —
interrupt-priority alerts manufactured out of a broken transfer.

So `status()` additionally requires that a missing week be the team's **single** missing week
before calling it a bye. Every NFL team has exactly one. A team missing three weeks has a
broken feed, not three byes.

### 1.7 ESPN contract failures crashed or silently mislabeled data · P1 · **confirmed, fixed**

Two separate problems, and the review is right that the second is the dangerous one.

**Crashes.** Only `json.JSONDecodeError` became `EspnUnavailable`. Valid JSON of the wrong
shape escaped as a bare `AttributeError` or `ValueError` — past every `except EspnUnavailable`,
so no stale fallback ran and the CLI's friendly error never printed. Now the top-level shapes
are checked explicitly and the team-parsing loop converts type errors to `EspnUnavailable` with
a message. Five parameterized mutation tests, each confirmed reachable before the guards
existed.

**False silence.** An unknown `lineupSlotId` defaulted to `"BN"` and an unknown `proTeamId` to
`"FA"`. These are the two worst available defaults: the first hides a real starter from every
check, and the second matches no schedule row, so the player looks like someone with nothing to
worry about. Both produce a clean run and an unguarded lineup.

Both now become `UNKNOWN` with a diagnostic. `UNKNOWN` is deliberately *not* a bench slot, so
an unknown-slot player is still evaluated as a starter — fail toward checking rather than
skipping. `proTeamId: 0` still maps to `FA`, because there it genuinely means free agent.

**Waiver hour.** An hour of 25 parsed and blew up much later constructing a datetime. It is now
discarded, not clamped — clamping to 23 would manufacture a confident deadline from a value
known to be wrong. Discarding makes the deadline `None`, which every caller already handles as
"a claim is needed but not by when".

**Diagnostics go where a human looks.** `League.diagnostics` travels into the payload and onto
the page, not only to the stderr of a scheduled run nobody watches.

### 1.8 The league page dropped injury status it already had · P1 · **confirmed, fixed**

Parsed, carried on `RosterEntry`, and then omitted from the report contract. Amon-Ra St. Brown
is QUESTIONABLE in the fixture and the page showed nothing.

Now rendered as a compact badge. **Never colour alone** — a letter (`Q` / `OUT` / `IR`) plus a
`title` spelling out the status, with colour only reinforcing. A red dot is invisible to a
screen reader and to roughly one man in twelve. This is now UX rule 5 in CLAUDE.md with a test
behind it, so it holds for the Week page too.

An unrecognized status renders blank rather than guessed at.

### 1.9 The fixture demo did not exercise its own promise · **confirmed, fixed**

`--fixture` hardcoded `my_swid=None`, so the generated page had no "your team" card while its
own copy promised "Your team is pinned to the top." A small thing that made the documented demo
misrepresent the product. Added `--my-swid`; verified Dynasty now sorts first and carries the
badge.

### 1.10 Phone and touch targets · P1 · **partially fixed**

The draft table now sits in a scrollable wrapper rather than clipping the availability column
off-screen, and controls meet a 44px target below 640px.

**Not done:** focus preservation across re-render, `aria-pressed` on the position chips, the
button label that still says "Mark … drafted" after becoming an undo, `aria-live` on the
best-available line, versioned localStorage parsing, and the dark-mode position-badge contrast
(measured 1.67–2.72:1 against a 4.5:1 requirement). These are all real. They are also all on
the draft board, which the in-season spec puts out of scope, and doing them now means doing
them twice — the Week page is where the responsive and a11y patterns should actually be
settled. Deferred to F1 as a deliberate, recorded choice rather than an oversight.

---

## 2. Challenged

### 2.1 The proposed resequencing goes further than its evidence

**Accepted:** build `CheckResult` and `ffcoach check --dry-run` before delivery. The argument
is airtight — `find_problems()` has no production caller, so there is nothing for a notifier to
send and nowhere for orchestration to live except inside a delivery module. That is now C7 and
it is next.

**Not accepted:** `F0 → fixture-backed F1 → CheckResult → D1/D2 → E1`, i.e. moving the whole
web server and Week dashboard ahead of notifications.

The review's own failure scenario for this is "the Week UI then exposes that freshness,
multiple replacements, impossible fixes, or clean-state proof do not fit the result schema,
forcing rework." But every one of those four is now *in* the schema — that is what §1 was. The
scenario was written against the codebase as it stood this morning, and the repairs it
recommended largely dissolve it.

What remains is a real but weaker claim: a UI would surface schema gaps earlier. True. Against
it: the stated V1 goal weights **trustworthy alerts** and **control over notifications**
alongside UX, and F0+F1 is a substantially larger build than D1+D2. Putting the dashboard first
delays every alert by that margin on the strength of a scenario whose specifics have been
addressed.

So: C7, then D1/D2 (ntfy + rendering), then F0/F1 consuming the same object. If C7's schema
turns out to be wrong, that is cheap to discover with a `--dry-run` printout and does not
require a web server to find out.

### 2.2 "The deadline clamp turns an impossible waiver into a plausible kickoff deadline" — half right

The diagnosis is correct and produced the best fix in this batch. One detail is not: the review
says `actionable()` "checks only `locked`, not whether a viable fix and an unexpired effective
deadline exist", and files this as one finding with the deadline problem. They are two bugs
with different causes — the clamp is a modelling error, the never-expiring finding is a
`None`-means-forever error — and fixing only the first would have left January's empty slot
reporting itself as fixable. Split into §1.3 and §1.4 so each has its own tests.

### 2.3 `FREE_AGENT_ADD` — declined, with a substitute

Covered in §1.3. Modelling a kind we cannot emit would be the same class of error as the
plausible defaults in §1.7: a confident-looking value standing in for information we do not
have.

### 2.4 "Projection weighting is overbuilt" — agreed on the conclusion, not the reasoning

The recommendation (ship two-source consensus, show disagreement, start the decision log
immediately, weight only after evidence) is right and I would adopt it. But the review reaches
it partly by noting that D-043 already says ship two while the spec text says three — that is a
stale-document inconsistency, not evidence about weighting.

The real argument is the one the review makes second: you cannot weight by measured accuracy
before you have measured any accuracy, and a handful of volatile outcomes in a single league
will overfit. That stands on its own. Recorded, not yet implemented — G1/G2 are not built and
this changes nothing today.

### 2.5 "Was G4 deferred for good reasons, or did I defer what I actually wanted?" — the review did not answer this

`CODEX_README.md` asked directly whether gating bench-upgrade alerts behind projection
aggregation was sound reasoning or rationalization. The reply restates the conclusion and adds
"usefulness of two-source advice remains a season experiment," which is a way of not answering.

My own read, unchanged: the reasoning holds, because the *channel* is shared. An alert that is
wrong a third of the time trains you to ignore the channel that also carries "your starter is
on bye." The mitigation is not better projections, it is a separate tier — which D-032 already
specifies. So the honest answer is that G4 was deferred for a sound reason **and** could ship
earlier than planned if it never interrupts. Worth revisiting after C7.

### 2.6 Value model, security hardening, launchd — accepted, not yet built

- **Draft "Value" is not an independent ranking** (P2). Correct: `draft.py` sorts by ADP,
  assigns rank from that sort order, then computes `ADP − rank`, so "value" is mostly an
  artifact of gaps in ADP and of the API returning more players than get drafted. Washington
  Defense at ADP 195.9 and row rank 271 is a real example. The label should be removed or the
  column renamed. **Not done here** — it is a shipped user-facing behaviour on a page the
  in-season spec puts out of scope, and changing what the board says deserves its own decision
  rather than being folded into a bug-fix branch.
- **Security before `serve`** — file permissions on `espn.yaml`, loopback-only binding, CSRF on
  config writes. All correct, all about a command that does not exist yet. They belong in F0's
  definition, not in this branch.
- **Scheduler and dead-man share one sleeping iMac** (P0). The clearest thinking in the review
  and it needs no code today: a process on the machine cannot warn you while the machine is
  asleep. Recorded as **R-3**, framed as the review framed it — either an off-host heartbeat,
  or the product's own copy stops saying "never miss".

---

## 3. What the review did not find

Not a criticism of the reviewer for most of these — several are only visible from inside the
history. Listed because the point of the exercise was to find what I am missing.

1. **The bye defect generalizes past missing kickoff times.** Found while writing the test for
   §1.6. Any dropped row becomes a bye, so a truncated download manufactures a run of
   interrupt-priority alerts. The review found the TBD-kickoff instance and stopped there. Fixed
   by requiring a bye to be the team's single missing week.

2. **"Stale" and "old" were being conflated in the fix as well as the bug.** The review's
   recommendation — "preserve freshness per source" — would, taken literally, mark every cache
   hit as stale, since the flag was computed from whether an age existed. The distinction
   between a hit inside its TTL and a fallback past it is what keeps the flag meaningful.

3. **`Cache` had no API for the fix it asked for.** `get()` returns a value without an age;
   `get_stale()` returns an age but ignores the TTL. Neither answers "give me this if it is
   still good, and tell me how old it is." Added `get_with_age()`.

4. **The import cycle.** Parsing before caching means `espn_client` needs `espn.parse_league`,
   and `espn` imports `espn_client`'s exceptions. Resolvable, but the review's recommendation
   ("validate before replacing the last-known-good cache") does not survive contact with the
   module graph without a note explaining the lazy import.

5. **`ADD_BEFORE_LOCK` needs `>=`, not `>`.** A waiver run at the exact lock moment has not made
   the lineup. A one-character decision, but it is the tie-breaking rule for the whole model and
   it deserved a test.

6. **The review checked ESPN mutations but not schedule mutations.** Its test list includes four
   ESPN-shape cases and one schedule case. The schedule is equally external, equally CSV, and
   its failure mode (phantom byes) is louder than the ESPN parser's. Added: non-numeric week,
   missing team, duplicate handling, truncation.

7. **It reported `lineup.py` at 362 lines without saying where to cut.** `CODEX_README.md` asked
   "should it be split, and where?" — the reply notes the size in passing and does not answer.
   The seam that emerged from the work is not size-driven: **detection, allocation, and fix
   modelling are three different decisions**, and two of them were being made per-finding when
   they are properly made per-roster and per-model. Allocation went to
   `advisors/roster_plan.py`, fix modelling to `model/deadlines.py`.

   Being accurate about the result: `lineup.py` **grew, 362 → 543 lines.** Extracting two
   responsibilities did not shrink it, because the same change added the openings/assignment
   pipeline, `slot_lock`, `is_actionable`, and IR candidates. Line count was never the real
   measure; what improved is that each remaining piece answers one question. The next genuine
   seam is the one the review identified elsewhere — `_reason()` builds user-facing prose inside
   an advisor whose contract says it emits structured findings. That is D2's decision (structured
   reason codes rendered per channel, or advisor-owned prose — not both), so it stays put for now.

8. **Nothing was said about the `_SLOT_ELIGIBILITY` question.** `CODEX_README.md` asked whether
   the hardcoded `FLEX = RB/WR/TE` is a real portability defect or acceptable for a one-league
   tool. The review's product table does not address it. Left hardcoded, now with a comment
   saying so and a note in CLAUDE.md's config section — it is the first thing to fix if this is
   ever pointed at a second league, and it is not a live defect for this one.

9. **The all-clear state is right and under-argued.** The review is correct that "I know the
   check ran and my lineup is clean" is a feature rather than the absence of an alert. But it
   lists this under UI, where it will be built last. It is really a property of `CheckResult` —
   if the object cannot represent "checked, nothing wrong, here is how fresh the inputs were",
   no consumer can display it. Pulled forward into C7.1.

---

## 4. What changed on disk

| Area | Files |
|---|---|
| New | `sources/base.py`, `advisors/roster_plan.py` |
| Freshness + validate-before-cache | `cache.py`, `sources/{ffcalc,sleeper,schedule,crosswalk}.py`, `leagues/espn_client.py` |
| Fix viability | `model/deadlines.py`, `advisors/lineup.py` |
| Contract hardening | `leagues/espn.py`, `leagues/base.py` |
| Payload + CLI | `report/build.py`, `cli.py` |
| Browser | `web/{render,league_render,main,league_main}.js`, `style.css`, `index.html`, `league.html` |
| Tests | `test_source_freshness.py`, `test_roster_plan.py` (new); `test_deadlines.py`, `test_lineup_advisor.py`, `test_espn_parse.py`, `test_schedule.py`, `test_report.py` |
| Docs | `CLAUDE.md`, `ROADMAP.md` (D-044…D-049, R-3, C6/C7), `docs/roadmap/C.md` |

Four existing tests asserted the buggy behaviour and were rewritten, each with a docstring
naming the defect it used to bless. That is the review's most quotable line — *"existing tests
currently bless the wrong behavior"* — and it is worth leaving a trail of.

## 5. Next

**C7:** `CheckResult` + `ffcoach check --dry-run`, including the all-clear state. Then D1/D2.

The one thing no amount of review moves is **R-1**: `leagues/espn.py` is still unverified
against a real league. What §1.7 bought is that it now fails *safely* — loudly on a wrong shape,
`UNKNOWN` on a value it does not recognize, never `BN` or `FA` or a phantom bye. That is the
most that can be done without the invite.
