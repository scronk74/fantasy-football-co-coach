import { test } from "node:test";
import assert from "node:assert/strict";
import {
  actionable,
  blindSpotsHtml,
  deadlinesHtml,
  findingHtml,
  headline,
  ordered,
  sourcesText,
  statusBadge,
  weekHtml,
} from "./week.js";

const SUNDAY = "2025-10-05T17:00:00+00:00";

const F = (over = {}) => ({
  kind: "out",
  player_name: "Hurt Guy",
  position: "WR",
  lineup_slot: "WR",
  nfl_team: "KC",
  reason: "Hurt Guy is listed OUT. Bench Guy is available and plays this week.",
  replacements: ["Bench Guy"],
  ir_candidates: [],
  verb: "Swap",
  deadline: SUNDAY,
  locked: false,
  actionable: true,
  lock_is_estimated: false,
  severity: 0,
  ...over,
});

const P = (over = {}) => ({
  league: "Test League",
  team: "Team 11",
  week: 5,
  week_source: "espn",
  status: "all_clear",
  all_clear: true,
  pre_draft: false,
  blind_spots: [],
  findings: [],
  sources: [{ name: "ESPN league", age_seconds: 0, stale: false, error: null }],
  timezone: "America/New_York",
  ...over,
});

// --- UX rule 5: status is never carried by colour ---

