// DOM wiring only. All computation lives in league_render.js, which is
// tested. Mirrors main.js's structure.
import { leagueHtml } from "./league_render.js";
import { navHtml } from "./nav.js";

const $ = (id) => document.getElementById(id);

async function load() {
  $("nav").innerHTML = navHtml("league");

  try {
    const response = await fetch("data/league.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();

    $("league-name").textContent = `${payload.league.name} — Teams`;
    const bits = [`${payload.teams.length} teams`];
    if (payload.stale) bits.push("data is stale — run ffcoach league");
    $("status").textContent = bits.join(" · ");

    $("teams").innerHTML = leagueHtml(payload.teams);
  } catch (error) {
    $("status").textContent =
      `Could not load data/league.json (${error.message}). ` +
      `Run "uv run ffcoach league --fixture tests/fixtures/espn_league.json" ` +
      `(or against your real league once it's set up), and make sure you are ` +
      `viewing this through Live Server rather than opening the file directly.`;
  }
}

load();
