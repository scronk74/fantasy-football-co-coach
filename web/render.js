// Pure render and filter logic. No DOM access lives here, which is what
// makes it testable with `node --test`. All DOM wiring is in main.js.

const POSITION_CLASSES = {
  QB: "pos-qb",
  RB: "pos-rb",
  WR: "pos-wr",
  TE: "pos-te",
  K: "pos-k",
  DEF: "pos-def",
};

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function playerId(player) {
  return `${player.name}|${player.position}`;
}

// Rounded on purpose. "3h" is honest about being approximate; "2.83h" claims a
// precision the number does not have.
export function ageText(seconds) {
  if (seconds == null) return "";
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 90) return `${Math.round(n)}s`;
  if (n < 90 * 60) return `${Math.round(n / 60)}m`;
  if (n < 48 * 3600) return `${Math.round(n / 3600)}h`;
  return `${Math.round(n / 86400)}d`;
}

// How old the data is, and whether serving it was a fallback. These are two
// different facts: the payload used to carry only `stale`, computed from
// whether an age happened to be present, so a live fetch and a week-old cache
// were indistinguishable on the page. `command` is what the user would run to
// refresh, named so the page never says "stale" without saying what to do.
export function freshnessText(payload, command) {
  // Age zero means the fetch was live, and "data 0s old" is noise on a line
  // whose job is to flag the exceptions.
  const seconds = payload?.age_seconds;
  const age = Number(seconds) > 0 ? ageText(seconds) : "";
  if (payload?.stale) {
    return age
      ? `stale — showing data from ${age} ago; run ${command}`
      : `stale — the last fetch failed; run ${command}`;
  }
  return age ? `data ${age} old` : "";
}

export function formatValue(value) {
  const n = Number(value);
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(1)}`;
}

export function positionClass(position) {
  return POSITION_CLASSES[position] ?? "pos-k";
}

export function applyFilters(players, { position, hideDrafted, draftedIds } = {}) {
  const drafted = draftedIds ?? new Set();
  return players.filter((p) => {
    if (position && position !== "ALL" && p.position !== position) return false;
    if (hideDrafted && drafted.has(playerId(p))) return false;
    return true;
  });
}

export function bestAvailable(players, draftedIds = new Set()) {
  const open = players.filter((p) => !draftedIds.has(playerId(p)));
  if (open.length === 0) return null;
  return open.reduce((best, p) => (p.rank < best.rank ? p : best));
}

export function tierCounts(players, draftedIds = new Set()) {
  const counts = {};
  for (const p of players) {
    const key = `${p.position}${p.tier}`;
    counts[key] = counts[key] ?? 0;
    if (!draftedIds.has(playerId(p))) counts[key] += 1;
  }
  return counts;
}

export function rowHtml(player, { explain = false, drafted = false } = {}) {
  const name = escapeHtml(player.name);
  const reason = player.reason
    ? `<span class="reason">${escapeHtml(player.reason)}</span>`
    : "";
  // Explain mode annotates; it never replaces a term or reorders a column.
  const verdictNote = explain
    ? `<span class="note">${escapeHtml(player.verdict_text)}</span>`
    : "";
  const availNote = explain
    ? `<span class="note">${escapeHtml(player.availability_text)}</span>`
    : "";
  const injury = player.injury_status
    ? `<span class="injury">${escapeHtml(player.injury_status)}</span>`
    : "";

  return `<tr class="row${drafted ? " drafted" : ""}" data-id="${escapeHtml(playerId(player))}">
  <td class="num">${player.rank}</td>
  <td><button class="mark" aria-label="Mark ${name} drafted">${drafted ? "↩" : "✓"}</button></td>
  <td class="name">${name} ${injury}${reason}</td>
  <td><span class="pos ${positionClass(player.position)}">${escapeHtml(player.position)}</span></td>
  <td class="num">${Number(player.adp).toFixed(1)}</td>
  <td class="num value ${player.verdict}">${formatValue(player.value)}${verdictNote}</td>
  <td class="avail ${player.availability}">${escapeHtml(player.availability)}${availNote}</td>
</tr>`;
}

export function boardHtml(players, opts = {}) {
  if (players.length === 0) {
    return `<tr><td colspan="7" class="empty">No players match this filter.</td></tr>`;
  }
  const drafted = opts.draftedIds ?? new Set();
  return players
    .map((p) => {
      const row = rowHtml(p, { ...opts, drafted: drafted.has(playerId(p)) });
      const brk = p.tier_break_after
        ? `<tr class="tier-break"><td colspan="7">Noticeable drop in quality below this line</td></tr>`
        : "";
      return row + brk;
    })
    .join("\n");
}
