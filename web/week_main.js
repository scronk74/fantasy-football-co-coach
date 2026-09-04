// DOM wiring only. Everything computed lives in week.js, which is tested.
import { navHtml } from "./nav.js";
import { escapeHtml } from "./render.js";
import { headline, sourcesText, statusBadge, weekHtml } from "./week.js";

const $ = (id) => document.getElementById(id);

async function load() {
  $("nav").innerHTML = navHtml("week");

  try {
    const response = await fetch("data/check.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();

    document.title = `Week ${payload.week} — ${payload.league}`;
    $("title").textContent = `Week ${payload.week}`;
    const team = payload.team_abbrev
      ? `${payload.team} (${payload.team_abbrev})`
      : payload.team;
    $("subtitle").textContent =
      `${team} · ${payload.league} · week from ${payload.week_source}`;
    $("badge").innerHTML = statusBadge(payload.status);
    $("headline").textContent = headline(payload);
    $("body").innerHTML = weekHtml(payload);

    const sources = sourcesText(payload);
    $("sources").textContent = sources ? `Data: ${sources}` : "";
    $("sources").classList.toggle("stale", Boolean(payload.stale));
    $("generated").textContent = payload.generated_at
      ? `Checked ${escapeHtml(payload.generated_at)}`
      : "";
  } catch (error) {
    // A page that cannot load its payload must not look like a clean week.
    $("badge").innerHTML = statusBadge("unverified");
    $("headline").textContent = "This page could not load the last check.";
    $("body").innerHTML =
      `<p class="warn">Could not read data/check.json (${escapeHtml(error.message)}). ` +
      `Run <code>uv run ffcoach check</code>, and view this through a server ` +
      `rather than opening the file directly — <code>file://</code> blocks the fetch.</p>`;
  }
}

load();
