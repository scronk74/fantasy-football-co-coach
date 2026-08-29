import { test } from "node:test";
import assert from "node:assert/strict";
import { leagueHtml, rosterHtml, rosterRowHtml, teamCardHtml } from "./league_render.js";

const ENTRY = (over = {}) => ({
  player_name: "Bijan Robinson",
  position: "RB",
  nfl_team: "ATL",
  lineup_slot: "RB",
  is_starter: true,
  ...over,
});

const TEAM = (over = {}) => ({
  team_id: "1",
  name: "Dynasty",
  owner: "Steve",
  wins: 5,
  losses: 3,
  ties: 0,
  record: "5-3",
  points_for: 650.4,
  points_against: 601.2,
  is_user_team: false,
  roster: [ENTRY()],
  ...over,
});

test("rosterRowHtml escapes html in player names", () => {
  const html = rosterRowHtml(ENTRY({ player_name: "<script>x</script>" }));
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("rosterRowHtml marks bench players with a bench class", () => {
  assert.match(rosterRowHtml(ENTRY({ is_starter: false })), /bench/);
  assert.doesNotMatch(rosterRowHtml(ENTRY({ is_starter: true })), /bench/);
});

test("rosterRowHtml shows position, team, and slot as real terms", () => {
  const html = rosterRowHtml(ENTRY({ position: "WR", nfl_team: "DET", lineup_slot: "FLEX" }));
  assert.match(html, />WR</);
  assert.match(html, /DET/);
  assert.match(html, /FLEX/);
});

test("rosterHtml handles an empty roster", () => {
  assert.match(rosterHtml([]), /no roster/i);
});

test("rosterHtml renders one row per entry", () => {
  const html = rosterHtml([ENTRY(), ENTRY({ player_name: "Second" })]);
  assert.equal((html.match(/<tr/g) || []).length, 2);
});

test("teamCardHtml shows name, owner, and record", () => {
  const html = teamCardHtml(TEAM());
  assert.match(html, /Dynasty/);
  assert.match(html, /Steve/);
  assert.match(html, /5-3/);
});

test("teamCardHtml marks the user's own team", () => {
  const mine = teamCardHtml(TEAM({ is_user_team: true }));
  assert.match(mine, /class="team-card mine"/);
  assert.match(mine, /Your team/);
});

test("teamCardHtml does not mark other teams as mine", () => {
  const notMine = teamCardHtml(TEAM({ is_user_team: false }));
  assert.doesNotMatch(notMine, /class="team-card mine"/);
  assert.doesNotMatch(notMine, /Your team/);
});

test("teamCardHtml escapes html in team and owner names", () => {
  const html = teamCardHtml(TEAM({ name: "<b>x</b>", owner: "<i>y</i>" }));
  assert.doesNotMatch(html, /<b>x<\/b>/);
  assert.doesNotMatch(html, /<i>y<\/i>/);
});

test("teamCardHtml never emits a dollar sign", () => {
  assert.doesNotMatch(teamCardHtml(TEAM()), /\$/);
});

test("leagueHtml puts the user's team first", () => {
  const teams = [
    TEAM({ name: "Bravo", is_user_team: false }),
    TEAM({ name: "Alpha", is_user_team: false }),
    TEAM({ name: "Zulu", is_user_team: true }),
  ];
  const html = leagueHtml(teams);
  const order = [...html.matchAll(/<h2>([^<]+)/g)].map((m) => m[1].trim());
  assert.deepEqual(order, ["Zulu", "Alpha", "Bravo"]);
});

test("leagueHtml handles no teams", () => {
  assert.match(leagueHtml([]), /no teams/i);
});
