# Stage C — Lineup detection

> Task-level detail for the imminent stage. Steps and status live in [`ROADMAP.md`](../../ROADMAP.md) §3.3.
> Later stages stay at Step level until work approaches them (progressive elaboration).

**Stage goal:** the advisor correctly identifies every starter who cannot score this week, knows which
week it is, and knows the real deadline for fixing each problem.

**Status: 6/7 done, 2026-08-31.** [R-1](../../ROADMAP.md#7-roadblocks) still gates *live
verification* — every module here is proven against fixtures, not against a real ESPN league — but no
step in the stage turned out to require the invite to build.

C6 was added by the [2026-08-31 end-to-end review](../end-to-end-review-2026-08-31.md), which found
that C4 and C5 had each fixed a symptom rather than its cause. C7 is the composition step that review
also found missing: the advisor this stage built has no production caller.

---

## C1 — Lineup advisor: bye / OUT / IR ✅ Done

Shipped in `src/ffcoach/advisors/lineup.py`. 32 tests.

Notable behaviors, each deliberate:
- QUESTIONABLE and DOUBTFUL are **not** treated as out (D-010) — that is E6's job.
- Findings past kickoff are returned flagged `locked` rather than dropped (D-011).
- Replacements are named on availability only — *"is healthy and plays this week"*, never
  *"will score more"*. The latter needs G2.

---

## C2 — Empty-slot detection ✅ Done *(2026-08-29)*

**The bug:** `find_problems` iterates `team.roster`. An empty starting slot **has no entry to
iterate**, so it produces no finding. The most elementary lineup failure in fantasy football — a slot
with nobody in it, a guaranteed zero — is invisible to the tool built to catch lineup failures.

Found by walking the user journey, not by a test. No existing test would have caught it, because every
fixture roster is fully populated.

- [x] **C2.1** — Add a failing test: a team whose required starting slots exceed its filled starting
      slots produces an `empty_slot` finding.
- [x] **C2.2** — Establish required slots. `LeagueConfig.roster` has them for the manual path; ESPN's
      `rosterSettings.lineupSlotCounts` is the real source. Prefer ESPN, fall back to config.
- [x] **C2.3** — Implement: diff required slots against filled slots; emit one finding per empty slot.
- [x] **C2.4** — Severity — same as OUT (D-012). Confirm ordering test.
- [x] **C2.5** — Replacements: reuse `find_replacements`; an empty slot with an eligible bench player
      is the easiest possible fix and should say so.
- [x] **C2.6** — Verify against the ESPN fixture with a slot deliberately emptied.

**Outcome:** fixed by *counting* required vs filled slots rather than iterating entries.
Verified end-to-end against the ESPN fixture: **1 finding before, 6 after** — five empty
slots that were previously invisible. Slot counts come from ESPN's
`rosterSettings.lineupSlotCounts`, whose shape was confirmed against the live public
endpoint. When counts are absent the check is **skipped, not guessed** — inventing a
number would manufacture either findings or false silence.

---

## C3 — Current week from ESPN ✅ Done *(2026-08-29)*

**The gap:** nothing determines the current week. `find_problems(team, schedule, week, now)` takes it
as a parameter no caller computes. Every part of the system is week-indexed.

**Decision D-013:** take ESPN's `scoringPeriodId` rather than deriving from the calendar. Verified
present in the public settings response. Deriving it means owning the rollover moment, and a rollover
bug alerts about the *wrong week entirely* — silent and total.

- [x] **C3.1** — Test: `parse_league` extracts `scoringPeriodId` and `status.currentMatchupPeriod`.
- [x] **C3.2** — Add both to the `League` model.
- [x] **C3.3** — Thread the week through the CLI so no caller invents one.
- [x] **C3.4** — Fallback when the league fetch fails: derive from the cached schedule, and **log that
      the fallback was used** (E1) — a silently-wrong week is the worst outcome here.
- [x] **C3.5** — Guard test: week 0 / missing / out-of-range is an error, never a default.

**Outcome:** `src/ffcoach/model/week.py`, 17 tests. ESPN's number short-circuits *before* any
schedule fetch — verified the ESPN path writes nothing to the cache and needs no network.
Derivation is fallback-only and self-labels as `derived`; the CLI prints provenance either way
and warns on stderr when it fell back. With neither source the command exits nonzero rather
than defaulting.

---

## C4 — Action-deadline alerting + bye look-ahead ✅ Done *(2026-08-30)*

**The reframe (D-014).** Alerts were timed off kickoff. That is the wrong deadline whenever the fix is
not a lineup swap: a starter who is out with **no bench replacement** needs a waiver claim, and waivers
process Wednesday morning. A Sunday 10:00 alert is before the lineup locks and hopelessly after every
useful replacement is gone.

| Situation | Real deadline |
|---|---|
| Bench replacement exists | That player's kickoff |
| No bench replacement | Waiver deadline — a claim is required |
| Bye next week, thin at that position | This week's waiver deadline |

- [x] **C4.1** — Add `deadline` and `needs_waiver` to `LineupFinding`.
- [x] **C4.2** — Compute deadline from replacement availability, not kind.
- [x] **C4.3** — Bye look-ahead: scan week + 1, flag positions with no healthy alternative.
- [x] **C4.4** — Waiver-processing time: a league setting; read it, don't assume Wednesday.
- [x] **C4.5** — Tests: same finding yields different deadlines depending on bench depth.

**Outcome:** `src/ffcoach/model/deadlines.py` + 13 tests. Fixture demo: **five problems due
Wed 11:00, one due Sun 13:00**. Under the old scheme all six read Sun 13:00 — the user would
have heard about them Sunday morning, four days after the claim window closed.

**C4.4 correction:** the assumption was wrong. ESPN's live default league processes waivers
**six days a week at 11:00**, not Wednesday morning. Read from `acquisitionSettings`; when a
league publishes nothing the deadline is `None`, never fabricated.

---

## C5 — Read the lineup-lock setting · Done *(2026-08-30)*

Some ESPN leagues lock **all** lineups at the week's first game rather than per player. Under that
rule, per-player timing is actively wrong — a Sunday alert about a Monday-night starter is pointless
because he locked Thursday.

- [x] **C5.1** — ~~Find the field~~ **Found while building C2**: `rosterSettings.lineupLocktimeType`,
      which returned `"INDIVIDUAL_GAME"` on the live public league. (An earlier note named
      `lineupLockTimeOffset` — that field returned `None` and is *not* the right one.)
- [x] **C5.2** — `LockMode` enum + `LineupLock` (mode, raw, `assumed`, `unrecognized`, `note`) in
      `leagues/base.py`, mirroring `WeekResolution`'s value-plus-provenance idiom.
- [x] **C5.3** — `advisors/lineup.lock_time()`. Under a weekly lock every player's lock resolves to
      `schedule.lock_windows(week)[0]`, so `fix_deadline`'s `min()` collapses the whole roster to one
      deadline without special-casing.
- [x] **C5.4** — Absent setting → per-player, and `ffcoach league` prints the assumption to stderr
      beside the existing derived-week note.

### R-1 turned out not to gate this

The board said C5 needed a real league to learn the weekly-lock spelling. It did not. ESPN offers
exactly two lock rules and the **default** one is verified live, so matching `INDIVIDUAL_GAME` and
treating anything else as weekly needs only the value we already have. The asymmetry with *absence*
is deliberate: a present-but-unfamiliar value is evidence the league chose the non-default rule;
absence is no evidence at all, so it falls back to the default and says so. Unrecognized also fails
toward the **earlier** deadline, which alerts too soon rather than too late.

### Defect found and fixed here (predates C5) — and the fix was wrong

A deadline could land *after* the lock — a waiver run processing Friday advertised as the fix for a
slot that froze Thursday, which reads as "you still have time" at exactly the moment you have none.
`fix_deadline` was made to clamp to the lock. This was live in C4 under per-player locking too, not
only under the weekly rule; the weekly demonstration is just what made it visible.

**The clamp was not the fix.** The 2026-08-31 review is right that it repaired the number and left
the advice false: `min(waiver, lock)` still returned `needs_waiver=True`, so the message became
"claim someone by Thursday 8:15" for a claim that cannot process until Friday. A plausible time
attached to an impossible action is arguably worse than an obviously wrong one, because it survives
inspection. Corrected in [C6](#c6--truth-repairs-from-the-2026-08-31-review--done-2026-08-31) by
`FixPlan`, which names the *kind* of action before its deadline (D-046).

`kickoff` and `locks_at` are kept as separate fields on `LineupFinding`: under a weekly lock they are
different facts — when he plays, versus when you lose the ability to bench him.

**Still wants R-1** to confirm the weekly value's actual spelling, but only to move it from the
`unrecognized` branch to a recognized one. Behavior is already correct either way.

---

## C6 — Truth repairs from the 2026-08-31 review ✅ Done *(2026-08-31)*

Six confirmed defects, four of them the same shape: **a plausible default standing in for a value we
did not actually have.** None would have been caught by the tests as written, and four produced a
clean-looking run rather than an error.

- [x] **C6.1** — `SourceResult`: freshness travels with the data; `freshest()` folds sources by
      taking the oldest. Both report paths had hardcoded `stale_seconds=None` (D-044).
- [x] **C6.2** — Parse before caching, in all five sources. An ESPN session-expiry page arrives as a
      200 and used to evict the roster we could still have fallen back on (D-044).
- [x] **C6.3** — `FixPlan` replaces `(deadline, needs_waiver)`; a claim that cannot land is not
      offered as a claim (D-046). Supersedes C5's clamp.
- [x] **C6.4** — Bye and empty-slot findings are bounded by the week's last kickoff. "No kickoff"
      had been read as "never locks", so a Week 5 empty slot was still actionable in January.
      `actionable()` now takes `now`.
- [x] **C6.5** — `advisors/roster_plan.py`: one bench player is allocated to one opening. IR is a
      prerequisite, not a swap (D-045).
- [x] **C6.6** — `Schedule.status()` tri-state; a bye requires being the *single* missing week
      (D-048).
- [x] **C6.7** — ESPN shape validation; unknown slot/team ids become `UNKNOWN` with a diagnostic
      rather than `BN`/`FA`; an out-of-range waiver hour is discarded rather than clamped (D-047).
- [x] **C6.8** — Injury status reaches the page; freshness and diagnostics are displayed; the draft
      table scrolls on a phone.

**Outcome:** 356 Python tests (was 295), 53 JS (was 38). Fixture demo at Jan 1 for Week 5: **6
findings, 0 actionable.** Before, all six read as still fixable.

Full reply to the review, including what was challenged and what it missed:
[`docs/review-reply-2026-08-31.md`](../review-reply-2026-08-31.md).

---

## C7 — `CheckResult` + `ffcoach check --dry-run` · Next

The review's most damning finding: `find_problems()` appears exactly once under `src/`, at its own
definition. `ffcoach league` parses ESPN, resolves the week, and writes a roster page — it never
loads the schedule, computes the waiver deadline, picks the user's team, or calls the advisor.
Stage C's work is real and tested and **nothing runs it**.

That also means there is no place for orchestration to live, so building D1 first would hide it
inside a delivery module.

- [x] **C7.1** — `CheckResult`: source health (per-source age + stale), week provenance, the one
      user team, findings with fix plans, next lock, and an explicit all-clear state.
- [x] **C7.2** — `ffcoach check --fixture … --now …`, so the whole safety decision is
      exercisable offline with no cookies.
- [x] **C7.3** — Exactly-one-user-team selection, with a clear error when zero or several match.
- [x] **C7.4** — Tests: end-to-end fixture check; a clean week produces an all-clear rather than
      silence.

**Outcome.** `src/ffcoach/check.py` (pure — inputs and `now` are passed in),
`src/ffcoach/report/check_text.py` (terminal rendering, kept out of both the pure layer and
the CLI), and `ffcoach check`. 399 Python tests, up from 359.

**Three things the plan did not anticipate.**

1. **An all-clear needs a fourth state, and silence is the bug.** A check that finds nothing is
   not a check that found nothing wrong. If ESPN did not publish `lineupSlotCounts` the
   empty-slot check never ran, and an empty starting slot produces exactly the same empty list
   as a healthy roster. Same for a stale cached roster, a derived week, or a slot id ESPN
   renamed. So `CheckResult` carries `blind_spots`, and `all_clear` requires **both** no
   findings and nothing that stopped us looking — giving `problems` / `unverified` /
   `all_clear`, which map straight onto what a notifier should do.

2. **`pre_draft`, found by running it for real.** On 2026-09-03, four days before the draft,
   the first live run produced **nine** confident "claim someone by Friday" findings — every
   starting slot was legitimately empty because the draft had not happened. ESPN publishes
   `draftDetail.drafted`; the checks now skip when it is `False`. It is tested with `is False`
   rather than a truthiness check: an absent field is `None`, and treating absence as
   "not drafted" would mute every alert for a season the first time ESPN renamed the field.

3. **No `--dry-run` flag.** The plan named one, but nothing is delivered or written yet, so
   there is nothing for it to suppress — a flag that suppresses nothing is the same broken
   promise as `FixKind.FREE_AGENT_ADD` (D-046). It arrives with D1, when there is a send to
   skip. `--now` carries the offline-testing weight instead, and refuses a naive instant
   rather than reading it as UTC and shifting every deadline by hours.

**Exit codes**, because a check runs unattended long before anyone reads its output:
`0` all clear · `1` could not run · `2` problems you can still act on · `3` nothing actionable,
but this run was not a clean look.

**Deliberately not in C7:** the Week page. It consumes `CheckResult` (F1) and belongs to Stage F.
Building the object first is the part of the review's resequencing the evidence supports.