test("every status badge carries a word and a mark, not just a class", () => {
  for (const status of ["problems", "pre_draft", "unverified", "all_clear"]) {
    const html = statusBadge(status);
    assert.match(html, /title="/, status);
    assert.match(html, /<span class="mark"/, status);
    assert.ok(html.replace(/<[^>]*>/g, "").trim().length > 3, status);
  }
});

test("the mark is hidden from screen readers so the word is not read twice", () => {
  assert.match(statusBadge("all_clear"), /aria-hidden="true"/);
});

// --- the whole point: silence is not an all-clear ---

test("an unverified run never reads as reassurance", () => {
  const html = weekHtml(P({ status: "unverified", all_clear: false,
    blind_spots: ["empty slot check skipped: no lineupSlotCounts"] }));
  assert.match(html, /Could not check everything \(1\)/);
  assert.match(html, /lineupSlotCounts/);
});

test("blind spots render above the findings, never below", () => {
  const html = weekHtml(P({ status: "problems", findings: [F()],
    blind_spots: ["ESPN league is stale"] }));
  assert.ok(html.indexOf("blindspots") < html.indexOf("finding"));
});

test("a clean week says so and renders no caveat block", () => {
  assert.equal(blindSpotsHtml(P()), "");
  assert.match(headline(P()), /All clear/);
});

test("a pre-draft run explains itself rather than claiming all clear", () => {
  const h = headline(P({ status: "pre_draft", all_clear: false, pre_draft: true }));
  assert.match(h, /Draft has not happened/);
  assert.doesNotMatch(h, /All clear/);
});

// --- the headline counts what you can still do ---

test("the headline counts actionable fixes, not findings", () => {
  const p = P({ status: "problems", all_clear: false,
    findings: [F(), F({ player_name: "Late Guy", actionable: false, locked: true })] });
  assert.match(headline(p), /1 fix you can still make/);
  assert.match(headline(p), /1 past the deadline/);
});

test("a week where everything already locked says exactly that", () => {
  const p = P({ status: "problems", all_clear: false,
    findings: [F({ actionable: false, locked: true })] });
  assert.match(headline(p), /all past their deadline/);
});

test("actionable filters to what the check said, never recomputed here", () => {
  const p = P({ findings: [F(), F({ actionable: false })] });
  assert.equal(actionable(p).length, 1);
});

// --- ordering ---

test("actionable findings sort above locked ones", () => {
  const rows = ordered([F({ player_name: "Locked", actionable: false }), F({ player_name: "Live" })]);
  assert.equal(rows[0].player_name, "Live");
});

test("severity beats deadline, because it is about how certain the zero is", () => {
  const soonButMild = F({ player_name: "Bye Guy", severity: 1, deadline: "2025-10-01T00:00:00+00:00" });
  const laterButCertain = F({ player_name: "Empty", severity: 0, deadline: SUNDAY });
  assert.equal(ordered([soonButMild, laterButCertain])[0].player_name, "Empty");
});

test("ordering never mutates the input array", () => {
  const input = [F({ player_name: "B", severity: 1 }), F({ player_name: "A", severity: 0 })];
  ordered(input);
  assert.equal(input[0].player_name, "B");
});

// --- individual findings ---

test("every finding states its reason inline, in both modes", () => {
  assert.match(findingHtml(F()), /listed OUT/);
});

test("a finding names its verb and deadline, not just a time", () => {
  const html = findingHtml(F(), "America/New_York");
  assert.match(html, /Swap/);
  assert.match(html, /by .*Oct 5/);
});

test("a claim reads as a claim, not as a swap", () => {
  assert.match(findingHtml(F({ verb: "Claim", replacements: [] })), /Claim/);
});

test("an empty slot does not render as missing data", () => {
  const html = findingHtml(F({ kind: "empty_slot", player_name: "", nfl_team: "", lineup_slot: "TE" }));
  assert.match(html, /no one in this slot/);
  assert.doesNotMatch(html, /\(\)/);
});

test("a locked finding is shown but never given a deadline to chase", () => {
  const html = findingHtml(F({ actionable: false, locked: true }));
  assert.match(html, /Past the deadline/);
  assert.doesNotMatch(html, /Swap by/);
});

test("no bench option says so rather than rendering an empty list", () => {
  assert.match(findingHtml(F({ replacements: [] })), /Nothing on the bench fits/);
});

test("IR candidates carry their prerequisite", () => {
  const html = findingHtml(F({ replacements: [], ir_candidates: ["Stashed Guy"] }));
  assert.match(html, /Stashed Guy/);
  assert.match(html, /activate first/);
});

test("an estimated deadline admits it is estimated", () => {
  assert.match(findingHtml(F({ lock_is_estimated: true })), /estimate/);
});

test("a missing deadline never renders as a date", () => {
  assert.match(findingHtml(F({ deadline: null })), /no known deadline/);
});

test("an unparseable deadline degrades rather than printing Invalid Date", () => {
  assert.doesNotMatch(findingHtml(F({ deadline: "not a date" })), /Invalid Date/);
});

// --- deadlines are shown even when nothing is wrong ---

test("a clean week still names the next deadline", () => {
  const html = deadlinesHtml(P({ next_lock: SUNDAY, waiver_deadline: SUNDAY }));
  assert.match(html, /Next slot freezes/);
  assert.match(html, /Waivers next process/);
});

test("deadlines render in the league timezone, not the browser's", () => {
  const east = deadlinesHtml(P({ next_lock: SUNDAY, timezone: "America/New_York" }));
  const west = deadlinesHtml(P({ next_lock: SUNDAY, timezone: "America/Los_Angeles" }));
  assert.notEqual(east, west);
});

// --- provenance ---

test("source ages are reported per source, in human units", () => {
  const text = sourcesText(P({ sources: [
    { name: "ESPN league", age_seconds: 0, stale: false },
    { name: "NFL schedule", age_seconds: 7200, stale: false },
  ] }));
  assert.match(text, /ESPN league live/);
  assert.match(text, /NFL schedule 2h old/);
});

test("a stale source says so in a word, not only by class", () => {
  const text = sourcesText(P({ sources: [{ name: "ESPN league", age_seconds: 999999, stale: true }] }));
  assert.match(text, /STALE/);
});

// --- the standing rules ---

test("no dollar sign is ever emitted", () => {
  const html = weekHtml(P({ status: "problems", findings: [F()],
    blind_spots: ["x"], next_lock: SUNDAY, waiver_deadline: SUNDAY }));
  assert.doesNotMatch(html, /\$/);
});

test("player names are escaped", () => {
  const html = findingHtml(F({ player_name: "<script>x</script>" }));
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("blind spot text is escaped too", () => {
  assert.doesNotMatch(blindSpotsHtml(P({ blind_spots: ["<img onerror=1>"] })), /<img/);
});

test("a finding card carries its kind as a class so the edge can echo the chip", () => {
  assert.match(findingHtml(F({ kind: "bye" })), /class="finding k-bye/);
  assert.match(findingHtml(F({ actionable: false })), /k-out done/);
});
