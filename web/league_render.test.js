import { test } from "node:test";
import assert from "node:assert/strict";
import {
  injuryBadgeHtml,
  leagueHtml,
  rosterHtml,
  rosterRowHtml,
  teamCardHtml,
} from "./league_render.js";

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

// --- injury status (it was in the payload and thrown away) ---

test("injuryBadgeHtml says nothing for a healthy player", () => {
  assert.equal(injuryBadgeHtml(null), "");
  assert.equal(injuryBadgeHtml("ACTIVE"), "");
  assert.equal(injuryBadgeHtml(""), "");
});

test("injuryBadgeHtml labels questionable and out differently", () => {
  assert.match(injuryBadgeHtml("QUESTIONABLE"), /\bQ\b/);
  assert.match(injuryBadgeHtml("OUT"), /OUT/);
  assert.match(injuryBadgeHtml("INJURY_RESERVE"), /IR/);
});

test("a certain-out status is marked more severely than a doubtful one", () => {
  assert.match(injuryBadgeHtml("OUT"), /injury out/);
  assert.match(injuryBadgeHtml("QUESTIONABLE"), /injury doubt/);
});

test("injury status is never conveyed by colour alone", () => {
  // A red dot is invisible to a screen reader. The letters and the title
  // attribute are what actually carry the meaning.
  const html = injuryBadgeHtml("QUESTIONABLE");
  assert.match(html, /title="questionable"/);
  assert.match(html, />Q</);
});

test("an unrecognized status is left blank rather than guessed at", () => {
  assert.equal(injuryBadgeHtml("SOMETHING_NEW"), "");
});

test("a roster row surfaces the status it was given", () => {
  const html = rosterRowHtml(ENTRY({ injury_status: "QUESTIONABLE" }));
  assert.match(html, />Q</);
});

test("a roster row with no status still renders the cell", () => {
  const html = rosterRowHtml(ENTRY({ injury_status: null }));
  assert.match(html, /class="status"/);
});

test("the empty-roster row spans every column", () => {
  const columns = (rosterRowHtml(ENTRY()).match(/<td/g) || []).length;
  assert.match(rosterHtml([]), new RegExp(`colspan="${columns}"`));
});

test("a team card shows ESPN's own short abbreviation beside the name", () => {
  const html = teamCardHtml(TEAM({ name: "Just End The Season", abbrev: "JETS" }));
  assert.match(html, /Just End The Season/);
  assert.match(html, /JETS/);
});

test("a missing abbreviation is omitted, never invented from the name", () => {
  // A manufactured abbreviation looks exactly like a real one.
  const html = teamCardHtml(TEAM({ name: "Just End The Season", abbrev: "" }));
  assert.doesNotMatch(html, /class="abbrev"/);
});

test("an abbreviation is escaped like any other ESPN string", () => {
  const html = teamCardHtml(TEAM({ abbrev: "<img onerror=1>" }));
  assert.doesNotMatch(html, /<img/);
});






