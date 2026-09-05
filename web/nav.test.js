import { test } from "node:test";
import assert from "node:assert/strict";
import { PAGES, navHtml } from "./nav.js";

test("every page entry has an id, label, and href", () => {
  for (const page of PAGES) {
    assert.ok(page.id);
    assert.ok(page.label);
    assert.ok(page.href);
  }
});

test("navHtml renders one link per page", () => {
  const html = navHtml("draft");
  const count = (html.match(/<a /g) || []).length;
  assert.equal(count, PAGES.length);
});

test("navHtml marks the current page", () => {
  const html = navHtml("league");
  assert.match(html, /class="navlink current"/);
  assert.match(html, /aria-current="page"/);
});

test("navHtml does not mark other pages as current", () => {
  const html = navHtml("draft");
  const draftLink = html.split("</a>").find((chunk) => chunk.includes("draft.html"));
  assert.match(draftLink, /current/);
  const leagueLink = html.split("</a>").find((chunk) => chunk.includes("league.html"));
  assert.doesNotMatch(leagueLink, /current/);
});

test("the front door is this week, not the draft board", () => {
  // D-051. The app opening on the draft board meant the first thing you saw
  // was the one page you said you did not want.
  const front = PAGES.find((p) => p.href === "index.html");
  assert.equal(front.id, "week");
});

test("navHtml adding a page to PAGES would not require touching this function", () => {
  // Guard against ever hardcoding page ids/labels inside navHtml itself.
  assert.doesNotMatch(navHtml.toString(), /Draft Board|My League|This Week/);
});

test("the Alerts page is in the nav", () => {
  // F2's whole point is being reachable without remembering a URL. A control
  // panel you have to know about is one you never open.
  assert.ok(PAGES.some((page) => page.id === "alerts" && page.href === "alerts.html"));
});
