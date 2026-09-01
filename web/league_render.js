// Pure render logic for the team/roster view. No DOM access here -- see
// render.js's header comment for why that split exists. league_main.js
// does the DOM wiring.

import { escapeHtml, positionClass } from "./render.js";

// ESPN's injuryStatus values, shortened for a table cell. ACTIVE is not here
// on purpose: healthy is the default and labelling it adds noise to every row.
const STATUS_LABELS = {
  QUESTIONABLE: "Q",
  DOUBTFUL: "D",
  OUT: "OUT",
  INJURY_RESERVE: "IR",
  SUSPENSION: "SUSP",
};

// Which statuses guarantee a zero, mirroring CERTAIN_OUT in leagues/base.py.
const CERTAIN_OUT = new Set(["OUT", "INJURY_RESERVE", "SUSPENSION", "IR"]);

// Returns "" for healthy or unknown, so the column stays quiet by default.
// Never colour alone: the letter carries the meaning and `title` spells it
// out, because a red dot is invisible to a screen reader and to about one man
// in twelve.
export function injuryBadgeHtml(status) {
  if (!status) return "";
  const key = String(status).trim().toUpperCase();
  const label = STATUS_LABELS[key];
  if (!label) return "";
  const severity = CERTAIN_OUT.has(key) ? "out" : "doubt";
  const full = key.replace(/_/g, " ").toLowerCase();
  return `<span class="injury ${severity}" title="${escapeHtml(full)}">${label}</span>`;
}

export function rosterRowHtml(entry) {
  const name = escapeHtml(entry.player_name);
  return `<tr class="roster-row${entry.is_starter ? "" : " bench"}">
  <td><span class="pos ${positionClass(entry.position)}">${escapeHtml(entry.position)}</span></td>
  <td class="name">${name}</td>
  <td>${escapeHtml(entry.nfl_team)}</td>
  <td>${escapeHtml(entry.lineup_slot)}</td>
  <td class="status">${injuryBadgeHtml(entry.injury_status)}</td>
</tr>`;
}

export function rosterHtml(roster) {
  if (roster.length === 0) {
    return `<tr><td colspan="5" class="empty">No roster yet.</td></tr>`;
  }
  return roster.map(rosterRowHtml).join("\n");
}

export function teamCardHtml(team) {
  const name = escapeHtml(team.name);
  const owner = escapeHtml(team.owner);
  const badge = team.is_user_team ? ' <span class="mine-badge">Your team</span>' : "";
  return `<section class="team-card${team.is_user_team ? " mine" : ""}" data-team-id="${escapeHtml(team.team_id)}">
  <header>
    <h2>${name}${badge}</h2>
    <p class="owner">${owner} &middot; ${escapeHtml(team.record)}</p>
    <p class="points">${team.points_for.toFixed(1)} PF / ${team.points_against.toFixed(1)} PA</p>
  </header>
  <table>
    <thead><tr><th>Pos</th><th>Player</th><th>NFL</th><th>Slot</th><th>Status</th></tr></thead>
    <tbody>${rosterHtml(team.roster)}</tbody>
  </table>
</section>`;
}

export function leagueHtml(teams) {
  if (teams.length === 0) {
    return `<p class="empty">No teams to show.</p>`;
  }
  // Your team first, then alphabetical -- the natural read order for this page.
  const ordered = [...teams].sort((a, b) => {
    if (a.is_user_team !== b.is_user_team) return a.is_user_team ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  return ordered.map(teamCardHtml).join("\n");
}
