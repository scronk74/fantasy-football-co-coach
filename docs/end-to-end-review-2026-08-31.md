# End-to-end product, code, and UI review

**Reviewed:** 2026-08-31

**Repository state:** `main` at `8f26711`

**Scope:** read-only review of the plan, specifications, implementation, tests, fixture-driven UI, reliability model, security posture, and season roadmap

## Executive summary

This is a better engineering foundation than most personal projects at the same stage. The pure model/advisor boundary is real, the tests are fast and deterministic, secrets are kept out of the repository, the browser code has a sensible compute/DOM split, and the current desktop UI is restrained and readable. Both test suites pass: **295 Python tests and 38 JavaScript tests**.

It is not yet a usable co-coach. The code can detect several lineup problems in tests, but no production command calls the lineup advisor, nothing sends a reminder, and the current pages do not show the findings. More importantly, three trust failures should be corrected before notification work amplifies them:

1. **Fix the source/cache contract first.** Every source discards stale provenance, both report paths label stale fallback as fresh, and a malformed HTTP 200 can overwrite the last known-good cache before validation.
2. **Add one end-to-end `check` slice next.** A fixture-capable `ffcoach check --dry-run` should compose league data, freshness, week, schedule, deadlines, user-team selection, and findings into one `CheckResult` consumed by the Week page, notifier, and log.
3. **Model whether a fix is actually possible, then schedule around that deadline.** The current deadline clamp can turn an impossible post-lock waiver into a plausible kickoff deadline. Repeats, polling, and reminders must follow the last viable action—not merely kickoff—and need an out-of-band safety net because the scheduler and proposed dead-man switch share one sleeping iMac.

The product strategy should also become more personal and less platform-like. Build a thin, visible safety loop, not eleven backend steps in a row. Ship ntfy only, demote general onboarding and extra channels, surface a quiet “checked and clear” receipt, and pull one fact-backed copy/paste joke into the first dashboard. Advice can follow as transparent two-source consensus; accuracy weighting and a third projection source are unnecessary until real evidence says otherwise.

## Verdict

**Keep the architecture’s core idea; change the next build sequence.**

- Keep deterministic Python facts, structured findings, injected clocks, fixture-first tests, ESPN-only scope, and the rule that projection advice never interrupts by default.
- Fix freshness and action viability before adding delivery.
- Build vertically: `check result → Week page → ntfy → log/dedupe → scheduler`, using the same structured object throughout.
- Treat “I know the check succeeded and my lineup is clean” as a product feature, not absence of an alert.
- Bring low-risk fun forward. A personal co-coach that only appears when something is wrong becomes a nag.

## What was verified

| Check | Result |
|---|---|
| `uv sync` | Passed with a workspace-safe uv cache |
| `uv run pytest` | **295 passed** in 1.35s |
| `npm test` | **38 passed** |
| `ffcoach league --fixture tests/fixtures/espn_league.json` | Wrote two teams and resolved Week 5 from ESPN fixture data |
| `ffcoach build` with the example league shape | Wrote 271 draft rows; reported 27 unmatched and 2 fuzzy matches |
| `ffcoach doctor` without `league.yaml` | Exits with the missing-config error; broader diagnostics are planned but not implemented |
| Desktop UI | Draft and league pages rendered without console warnings/errors at 1280×800 |
| Phone UI | Both pages exercised at 390×844; draft table overflow confirmed |
| Malformed ESPN shapes | Uncaught `AttributeError`/`ValueError` confirmed |
| Schedule row with game but missing time | Confirmed that the team is incorrectly classified as on bye |

The fixture is hand-written and no live private ESPN response was available. This review therefore makes no claim that ESPN field names match the real league.

## Priority definitions

- **P0:** fix before building notification delivery or relying on the tool during the season.
- **P1:** fix before calling the first personal-use MVP dependable.
- **P2:** important, but can follow the first end-to-end safety slice.

## Prioritized findings

### P0 · Stale fallback is presented as fresh, and invalid responses can poison the last good cache

**Status:** Confirmed.

