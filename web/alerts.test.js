import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MUTE_PRESETS,
  kindsHtml,
  muteInstant,
  payloadFrom,
  quietHtml,
  summary,
  whenText,
} from "./alerts.js";

const P = (over = {}) => ({
  path: "alerts.yaml",
  exists: true,
  error: null,
  kinds: [
    { name: "empty_slot", label: "An empty starting slot", enabled: true },
    { name: "out", label: "A starter ruled OUT", enabled: true },
    { name: "bye_next_week", label: "A starter on bye next week", enabled: true },
  ],
  quiet_hours: { enabled: true, start: 23, end: 8 },
  mute_until: null,
  writable: true,
  ...over,
});

// --- the headline ---

test("a page with nothing switched off says so plainly", () => {
  assert.match(summary(P()), /Every kind/);
});

test("switched-off kinds are counted and named", () => {
  const payload = P({
    kinds: [
      { name: "out", label: "OUT", enabled: true },
      { name: "bye_next_week", label: "Bye next week", enabled: false },
    ],
  });
  assert.match(summary(payload), /1 of 2/);
  assert.match(summary(payload), /bye_next_week/);
});

test("a mute is said first, because it hides everything below it", () => {
  const now = new Date("2026-09-13T12:00:00Z");
  const payload = P({
    mute_until: "2026-09-13T15:00:00Z",
    kinds: [{ name: "out", label: "OUT", enabled: false }],
  });
  assert.match(summary(payload, now), /^Muted until/);
});

test("a lapsed mute is not reported as a mute", () => {
  const now = new Date("2026-09-13T18:00:00Z");
  const payload = P({ mute_until: "2026-09-13T15:00:00Z" });
  assert.doesNotMatch(summary(payload, now), /Muted/);
});

// --- mute presets ---

test("every preset lands on a moment in the future", () => {
  const now = new Date("2026-09-13T12:00:00Z");
  for (const preset of MUTE_PRESETS) {
    const instant = muteInstant(now, preset.id);
    assert.ok(new Date(instant) > now, preset.id);
  }
});

test("there is no preset that never expires", () => {
  // The rule the page exists to keep: a permanent mute is how a season ends
  // in silence.
  for (const preset of MUTE_PRESETS) {
    assert.ok(muteInstant(new Date(), preset.id) !== null);
  }
  assert.equal(muteInstant(new Date(), "forever"), null);
});

test("an unknown preset yields nothing rather than a bogus instant", () => {
  assert.equal(muteInstant(new Date(), "next-tuesday"), null);
});

// --- the form ---

test("every kind renders its sentence, not only its identifier", () => {
  const html = kindsHtml(P());
  assert.match(html, /An empty starting slot/);
  assert.match(html, /A starter ruled OUT/);
});

test("a switched-off kind renders unchecked", () => {
  const html = kindsHtml(P({
    kinds: [{ name: "out", label: "OUT", enabled: false }],
  }));
  assert.doesNotMatch(html, /checked/);
});

test("quiet hours render the stored window as the selected options", () => {
  const html = quietHtml(P({ quiet_hours: { enabled: true, start: 22, end: 7 } }));
  assert.match(html, /<option value="22" selected>/);
  assert.match(html, /<option value="7" selected>/);
});

test("quiet hours disabled renders an unchecked box", () => {
  const html = quietHtml(P({ quiet_hours: { enabled: false, start: 23, end: 8 } }));
  assert.doesNotMatch(html, /checked/);
});

test("what is posted is shaped the way the endpoint validates", () => {
  const body = payloadFrom({
    kinds: { out: false },
    quietEnabled: true,
    quietStart: 23,
    quietEnd: 8,
    muteUntil: "",
  });
  assert.deepEqual(body, {
    kinds: { out: false },
    quiet_hours: { enabled: true, start: 23, end: 8 },
    mute_until: "",
  });
});

// --- what must never appear ---

test("no dollar sign reaches this page either", () => {
  // UX rule 3, asserted per page rather than centrally so a new page cannot
  // quietly opt out of it.
  const html = kindsHtml(P()) + quietHtml(P()) + summary(P());
  assert.doesNotMatch(html, /\$/);
});

test("a label containing markup is escaped, not rendered", () => {
  const html = kindsHtml(P({
    kinds: [{ name: "out", label: "<img src=x onerror=alert(1)>", enabled: true }],
  }));
  assert.doesNotMatch(html, /<img/);
});

test("an empty instant renders as nothing rather than as Invalid Date", () => {
  assert.equal(whenText(null), "");
  assert.equal(whenText(""), "");
});
