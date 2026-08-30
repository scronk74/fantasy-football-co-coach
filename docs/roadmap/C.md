# Stage C — Lineup detection

> Task-level detail for the imminent stage. Steps and status live in [`ROADMAP.md`](../../ROADMAP.md) §3.3.
> Later stages stay at Step level until work approaches them (progressive elaboration).

**Stage goal:** the advisor correctly identifies every starter who cannot score this week, knows which
week it is, and knows the real deadline for fixing each problem.

Gated by [R-1](../../ROADMAP.md#7-roadblocks) for live verification, but **all of it is buildable and
testable against fixtures today.**

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

## C5 — Read the lineup-lock setting · Backlog

Some ESPN leagues lock **all** lineups at the week's first game rather than per player. Under that
rule, per-player timing is actively wrong — a Sunday alert about a Monday-night starter is pointless
because he locked Thursday.

- [ ] **C5.1** — ~~Find the field~~ **Found while building C2**: `rosterSettings.lineupLocktimeType`,
      which returned `"INDIVIDUAL_GAME"` on the live public league. (An earlier note named
      `lineupLockTimeOffset` — that field returned `None` and is *not* the right one.) The
      weekly-lock value is still unknown; R-1 or another public league would confirm it.
- [ ] **C5.2** — Model it as an enum: per-player vs weekly lock.
- [ ] **C5.3** — When weekly, collapse all deadlines to the week's first kickoff.
- [ ] **C5.4** — Default to per-player and **log the assumption** when the setting is absent.

**Depends on R-1** for real confirmation of the field's semantics.