**Evidence:** [`espn_client.py:49-52,69-78`](../src/ffcoach/leagues/espn_client.py#L49-L78), [`ffcalc.py:38-60`](../src/ffcoach/sources/ffcalc.py#L38-L60), [`sleeper.py:28-49`](../src/ffcoach/sources/sleeper.py#L28-L49), [`schedule.py:108-130`](../src/ffcoach/sources/schedule.py#L108-L130), [`crosswalk.py:167-188`](../src/ffcoach/sources/crosswalk.py#L167-L188), and [`cli.py:121-125,195-200`](../src/ffcoach/cli.py#L121-L125).

Every source calls `Cache.get_stale()` and throws away the returned age. Both CLI report paths then pass `stale_seconds=None` unconditionally. An expired cached response returned during an outage gets a new `generated_at` timestamp and `stale: false`.

The fetch/parse split contains a second failure: raw HTTP 200 content is cached before its parser validates it. A login page, truncated JSON, or schema-error document can overwrite the last valid entry; parsing then fails, and the cache no longer has a known-good fallback.

**Failure scenario:** Sunday morning ESPN returns 500. The cache contains Friday’s roster, before an OUT player was benched. The tool serves Friday’s roster, writes a current generation timestamp, and labels it fresh. The page or future notifier can confidently repeat obsolete advice. If ESPN instead returns a 200 login document, that document replaces the good roster before parsing fails.

**Recommendation:** replace raw-string fetch results with a typed `SourceResult[T]` carrying parsed data, source timestamp, stale age, and fallback error. Validate before replacing the last-known-good cache. Preserve freshness per source; one global stale boolean is not enough for the Week page or health panel.

**Tests to add:** expired valid cache + HTTP failure, malformed HTTP 200 preserving the previous entry, mixed fresh/stale sources, and an assertion that `generated_at` is not source freshness.

### P0 · The deadline model can describe an impossible transaction as an actionable fix

**Status:** Confirmed; existing tests currently bless the wrong behavior.

**Evidence:** [`deadlines.py:72-104`](../src/ffcoach/model/deadlines.py#L72-L104), [`lineup.py:211-212,303-325,360-362`](../src/ffcoach/advisors/lineup.py#L211-L212), [`test_deadlines.py:106-129`](../tests/test_deadlines.py#L106-L129), and [`test_lineup_advisor.py:278-283,489-494`](../tests/test_lineup_advisor.py#L278-L283).

When no bench replacement exists and the next waiver processing time is after lineup lock, `fix_deadline()` returns `min(waiver_deadline, lock)`. That satisfies “never after lock” numerically but does not make the waiver process before lock. The returned pair still says `needs_waiver=True`, creating a plausible time for an impossible fix.

Bye and empty-slot findings have no per-player kickoff, so they are also considered unlocked forever—even on January 1 for an old regular-season week. `actionable()` checks only `locked`, not whether a viable fix and an unexpired effective deadline exist.

**Failure scenario:** Thursday at 10:00, a Thursday-night starter is OUT, there is no bench replacement, and waivers next process Friday. The system returns Thursday kickoff as a waiver deadline. A message can tell the user to “claim someone by 8:15” even though the claimed player cannot arrive until Friday.

**Recommendation:** replace `(deadline, needs_waiver)` with an explicit fix plan such as `BENCH_SWAP`, `FREE_AGENT_ADD`, `WAIVER_CLAIM`, `NO_REMAINING_FIX`, or `UNKNOWN`. Carry both the transaction deadline and scoring-period/slot boundary. A finding is actionable only when its fix is viable and `now` precedes the effective deadline.

This preserves **D-014**’s correct principle while overturning the claim that clamping alone solves it. Amend **D-019** so both strikes are relative to the viable action deadline, not automatically kickoff.

### P0 · Stage C’s completed advisor has no production execution path

**Status:** Confirmed.

**Evidence:** [`cli.py:88-136`](../src/ffcoach/cli.py#L88-L136); `find_problems()` appears nowhere else under `src/` outside its definition in [`lineup.py:258`](../src/ffcoach/advisors/lineup.py#L258).

`ffcoach league` parses ESPN, resolves the week, and writes a roster payload. It does not load the schedule when ESPN supplies a valid week, calculate the waiver deadline, select exactly one user team, or call the lineup advisor.

**Failure scenario:** `ffcoach league --fixture tests/fixtures/espn_league.json` succeeds and writes the team page, but produces no lineup findings even though the same fixture supports several advisor findings in tests. There is currently nothing for a notifier to send.

This is not merely “notifications are not implemented.” The roadmap has no explicit application-composition step between detection and delivery. Implementing `Notifier` next risks hiding orchestration inside a delivery module.

**Recommendation:** add an application service and `ffcoach check --fixture ... --now ... --dry-run`. It should emit one structured `CheckResult` containing source health, week provenance, team selection, findings, fix plans, last viable deadlines, next check, and an all-clear state. Notification, logging, and `week.html` should consume this exact object.

### P0 · The proposed scheduler and dead-man switch share the same failure domain

**Status:** Confirmed design flaw; actual sleep duration and wake behavior remain operational assumptions until tested on the target iMac.

**Evidence:** the iMac sleeps in [`in-season-alerting-design.md:44-52`](superpowers/specs/2026-08-29-in-season-alerting-design.md#L44-L52); scheduling and heartbeat are specified in [`in-season-alerting-design.md:285-325`](superpowers/specs/2026-08-29-in-season-alerting-design.md#L285-L325); **D-022/D-023** are recorded in [`ROADMAP.md`](../ROADMAP.md).

The machine is scheduler, checker, monitor, and messenger. A process on that machine cannot warn while the machine itself is asleep or off. Running a missed job on wake is useful only if wake still precedes the action deadline.

**Failure scenario:** the iMac sleeps Saturday night and wakes at 1:15 PM Sunday. The 11:30 inactives sweep and local heartbeat both slept. On wake, the lineup check is accurate but useless because the 1:00 players are locked.

**Recommendation:** keep `launchd` but replace dynamic per-window jobs with one frequent, idempotent poller; tested application code decides what is due. Add `doctor` checks for sleep/power configuration and an `.ics` calendar safety net for the phone. A true dead-man must live outside the iMac; otherwise state honestly that monitoring is best-effort. A free external heartbeat endpoint can receive a non-sensitive “check succeeded” ping without receiving ESPN credentials or roster data.

### P1 · ESPN contract failures can crash or silently convert unknown data into normal-looking roster facts

**Status:** Confirmed against mutated fixture inputs; live ESPN field compatibility remains unverified.

**Evidence:** [`espn.py:86-116,121-150,172-220`](../src/ffcoach/leagues/espn.py#L86-L116) and [`cli.py:109-113`](../src/ffcoach/cli.py#L109-L113).

Only JSON syntax errors become `EspnUnavailable`. Valid JSON with the wrong shape or scalar type escapes as ordinary exceptions. Confirmed cases include top-level `[]`, `settings: []`, and `wins: "oops"`. A waiver hour of 25 parses and fails later when constructing a datetime.

Unknown critical identifiers are more dangerous than a crash. An unknown lineup slot defaults to `BN`; an unknown team defaults to `FA`. The advisor can then ignore a real starter or claim an unplaceable bench player “plays this week.”

**Failure scenario:** ESPN renames or omits `lineupSlotId` for one entry. That starter becomes bench data at parse time, so the advisor never evaluates him. The run succeeds with false silence—the worst failure mode for this product.

**Recommendation:** validate top-level and critical nested shapes at the adapter boundary. Convert contract failures to `EspnUnavailable` with JSON-path-like locations. Unknown slot/team values must stay explicit `UNKNOWN`, generate a diagnostic, and suppress affected advice rather than map to plausible defaults. Add table-driven mutation tests.

### P1 · Missing kickoff time is silently reinterpreted as a bye

**Status:** Confirmed with a three-row schedule input.

**Evidence:** [`schedule.py:80-98,150-166`](../src/ffcoach/sources/schedule.py#L80-L98).

Rows with an absent or invalid kickoff are dropped. `Schedule.is_on_bye()` then defines a team/week without a stored game as a bye.

**Failure scenario:** the feed contains KC vs DEN in Week 2 but its time is blank because scheduling is TBD. The parser drops the game, and `is_on_bye("KC", 2)` returns `True`. A data-quality problem becomes a fact-only, interrupt-tier false alert.

**Recommendation:** model game existence separately from known kickoff. A row with teams and week proves “playing,” while its lock time may remain unknown. Validate duplicate team/week entries, team coverage, season coverage, and required columns. Prefer a tri-state `playing / bye / unknown`; missing data must never become a confident bye.

### P1 · Replacement suggestions are individually valid but not jointly feasible

**Status:** Confirmed; this also confirms two suspicions already listed in `CODEX_README.md`.

**Evidence:** [`lineup.py:123-139,291-310`](../src/ffcoach/advisors/lineup.py#L123-L139) and [`base.py:14,31-39`](../src/ffcoach/leagues/base.py#L14-L39).

`find_replacements()` runs independently for each broken slot. It does not reserve a candidate, so two findings can both recommend the same bench player. It also considers every non-starter, including IR, a direct candidate.

**Failure scenario:** two starting WRs are OUT and one healthy bench WR exists. Both action cards name that WR. Acting on one leaves the other guaranteed zero. A healthy player parked in IR is likewise presented as directly startable even though activation—and perhaps a roster drop—comes first.

**Recommendation:** keep fact detection separate from action planning. Run a deterministic roster-level matching pass across broken slots and available `BN` players. Unmatched slots become add/waiver needs. Treat IR activation as a prerequisite action with its own roster-capacity implications.

### P1 · The current league page drops injury information it already has

**Status:** Confirmed in source and rendered fixture UI.

**Evidence:** ESPN parsing preserves status in [`espn.py:86-97`](../src/ffcoach/leagues/espn.py#L86-L97), and the fixture contains `QUESTIONABLE` and `INJURY_RESERVE` at [`espn_league.json:95-101,128-134`](../tests/fixtures/espn_league.json#L95-L101). The report contract omits it in [`report/build.py:79-87`](../src/ffcoach/report/build.py#L79-L87), and [`league_render.js:7-14`](../web/league_render.js#L7-L14) has no status cell/badge.

**Failure scenario:** Amon-Ra St. Brown is QUESTIONABLE in the fixture, but the rendered My League page shows no designation. Hurt Guy's `IR` lineup slot remains visible, so IR can be inferred in that case, but the detailed status field is still dropped. A user opening the page to understand the team at a glance receives no hint about a questionable starter.

**Recommendation:** thread `injury_status` through the JSON contract and render a textual status badge with more than color alone. This does not replace the Week action queue; it makes the already-shipped roster page tell the truth it already knows.

### P1 · The desktop UI is clean, but the draft page is not phone-safe or fully keyboard/screen-reader safe

**Status:** Confirmed through browser testing and source inspection.

**Evidence:** the stylesheet ends without a responsive table strategy at [`style.css:48-93`](../web/style.css#L48-L93), while dark-mode colors are defined at [`style.css:7-13`](../web/style.css#L7-L13). At a 390px viewport, the document was 510–511px wide and the 491px table clipped `Value` and `Available at next pick`. Marking a player rebuilds the entire table with `innerHTML` at [`main.js:25-30`](../web/main.js#L25-L30), losing keyboard focus. The toggled button’s label remains “Mark … drafted” after it becomes an undo action at [`render.js:77-80`](../web/render.js#L77-L80). Position chips have visual state but no `aria-pressed` at [`main.js:38-41`](../web/main.js#L38-L41). Stored JSON is parsed outside the load error boundary at [`main.js:9-16`](../web/main.js#L9-L16).

The touch targets are also too small for a hurried phone interaction: the mark button measured about 26×18.5px and the chips about 31px high. Dark mode brightens position backgrounds but keeps white text. Verified contrast ratios were 2.72:1 for QB, 1.74:1 for RB, 2.14:1 for WR, 1.67:1 for TE, and 2.54:1 for K/DEF—well below 4.5:1 for this small text. Applying `.drafted { opacity: .35 }` to the whole row also dims the undo control, not just secondary information.

**Failure scenario:** on an iPhone-sized screen, the actionable availability column is off-screen with no cue that the table scrolls. A keyboard user marks a player and focus jumps to the page body. A screen reader continues to announce the undo button as “Mark … drafted.” Bright dark-mode badges are hard to read, touch targets are easy to miss, and corrupted legacy localStorage can stop all page initialization before the friendly data-load error runs.

**Recommendation:** for the draft page, use a clearly scrollable wrapper with sticky identity/action columns or switch rows to compact cards below a breakpoint. Use at least 44px touch targets. Preserve focus across re-render, make button labels describe the next action, add `aria-pressed` to chips, use `aria-live` for updated best/status text, and safely parse/version local storage. In dark mode, use dark text on the bright badge colors and dim secondary text rather than entire interactive rows. Apply these rules to the planned Week page from its first mockup rather than retrofitting later.

### P1 · The roadmap is organized as a backend waterfall instead of a usable safety loop

**Status:** Confirmed plan conflict.

**Evidence:** the spec says `week.html` should be built UI-first in [`in-season-alerting-design.md:360-378`](superpowers/specs/2026-08-29-in-season-alerting-design.md#L360-L378), then says Phase 1 has no UI and the dashboard is Phase 5 in [`in-season-alerting-design.md:457-478`](superpowers/specs/2026-08-29-in-season-alerting-design.md#L457-L478). The roadmap puts all of D and E before F in [`ROADMAP.md`](../ROADMAP.md).

**Failure scenario:** every notification and scheduling abstraction is implemented before the first realistic action card is reviewed. The Week UI then exposes that freshness, multiple replacements, impossible fixes, or clean-state proof do not fit the result schema, forcing rework across delivery and history after eleven steps.

**Recommendation:** make the next slice `F0 → fixture-backed F1 → CheckResult/dry-run → D1/D2 ntfy → E1 logging`. Then add dedupe/repeats, scheduling, and controls around a user-validated result. **D-027 is right that the action queue is the primary object; this review additionally recommends ordering it by the last viable deadline.** The sequence around it is wrong.

Split the first dashboard promise as well. F1 depends only on C4/F0 in the roadmap, but the approved mockup promises projected matchup score and projected swing while G1/G2 projections come later. Ship F1 first with objective actions, deadlines, freshness, and system health; add matchup projections only after the projection contract is trustworthy. Do not quietly insert single-source projections to make the mockup look complete.

### P1 · Projection weighting and advice gating are overbuilt for a one-user tool

**Status:** Confirmed planning inconsistency; usefulness of two-source advice remains a season experiment.

**Evidence:** the design requires three weighted sources at [`in-season-alerting-design.md:54-77`](superpowers/specs/2026-08-29-in-season-alerting-design.md#L54-L77), while **D-043** now says ship two. The decision log needed to learn weights is described after the weighting premise at [`in-season-alerting-design.md:398-413`](superpowers/specs/2026-08-29-in-season-alerting-design.md#L398-L413). G2 precedes G3 in the roadmap.

**Failure scenario:** Week 1 has ESPN and Sleeper projections but no local accuracy history. “Accuracy-weighted” either means invented weights, secretly equal weights, or a blocked feature. A small number of volatile outcomes can then overfit a single personal league.

**Recommendation:** overturn the initial weighting portion of **D-030**. Ship a simple two-source consensus with visible disagreement and start the decision log immediately. Preserve **D-032**’s “never interrupt by default,” but loosen its all-or-nothing gate: unanimous, above-threshold advice may appear in the page/digest; disagreement should say “review,” not “do this.” Consider weights only after a documented minimum sample, separated at least by position.

### P2 · The draft board’s “Value” signal is not an independent ranking

**Status:** Confirmed; lower season priority because the in-season spec now puts the draft out of scope.

**Evidence:** [`draft.py:62-85`](../src/ffcoach/advisors/draft.py#L62-L85) sorts by ADP, assigns “our rank” from that same list index, then defines value as `ADP - rank`. The design describes rank as independent in [`2026-08-20 design:205-210`](superpowers/specs/2026-08-20-fantasy-football-co-coach-design.md#L205-L210).

There is no independent ranking model. The index diverges from ADP mainly because ADP contains gaps and the returned player pool extends beyond normal draft depth. In the live review build, Washington Defense had ADP 195.9, row rank 271, value -75.1, and the UI called it an early pick before any draft state could establish that conclusion.

**Failure scenario:** a late player is labeled a massive “reach” solely because 270 API rows precede him while ADP is an average pick number on a different scale. Marking drafted players does not recompute the stored rank/value, so the reason “would be an early pick” is not evidence of current draft value.

**Recommendation:** either supply a real independent ranking/roster-construction model or remove “Bargain/Fair/Reach” and call the column what it is. Because the new product goal is in-season safety, freeze draft enhancements after correcting or removing the misleading signal.

### P2 · Security is appropriate for a personal tool, with a few boundaries to enforce before `serve`

**Status:** Confirmed posture; no committed real credentials found.

Good choices already present: credentials are separate from league config; `espn.yaml`, generated web data, SQLite state, and `.venv` are ignored; cookies are not logged; HTTPS is used; and 401/403 has a distinct exception.

Before `ffcoach serve` and config-writing controls:

- Have `doctor` warn if [`espn.yaml` permissions](../src/ffcoach/config.py#L62-L87) allow group/other access; creation should use user-only permissions.
- Bind only to loopback. Do not expose ESPN cookies through any browser endpoint.
- Use POST plus Origin/CSRF validation for config mutations.
- Give generated roster JSON and SQLite state user-only permissions where practical; they contain private league/owner data even though they are not credentials.
- Validate how ESPN actually represents an expired session. A 200 login/error page may not reach the current 401/403 classification.

## Architecture assessment

### What is right

- The `sources → model → advisors → report` direction is mostly real.
- `model/` is pure, time is injected, and immutable data records make difficult deadline behavior testable.
- Structured facts separated from generated coaching language is the right cost and trust boundary.
- The browser compute/DOM split is holding. Rendering/filtering functions are testable, DOM wiring is small, and user-supplied strings are escaped.
- Keeping ESPN auth failures distinct is correct; stale roster data cannot repair expired credentials.
- One `PAGES` list for navigation is proportionate and effective.

### What needs a new boundary

The canonical source template is the weakest architecture. It combines fetch and cache mutation but returns only raw text, so it cannot represent freshness or validate before commit. Fix that template before copying it into projection sources.

The missing architectural object is an application-level `CheckResult`. Today the system jumps from source-specific fetching to page-specific report writing while the most important advisor is orphaned. `CheckResult` should be the stable contract shared by notification rendering, history, and the Week page.

`LineupFinding.reason` currently embeds wording inside the advisor even though the design says wording belongs at the edge. This is not a current correctness defect, but D2 is the moment to pick one rule: either structured reason codes/arguments rendered per channel, or advisor-owned prose—not both.

## Product-gap analysis

| Season need | Current state | Planned state | Opinionated recommendation |
|---|---|---|---|
| Draft assistance | Usable board, but misleading Value model | Considered complete | Correct/remove Value, then freeze it. The in-season product is more important. |
| Weekly lineup integrity | Strong fixture-tested library logic | D/E notifications, F dashboard | Add `check` composition now; code unused by an application is not “done.” |
| Empty/bye/OUT reminders | Detection exists | Interrupt tier | Preserve fact-only urgency after fixing freshness, unknowns, and fix viability. |
| Sunday inactive | Not built | E6 | Ship before projection advice; force-refresh every uncertain unlocked starter, including QUESTIONABLE and DOUBTFUL, and fail safely on unknown statuses. |
| Proof the system checked | None | Dashboard clean state + heartbeat | Add visible/silent “checked and clear,” including freshness and next lock. |
| Sleep/offline/auth failure | Auth exception exists | Same-host launchd + heartbeat | Verify power state, add phone calendar fallback, and move true heartbeat off-host. |
| Waiver deadline | Parser/model exists but fix semantics are incomplete | H3 advice on Hold | Separate reminders from advice. Deadline reminders are MVP; recommendations can wait. |
| Add/drop feasibility | `needs_waiver` boolean | Drop candidate X-3 | Model free agent vs waiver vs no viable fix; require drop candidate when advice begins. |
| Start/sit advice | None | G1–G4 | Two-source consensus in dashboard/digest first; no interrupt and no premature weights. |
| Trade deadline | X-2 backlog | No dated stage | Promote to season-critical reminder. It requires no projection model. |
| Pending trade offer | Mentioned in the original notification design, but no detection step | No clear roadmap owner | Inventory ESPN support; if available, alert on unread/expiring offers so “did not notice it” cannot be the failure mode. |
| Trade help | None | X-4/H4 | Start with side-by-side comparison and positional needs, not an authoritative “winner.” |
| IR management | None | X-1 backlog | Promote before heavy bye weeks; current replacement logic must stop treating IR as bench. |
| Playoff/Week 18 risk | None | H2 | Date-gate it before fantasy playoffs rather than leaving it at the roadmap tail. |
| Fun/smack talk | None | H1 late | Put one fact-backed, copyable line in the first Week page/digest. |
| Recommendation trust | Reasons and provenance concepts exist | Decision log | Show source freshness and disagreement; measure before weighting. |
| General onboarding | Manual YAML, minimal doctor | `ffcoach init` V1 | Demote for a personal project. Harden `doctor`; manual YAML is enough for one operator. |

## Recommended personal-use MVP

The MVP definition should be:

> Before every meaningful deadline, I either receive a correct action or can see a recent all-clear. If the system could not check, I learn that independently of the failed machine.

### Include

- Real-league ESPN verification and a scrubbed, structurally real fixture as soon as access exists.
- Validated source results with per-source freshness and last-known-good fallback.
- Explicit fix viability rather than `deadline + needs_waiver` alone.
- `ffcoach check --dry-run` and one `CheckResult` shared by page, notifier, and log.
- `ffcoach serve` bound to loopback, with a Week page showing:
  - actions ordered by last viable deadline;
  - exact reason and legal fix;
  - last successful check and source ages;
  - next lock and next scheduled check;
  - a first-class all-clear state.
- ntfy only, with interrupt and silent/digest priorities.
- Run logging, minimal history for deduplication, and first-run flood protection.
- One frequent idempotent `launchd` poller plus an inactives sweep that force-refreshes all uncertain unlocked starters, including QUESTIONABLE and DOUBTFUL.
- Sleep/power checks in `doctor`, a phone `.ics` fallback, and an external non-sensitive heartbeat if “never miss” is meant literally.
- Minimal config controls: global mute, interrupt enabled, digest enabled, and thresholds. A full config-writing UI can follow.
- One fact-backed, copy/paste-ready joke with a `Dad joke / Mild / Spicy / Self-roast` tone preference.

### Exclude for now

- SMS and email adapters.
- A global 160-character budget; keep that constraint inside a future SMS renderer only.
- General-purpose interactive onboarding.
- Projection accuracy weighting and a third projection source.
- Automated lineup changes.
- Full trade/waiver intelligence.
- Multi-league support and publishable-product polish.

## Recommended phased roadmap

### Phase 0 · Repair truth and expose it

1. Fix source validation/freshness and schedule/ESPN unknown handling.
2. Fix action viability and joint replacement planning.
3. Add fixture-capable `CheckResult` composition and `ffcoach check --dry-run`.
4. Build `ffcoach serve` and the Week action queue from the same fixture.
5. Show freshness, last check, next deadline, and all-clear state.

### Phase 1 · Dependable reminders

1. Add ntfy and channel-specific concise rendering.
2. Add logging, dedupe, first-run summary, and deadline-relative repeats.
3. Install one idempotent polling job rather than dynamic per-window jobs.
4. Add the inactives sweep with a forced-fresh path for every uncertain unlocked starter, including QUESTIONABLE and DOUBTFUL; unknown future statuses must not be treated as healthy.
5. Add sleep checks, phone calendar safety net, and external heartbeat if desired.
6. Add minimal notification controls.

### Phase 2 · Fun and seasonal safety

1. Tuesday digest and one factual copy/paste banter card.
2. IR activation/roster-space prompts.
3. Trade-deadline and waiver-deadline reminders.
4. Alert history.
5. Date-gated playoff and Week 18/resting-risk behavior.

Suggested no-new-source lines:

- “Lineup checked, all starters eligible. Competence is a streak now.”
- “I successfully noticed the giant BYE label before kickoff. Growth.”
- “My lineup briefly embraced minimalism. The vacancy has been filled.”
- “Roster legal. Excuses preloaded. Let’s play.”
- “The record says contender. The points-against column says blessed.”

Keep **D-034** firm: roast decisions and outcomes, never people. Deterministic facts choose the template; wording must not invent a claim.

### Phase 3 · Transparent start/sit advice

1. Resolve Q-2 and represent the league's real scoring rules when custom scoring requires it.
2. Add ESPN and Sleeper projections normalized to the same league scoring contract.
3. Start with equal/simple consensus and visible source disagreement.
4. Record recommendation, user decision, and outcome from day one.
5. Show bench-upgrade cards in the dashboard/digest only.
6. Keep interrupts off by default; experiment with weights only after sufficient evidence.

### Phase 4 · Trade and waiver decisions

1. Side-by-side player comparison.
2. Positional surplus/need across league rosters using already-available roster data.
3. Trade-target shortlist clearly labeled as advisory.
4. Waiver recommendations that always name the required drop candidate.
5. Claude coaching language over compact structured facts for nuance and fun.

### Phase 5 · Optional polish

- Full notification-control UI.
- Additional delivery channels.
- Third projection model and evidence-based weighting experiments.
- General onboarding/portability.
- Vegas context only if the in-season endpoint proves useful.

## Decision-log changes recommended

| Decision | Recommendation |
|---|---|
| **D-014** action deadline | Keep the principle; replace the clamp implementation with explicit fix viability. |
| **D-017** 160-character rendering | Scope it to a future SMS renderer. Ntfy must remain concise but can carry the full required action. |
| **D-019** two strikes | Change the second strike from “90m before kickoff” to “before the last viable action deadline.” Never interrupt after the fix is impossible. |
| **D-022** launchd | Keep launchd, but prefer one frequent idempotent poller over dynamic per-window jobs. |
| **D-023** dead-man | Acknowledge same-host monitoring cannot detect the host being asleep/off in time; add an external heartbeat or call it best-effort. |
| **D-025** clonable by someone else | Demote from personal-use MVP. Keep secrets safe and harden `doctor`; defer general onboarding. |
| **D-027** action queue | Keep and move earlier. Order by the last viable deadline, not generic severity alone. |
| **D-030** accuracy weighting | Overturn for initial delivery. Start with transparent two-source consensus and measure before weighting. |
| **D-032** bench-upgrade gate | Keep “never interrupt by default”; allow clearly labeled dashboard/digest advice after two-source agreement. |
| **D-033/D-034** banter | Keep the fact/presentation split and safety boundary; pull one small fun slice into the first Week page. |
| **D-040** local server | Keep, bind loopback only, and make it part of the next vertical slice. |

## Test strategy: next highest-value coverage

The suite does not primarily need a percentage target. It needs contract mutation and application-composition tests:

1. End-to-end fixture `check` result, including exactly one user team.
2. Stale provenance preserved through CLI/report/UI.
3. Invalid HTTP 200 cannot replace the last-known-good cache.
4. ESPN null/list/string/wrong-number mutations at critical paths.
5. Unknown ESPN slot/team IDs become diagnostics, never BN/FA facts.
6. Schedule game with unknown time is `playing + lock unknown`, not bye.
7. Truncated/duplicate schedule produces unknown or a validation failure.
8. Waiver processing after lock produces `NO_REMAINING_FIX`.
9. Bye/empty findings after the scoring-period boundary are not actionable.
10. Two broken slots and one bench replacement produce one assignment and one uncovered problem.
11. IR activation is not a direct bench swap.
12. Mobile browser checks for no unexplained horizontal clipping, correct toggle state, focus preservation, and live status announcements.

## UI assessment

### What works

- The desktop hierarchy is calm and readable in dark mode.
- Navigation, headings, tables, and labels are structurally sensible.
- The draft page explains what action to take and updates best available immediately.
- The league cards read well on both desktop and phone widths.
- Escaping is covered by JavaScript tests.
- There were no browser console warnings or errors in the successful fixture runs.

### What should shape the Week page

- Do not reproduce the wide draft table. Use narrow, responsive action cards so the localhost page works in a small window and the same presentation can support a future standalone export. The notification—not the loopback-only page—must be phone-first and self-sufficient.
- Put source age, last successful check, and next lock beside the page title—not in a hidden health panel only.
- Make the all-clear state positive evidence: “Checked 11:28 · 9/9 starters eligible · ESPN 2m old · next lock 1:00.”
- Give each action one primary verb: `Swap`, `Claim`, `Activate IR`, `Review`, or `Too late`; never make the user infer transaction type from prose.
- Keep reasons inline and make source disagreement visible for advice.
- Preview the exact notification text on the same card so page and phone cannot drift.
- Include one copy button for banter; this is a family-league tool, not an operations console.

### Fixture limitation worth fixing

Fixture mode sets `my_swid=None` in [`cli.py:88-108`](../src/ffcoach/cli.py#L88-L108), so the generated My League page has no `.mine` card while its instructions promise “Your team is pinned to the top.” In the review run, “Disasters” appeared first alphabetically and “Dynasty” second. Add a fixture-only `--my-team-id`/`--my-swid` option or mark one fixture team so the documented demo exercises its central UI promise.

## Confirmed facts versus assumptions

### Confirmed

- The project is one-user, one-ESPN-league, local, and not intended for sale.
- Stage C has substantial fixture-tested logic but no production caller.
- No notifier, scheduler, Week dashboard, or projection source exists yet.
- Stale age is discarded and report payloads force `stale_seconds=None`.
- Invalid-but-shaped external data is not consistently validated before cache mutation.
- The deadline clamp and forever-actionable bye/empty behavior are encoded in tests.
- The current league payload omits injury status.
- The draft page horizontally overflows a 390px viewport.
- The internal league model has cumulative teams/records/rosters/settings but no pending-trade or matchup-history model.
- No committed production secrets were found.

### Assumptions requiring real-world validation

- The live private ESPN response matches enough of the fixture contract to operate.
- The target league uses only the currently supported roster slots and known lock/waiver shapes.
- The iMac may sleep through a deadline; its actual power schedule is not yet measured.
- ntfy delivery and priority behavior are reliable enough on the user’s iPhone.
- ESPN roster injury status updates quickly enough for the inactives sweep; the sweep should be verified live and force freshness.
- Trade deadline, pending transactions, matchup results, scoring rules, and playoff fields are available in fetchable ESPN views.
- ESPN and Sleeper agree often enough for useful, non-interrupt start/sit guidance.
- “Mild” is the right default banter level; this is a preference to confirm, not an engineering fact.

## Ten highest-value next actions

1. **Resolve R-1:** capture a real ESPN response, scrub it, replace/augment the fixture, and document unsupported league settings.
2. **Repair the source template:** validate before cache commit and carry per-source freshness/error metadata.
3. **Replace deadline booleans with fix viability:** distinguish swap, activation, free-agent add, waiver, impossible, and unknown.
4. **Add roster-level replacement planning:** reserve candidates and treat IR as a prerequisite, not a bench swap.
5. **Create `CheckResult` and `ffcoach check --dry-run`:** prove the entire safety decision offline with a fixture.
6. **Build the compact, responsive Week action queue now:** include all-clear, freshness, last check, next lock, and an exact preview of the phone-first notification.
7. **Ship ntfy + structured run log + dedupe as one vertical slice:** no extra channels yet.
8. **Install one frequent idempotent poller and test the actual iMac:** add a forced-fresh sweep for all uncertain unlocked starters, sleep diagnostics, calendar fallback, and external heartbeat if required.
9. **Promote seasonal and fun work:** recurring waiver-review/deadline reminders, trade-deadline reminder, pending-offer detection if ESPN supports it, IR prompt, Tuesday digest, and one fact-backed copy/paste joke before projection sophistication.
10. **Add transparent two-source advice:** first resolve league scoring and normalize both sources, then show consensus/disagreement, start the decision log immediately, and use no interrupt or weighting until evidence earns it.

## Final assessment

The project is pointed in the right direction, but “13 of 40 steps complete” overstates user value because the completed lineup detection is not composed into anything the user can run or see. The next milestone should not be “notification interfaces exist.” It should be:

> I can run one check, see exactly what must be done before which deadline, receive that same answer on my phone, and prove the data and check were fresh—even when the answer is “nothing is wrong.”

Once that loop survives real ESPN data and two actual weekends, add the fun. In practice, pull a small piece of fun into the loop immediately so there is a reason to enjoy opening it before something breaks.
