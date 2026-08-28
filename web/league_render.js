// Pure render logic for the team/roster view. No DOM access here -- see
// render.js's header comment for why that split exists. league_main.js
// does the DOM wiring.

import { escapeHtml, positionClass } from "./render.js";

export function rosterRowHtml(entry) {
  const name = escapeHtml(entry.player_name);
  return `<tr class="roster-row${entry.is_starter ? "" : " bench"}">
  <td><span class="pos ${positionClass(entry.position)}">${escapeHtml(entry.position)}</span></td>
  <td class="name">${name}</td>
  <td>${escapeHtml(entry.nfl_team)}</td>
  <td>${escapeHtml(entry.lineup_slot)}</td>
</tr>`;
}

export function rosterHtml(roster) {
  if (roster.length === 0) {
    return `<tr><td colspan="4" class="empty">No roster yet.</td></tr>`;
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
    <thead><tr><th>Pos</th><th>Player</th><th>NFL</th><th>Slot</th></tr></thead>
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
