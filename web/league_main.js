// DOM wiring only. All computation lives in league_render.js, which is
// tested. Mirrors main.js's structure.
import { leagueHtml } from "./league_render.js";
import { navHtml } from "./nav.js";
import { escapeHtml, freshnessText } from "./render.js";

const $ = (id) => document.getElementById(id);

async function load() {
  $("nav").innerHTML = navHtml("league");

  try {
    const response = await fetch("data/league.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();

    $("league-name").textContent = `${payload.league.name} — Teams`;
    const bits = [`${payload.teams.length} teams`];
    const freshness = freshnessText(payload, "ffcoach league");
    if (freshness) bits.push(freshness);
    $("status").textContent = bits.join(" · ");
    $("status").classList.toggle("stale", Boolean(payload.stale));

    // Anything the ESPN adapter could not interpret. Shown on the page, not
    // just on the stderr of a run nobody watched.
    const notes = payload.diagnostics ?? [];
    $("diagnostics").innerHTML = notes.length
      ? `<p class="warn">ESPN data we could not read: ${notes
          .map((n) => escapeHtml(n))
          .join("; ")}</p>`
      : "";

    $("teams").innerHTML = leagueHtml(payload.teams);
  } catch (error) {
    $("status").textContent =
      `Could not load data/league.json (${error.message}). ` +
      `Run "uv run ffcoach league --fixture tests/fixtures/espn_league.json" ` +
      `(or against your real league once it's set up), and make sure you are ` +
      `serving it with "uv run ffcoach serve" rather than opening the file ` +
      `directly \u2014 file:// blocks the fetch.`;
  }
}

load();
