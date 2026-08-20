import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyFilters,
  bestAvailable,
  boardHtml,
  formatValue,
  playerId,
  positionClass,
  rowHtml,
  tierCounts,
} from "./render.js";

const P = (over = {}) => ({
  rank: 1,
  name: "Bijan Robinson",
  position: "RB",
  team: "ATL",
  adp: 1.7,
  stdev: 0.8,
  bye: 11,
  value: 0.7,
  verdict: "fair",
  verdict_text: "He is going right about where he normally goes.",
  availability: "gone",
  availability_text: "Almost certainly drafted before pick 18.",
  tier: 1,
  tier_break_after: false,
  injury_status: null,
  reason: "",
  ...over,
});

test("formatValue always shows a sign and one decimal", () => {
  assert.equal(formatValue(4), "+4.0");
  assert.equal(formatValue(-2.25), "-2.3");
  assert.equal(formatValue(0), "0.0");
});

test("positionClass maps position to a class", () => {
  assert.equal(positionClass("RB"), "pos-rb");
  assert.equal(positionClass("DEF"), "pos-def");
});

test("playerId is stable and unique per name and position", () => {
  assert.equal(playerId(P()), playerId(P()));
  assert.notEqual(playerId(P()), playerId(P({ name: "Someone Else" })));
  assert.notEqual(playerId(P()), playerId(P({ position: "WR" })));
});

test("applyFilters returns everything by default", () => {
  const players = [P(), P({ name: "B", position: "WR" })];
  assert.equal(applyFilters(players, {}).length, 2);
});

test("applyFilters narrows by position", () => {
  const players = [P(), P({ name: "B", position: "WR" })];
  const out = applyFilters(players, { position: "WR" });
  assert.deepEqual(out.map((p) => p.name), ["B"]);
});

test("applyFilters can hide drafted players", () => {
  const a = P();
  const b = P({ name: "B" });
  const drafted = new Set([playerId(a)]);
  const out = applyFilters([a, b], { hideDrafted: true, draftedIds: drafted });
  assert.deepEqual(out.map((p) => p.name), ["B"]);
});

test("applyFilters keeps drafted players when not hiding", () => {
  const a = P();
  const drafted = new Set([playerId(a)]);
  assert.equal(applyFilters([a], { hideDrafted: false, draftedIds: drafted }).length, 1);
});

test("bestAvailable skips drafted players", () => {
  const a = P({ name: "A", rank: 1 });
  const b = P({ name: "B", rank: 2 });
  assert.equal(bestAvailable([a, b], new Set([playerId(a)])).name, "B");
});

test("bestAvailable returns null when everyone is gone", () => {
  const a = P();
  assert.equal(bestAvailable([a], new Set([playerId(a)])), null);
});

test("tierCounts counts undrafted players per position tier", () => {
  const players = [
    P({ name: "A", position: "RB", tier: 1 }),
    P({ name: "B", position: "RB", tier: 1 }),
    P({ name: "C", position: "WR", tier: 2 }),
  ];
  const counts = tierCounts(players, new Set());
  assert.equal(counts["RB1"], 2);
  assert.equal(counts["WR2"], 1);
});

test("tierCounts drops to zero as players are drafted", () => {
  const a = P({ position: "RB", tier: 1 });
  assert.equal(tierCounts([a], new Set([playerId(a)]))["RB1"], 0);
});

test("rowHtml shows the raw ADP number in both modes", () => {
  assert.match(rowHtml(P(), { explain: false }), /1\.7/);
  assert.match(rowHtml(P(), { explain: true }), /1\.7/);
});

test("rowHtml never renames ADP away", () => {
  const html = rowHtml(P(), { explain: true });
  assert.doesNotMatch(html, /Typical pick/i);
});

test("rowHtml shows the reason in both modes", () => {
  const p = P({ verdict: "bargain", reason: "Falling past his usual draft slot." });
  assert.match(rowHtml(p, { explain: false }), /Falling past his usual draft slot/);
  assert.match(rowHtml(p, { explain: true }), /Falling past his usual draft slot/);
});

test("explain mode adds the verdict explanation, plain mode does not", () => {
  const p = P({ verdict_text: "EXPLAIN ME" });
  assert.doesNotMatch(rowHtml(p, { explain: false }), /EXPLAIN ME/);
  assert.match(rowHtml(p, { explain: true }), /EXPLAIN ME/);
});

test("drafted rows are marked", () => {
  assert.match(rowHtml(P(), { drafted: true }), /drafted/);
});

test("rowHtml escapes html in player names", () => {
  const html = rowHtml(P({ name: "<script>x</script>" }), {});
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("rowHtml never emits a dollar sign", () => {
  assert.doesNotMatch(rowHtml(P({ verdict: "bargain" }), { explain: true }), /\$/);
});

test("boardHtml inserts a tier break row after a flagged player", () => {
  const players = [P({ name: "A", tier_break_after: true }), P({ name: "B", tier: 2 })];
  const html = boardHtml(players, {});
  assert.match(html, /tier-break/);
});

test("boardHtml renders one row per player plus breaks", () => {
  const players = [P({ name: "A" }), P({ name: "B" })];
  const html = boardHtml(players, {});
  assert.equal((html.match(/<tr/g) || []).length, 2);
});

test("boardHtml handles an empty roster", () => {
  assert.match(boardHtml([], {}), /no players/i);
});
