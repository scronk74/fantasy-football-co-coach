// Everything the Week page computes. No DOM here; week_main.js does that.
//
// The dividing line matters more on this page than the others, because what it
// renders is a safety decision. Nothing here re-derives one: `actionable`,
// `verb`, `status` and `blind_spots` all arrive from Python, where they are
// tested. A second implementation in JavaScript of "can I still fix this?"
// would answer a slightly different question on every reload.

import { escapeHtml } from "./render.js";

const KIND_LABEL = {
  empty_slot: "Empty",
  out: "Out",
  // "At risk", not "Questionable". The chip is this tool's read; the player's
  // own ESPN designation is spelled out in the reason line below it, so the
  // two are never confused for each other.
  at_risk: "At risk",
  bye: "Bye",
  bye_next_week: "Bye next week",
};

// UX rule 5: status is never carried by colour. Each of these is a word plus a
// mark, and the mark is a character rather than a coloured dot -- a red dot is
// invisible to a screen reader and to roughly one man in twelve.
const STATUS = {
  problems: { mark: "!", label: "Needs attention" },
  pre_draft: { mark: "-", label: "Before the draft" },
  unverified: { mark: "?", label: "Could not check everything" },
  all_clear: { mark: "+", label: "All clear" },
};

export function statusBadge(status) {
  const s = STATUS[status] ?? { mark: "?", label: status };
  return `<span class="badge s-${escapeHtml(status)}" title="${escapeHtml(s.label)}">` +
    `<span class="mark" aria-hidden="true">${s.mark}</span> ${escapeHtml(s.label)}</span>`;
}

export function headline(payload) {
  const fixes = actionable(payload);
  if (payload.status === "problems") {
    const total = (payload.findings ?? []).length;
    const noun = fixes.length === 1 ? "fix" : "fixes";
    if (fixes.length === 0) {
      return `${total} problem${total === 1 ? "" : "s"}, all past their deadline`;
    }
    return fixes.length < total
      ? `${fixes.length} ${noun} you can still make — ${total - fixes.length} past the deadline`
      : `${fixes.length} ${noun} you can still make`;
  }
  if (payload.status === "pre_draft") {
    return "Draft has not happened yet, so there is nothing to check";
  }
  if (payload.status === "unverified") {
    return "Nothing found — but this run could not see everything";
  }
  return "All clear — nothing to fix, and every check ran";
}

export function actionable(payload) {
  return (payload.findings ?? []).filter((f) => f.actionable);
}

// Most urgent first, then soonest deadline. Deliberately not "soonest first":
// an empty slot with a Sunday deadline still outranks a bye you have a week to
// solve, because severity is about how certain the zero is.
export function ordered(findings) {
  return [...findings].sort((a, b) => {
    if (a.actionable !== b.actionable) return a.actionable ? -1 : 1;
    if (a.severity !== b.severity) return a.severity - b.severity;
    const at = a.deadline ?? "";
    const bt = b.deadline ?? "";
    return at < bt ? -1 : at > bt ? 1 : 0;
  });
}

export function formatWhen(iso, timeZone) {
  if (!iso) return "no known deadline";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "no known deadline";
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short",
    timeZone: timeZone || undefined,
  }).format(when);
}

export function findingHtml(finding, timeZone) {
  // An empty slot has no player and no NFL team. "(nobody) ()" reads as missing
  // data rather than as the finding itself.
  const who = finding.player_name
    ? `${escapeHtml(finding.player_name)} <span class="team">${escapeHtml(finding.nfl_team)}</span>`
    : `<span class="nobody">no one in this slot</span>`;

  const action = finding.actionable
    ? `<span class="verb">${escapeHtml(finding.verb)}</span> by ` +
      `${escapeHtml(formatWhen(finding.deadline, timeZone))}`
    : `<span class="past">Past the deadline — nothing left to do</span>`;

  let options = `<li class="none">Nothing on the bench fits</li>`;
  if (finding.replacements?.length) {
    options = finding.replacements
      .map((n) => `<li>Start <strong>${escapeHtml(n)}</strong></li>`)
      .join("");
  } else if (finding.ir_candidates?.length) {
    // Not a replacement: ESPN will not start a player out of an IR slot, so
    // activating one is a prior action with its own roster-space cost.
    options = finding.ir_candidates
      .map(
        (n) =>
          `<li>On IR: <strong>${escapeHtml(n)}</strong> — activate first, ` +
          `ESPN will not start a player out of IR</li>`
      )
      .join("");
  }

  const estimated = finding.lock_is_estimated
    ? `<p class="estimated">Kickoff time is not published yet, so this deadline is an estimate.</p>`
    : "";

  return `<article class="finding k-${escapeHtml(finding.kind)}${
    finding.actionable ? "" : " done"
  }">
  <h3><span class="kind k-${escapeHtml(finding.kind)}">${escapeHtml(
    KIND_LABEL[finding.kind] ?? finding.kind
  )}</span> <span class="slot">${escapeHtml(finding.lineup_slot)}</span> ${who}</h3>
  <p class="reason">${escapeHtml(finding.reason)}</p>
  <p class="action">${action}</p>
  <ul class="options">${options}</ul>
  ${estimated}
</article>`;
}

export function blindSpotsHtml(payload) {
  const spots = payload.blind_spots ?? [];
  if (spots.length === 0) return "";
  // Above the findings, never below: an empty findings list plus a hidden
  // caveat is exactly the false reassurance CheckResult exists to prevent.
  return `<section class="blindspots">
  <h2>Could not check everything (${spots.length})</h2>
  <ul>${spots.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul>
</section>`;
}

export function deadlinesHtml(payload) {
  const rows = [];
  if (payload.next_lock) {
    rows.push(["Next slot freezes", formatWhen(payload.next_lock, payload.timezone)]);
  }
  if (payload.waiver_deadline) {
    rows.push(["Waivers next process", formatWhen(payload.waiver_deadline, payload.timezone)]);
  }
  if (rows.length === 0) return "";
  // Shown even in a clean week: "nothing is wrong" and "nothing is wrong yet"
  // are different sentences.
  return `<section class="deadlines"><h2>Coming up</h2><dl>${rows
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`)
    .join("")}</dl></section>`;
}

export function sourcesText(payload) {
  const sources = payload.sources ?? [];
  if (sources.length === 0) return "";
  return sources
    .map((s) => {
      const age = s.age_seconds > 0 ? `${ageText(s.age_seconds)} old` : "live";
      return `${s.name} ${s.stale ? `STALE, ${age}` : age}`;
    })
    .join(" · ");
}

function ageText(seconds) {
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export function weekHtml(payload) {
  const findings = ordered(payload.findings ?? []);
  return (
    blindSpotsHtml(payload) +
    (findings.length
      ? `<section class="queue">${findings
          .map((f) => findingHtml(f, payload.timezone))
          .join("")}</section>`
      : "") +
    deadlinesHtml(payload)
  );
}
