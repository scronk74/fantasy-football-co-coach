import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BAD,
  OK,
  UNKNOWN,
  ageText,
  alertingHostRow,
  healthHtml,
  heartbeatRow,
  lastRunRow,
  lastSuccessRow,
  overall,
  rows,
  schedulerRow,
  setupHtml,
  sourcesHtml,
  watchdogRow,
} from "./health.js";

const P = (over = {}) => ({
  host: "steve-imac",
  alerts: { configured: true, channel: "ntfy", reason: null },
  heartbeat: { configured: true },
  scheduler: {
    host: "steve-imac", is_this_machine: true, plist_exists: true,
    loaded: true, interval_minutes: 30,
  },
  watchdog: { tripped: false, reason: null },
  last_run: { at: "x", age_seconds: 120, ok: true, status: "all_clear",
              findings: 0, sources: [] },
  last_success: { at: "x", age_seconds: 120, ok: true },
  setup: [],
  ...over,
});

// --- the rule this page lives by ---

test("a scheduler we could not ask about is unknown, never healthy", () => {
  // A panel that says "yes" because it failed to ask is the exact failure it
  // exists to catch.
  const row = schedulerRow(P({ scheduler: { loaded: null, interval_minutes: 30 } }));
  assert.equal(row.state, UNKNOWN);
  assert.match(row.detail, /could not be determined/);
});

test("a scheduler that is genuinely absent is bad, not unknown", () => {
  const row = schedulerRow(P({ scheduler: { loaded: false, plist_exists: false } }));
  assert.equal(row.state, BAD);
  assert.match(row.detail, /nothing is running the check/);
});

test("installed-but-not-loaded is distinguished from not installed", () => {
  const row = schedulerRow(P({ scheduler: { loaded: false, plist_exists: true } }));
  assert.match(row.detail, /installed but not loaded/);
});

test("any unknown drags the overall state down from ok", () => {
  assert.equal(overall(P()), OK);
  assert.equal(overall(P({ scheduler: { loaded: null } })), UNKNOWN);
});

test("any bad beats any unknown", () => {
  const p = P({ scheduler: { loaded: null }, heartbeat: { configured: false } });
  assert.equal(overall(p), BAD);
});

// --- last run vs last success ---

test("the last run and the last success are reported separately", () => {
  // A recent run proves the scheduler is alive; only a recent success proves
  // it would have told you anything.
  const labels = rows(P()).map((r) => r.label);
  assert.ok(labels.includes("Last run"));
  assert.ok(labels.includes("Last success"));
});

test("a machine erroring every fifteen minutes does not read as healthy", () => {
  const p = P({
    last_run: { age_seconds: 120, ok: false, error: "EspnAuthError", sources: [] },
    last_success: null,
  });
  assert.equal(lastRunRow(p).state, BAD);
  assert.equal(lastSuccessRow(p).state, BAD);
  assert.match(lastSuccessRow(p).detail, /never/);
});

test("a run that was suppressed by the host guard says so", () => {
  const p = P({ last_run: { age_seconds: 60, ok: true, status: "problems",
                            findings: 2, suppressed_host: "macbook-air", sources: [] } });
  assert.match(lastRunRow(p).detail, /not the alerting host/);
});

test("never having run is bad, not unknown", () => {
  assert.equal(lastRunRow(P({ last_run: null })).state, BAD);
});

// --- exposures stated as exposures ---

test("a missing heartbeat says what it costs, not just that it is missing", () => {
  const row = heartbeatRow(P({ heartbeat: { configured: false } }));
  assert.equal(row.state, BAD);
  assert.match(row.detail, /nothing will tell you/);
});

test("a tripped watchdog carries its own reason", () => {
  const row = watchdogRow(P({ watchdog: { tripped: true, reason: "failed 3 runs in a row" } }));
  assert.equal(row.state, BAD);
  assert.match(row.detail, /3 runs in a row/);
});

test("an unrecorded alerting host is unknown, since any machine may alert", () => {
  const row = alertingHostRow(P({ scheduler: { host: null } }));
  assert.equal(row.state, UNKNOWN);
});

test("a machine that is not the alerting host says it will not send", () => {
  const row = alertingHostRow(P({ scheduler: { host: "steve-imac", is_this_machine: false } }));
  assert.match(row.detail, /will not send or ping/);
});

// --- presentation rules ---

test("every row carries a word and a mark, never colour alone", () => {
  const html = healthHtml(P());
  for (const row of rows(P())) {
    assert.ok(html.includes(row.label), row.label);
  }
  assert.match(html, /<span class="hmark" aria-hidden="true">/);
});

test("no ANSI or dollar sign reaches the page", () => {
  const html = healthHtml(P({ heartbeat: { configured: false }, setup: [
    { done: false, what: "espn.yaml", fix: "copy espn.example.yaml" }] }));
  assert.doesNotMatch(html, /\x1b/);
  assert.doesNotMatch(html, /\$/);
});

test("remaining setup steps carry the command that fixes them", () => {
  const html = setupHtml(P({ setup: [
    { done: true, what: "league.yaml", fix: "x" },
    { done: false, what: "espn.yaml", fix: "uv run ffcoach init" }] }));
  assert.match(html, /1 step\(s\) left/);
  assert.match(html, /uv run ffcoach init/);
  assert.doesNotMatch(html, /league.yaml/);
});

test("a completed setup renders nothing at all", () => {
  assert.equal(setupHtml(P({ setup: [{ done: true, what: "x", fix: "y" }] })), "");
});

test("source ages are shown per source, with stale called out in a word", () => {
  const html = sourcesHtml(P({ last_run: { sources: [
    { name: "ESPN league", age_seconds: 0, stale: false },
    { name: "NFL schedule", age_seconds: 999999, stale: true }] } }));
  assert.match(html, /ESPN league — live/);
  assert.match(html, /STALE/);
});

test("everything from the payload is escaped", () => {
  const html = healthHtml(P({ watchdog: { tripped: true, reason: "<img onerror=1>" } }));
  assert.doesNotMatch(html, /<img/);
});

test("ageText degrades rather than printing NaN", () => {
  assert.equal(ageText(null), "unknown");
  assert.equal(ageText(undefined), "unknown");
  assert.equal(ageText(45), "45s ago");
  assert.equal(ageText(7200), "2h ago");
});
