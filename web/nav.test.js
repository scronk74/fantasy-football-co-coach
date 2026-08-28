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
  const draftLink = html.split("</a>").find((chunk) => chunk.includes("index.html"));
  assert.match(draftLink, /current/);
  const leagueLink = html.split("</a>").find((chunk) => chunk.includes("league.html"));
  assert.doesNotMatch(leagueLink, /current/);
});

test("navHtml adding a page to PAGES would not require touching this function", () => {
  // Guard against ever hardcoding page ids/labels inside navHtml itself.
  assert.doesNotMatch(navHtml.toString(), /Draft Board|My League/);
});
