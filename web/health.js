// Everything the health page computes. No DOM here; health_main.js does that.
//
// The rule this page lives by: **unknown is not healthy.** Every field that
// could not be determined renders as its own state, never as a green tick. A
// panel that says "yes" because it failed to ask is the exact failure it
// exists to catch.

import { escapeHtml } from "./render.js";

export const OK = "ok";
export const BAD = "bad";
export const UNKNOWN = "unknown";

// UX rule 5: a word and a mark, never colour alone.
const MARKS = { [OK]: "+", [BAD]: "!", [UNKNOWN]: "?" };

export function ageText(seconds) {
  if (seconds === null || seconds === undefined) return "unknown";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function rowHtml({ state, label, detail }) {
  const mark = MARKS[state] ?? MARKS[UNKNOWN];
  return `<div class="hrow h-${escapeHtml(state)}">
  <span class="hmark" aria-hidden="true">${mark}</span>
  <span class="hlabel">${escapeHtml(label)}</span>
  <span class="hdetail">${escapeHtml(detail)}</span>
</div>`;
}

// --- one row per thing that can be wrong ---

export function alertsRow(payload) {
  const a = payload.alerts ?? {};
  if (!a.configured) {
    return { state: BAD, label: "Alerts", detail: a.reason || "not configured" };
  }
  if (a.prefs_error) {
    // An unreadable alerts.yaml stops `check` sending at all, so it belongs
    // here and not on the Alerts page alone.
    return { state: BAD, label: "Alerts", detail: a.prefs_error };
  }
  // D4 made silence something you can ask for. It must still be visible, or
  // it is indistinguishable from the channel being broken -- which is the one
  // confusion this whole panel exists to prevent.
  if (a.muted_until) {
    return { state: UNKNOWN, label: "Alerts", detail: `muted until ${a.muted_until}` };
  }
  const off = (a.kinds_off ?? []).length;
  if (off) {
    return {
      state: UNKNOWN,
      label: "Alerts",
      detail: `${a.channel} configured · ${off} kind${off === 1 ? "" : "s"} switched off`,
    };
  }
  return { state: OK, label: "Alerts", detail: `${a.channel} configured` };
}

export function heartbeatRow(payload) {
  // Stated as an exposure, not a missing option: the difference between "the
  // machine died and I was told" and "the machine died".
  return (payload.heartbeat ?? {}).configured
    ? { state: OK, label: "Heartbeat", detail: "off-host monitor configured" }
    : {
        state: BAD,
        label: "Heartbeat",
        detail: "not configured — if this machine dies, nothing will tell you",
      };
}

export function schedulerRow(payload) {
  const s = payload.scheduler ?? {};
  if (s.loaded === true) {
    return {
      state: OK,
      label: "Scheduler",
      detail: `loaded, every ${s.interval_minutes} minutes`,
    };
  }
  if (s.loaded === false) {
    return {
      state: BAD,
      label: "Scheduler",
      detail: s.plist_exists
        ? "installed but not loaded — nothing is running the check"
        : "not installed — nothing is running the check",
    };
  }
  // null: we could not ask. Not the same as "no".
  return { state: UNKNOWN, label: "Scheduler", detail: "could not be determined here" };
}

export function alertingHostRow(payload) {
  const s = payload.scheduler ?? {};
  if (!s.host) {
    return { state: UNKNOWN, label: "Alerting host", detail: "not recorded — any machine here may alert" };
  }
  return s.is_this_machine
    ? { state: OK, label: "Alerting host", detail: `${s.host} (this machine)` }
    : {
        state: UNKNOWN,
        label: "Alerting host",
        detail: `${s.host} — this machine will not send or ping`,
      };
}

export function watchdogRow(payload) {
  const w = payload.watchdog ?? {};
  return w.tripped
    ? { state: BAD, label: "Watchdog", detail: w.reason }
    : { state: OK, label: "Watchdog", detail: "the tool is running normally" };
}

export function lastRunRow(payload) {
  const r = payload.last_run;
  if (!r) return { state: BAD, label: "Last run", detail: "never — nothing has run a check yet" };
  const bits = [ageText(r.age_seconds)];
  if (r.status) bits.push(r.status);
  if (r.findings !== null && r.findings !== undefined) bits.push(`${r.findings} found`);
  if (r.sent) bits.push(`${r.sent} sent`);
  if (r.suppressed_host) bits.push("not the alerting host, so nothing was sent");
  if (r.error) bits.push(r.error);
  return { state: r.ok ? OK : BAD, label: "Last run", detail: bits.join(" · ") };
}

export function lastSuccessRow(payload) {
  // Reported separately and always. A recent *run* proves the scheduler is
  // alive; only a recent *success* proves it would have told you anything.
  const r = payload.last_success;
  if (!r) return { state: BAD, label: "Last success", detail: "never — no run has ever completed" };
  return { state: OK, label: "Last success", detail: ageText(r.age_seconds) };
}

export function rows(payload) {
  return [
    lastRunRow(payload),
    lastSuccessRow(payload),
    watchdogRow(payload),
    schedulerRow(payload),
    alertingHostRow(payload),
    alertsRow(payload),
    heartbeatRow(payload),
  ];
}

export function overall(payload) {
  const states = rows(payload).map((r) => r.state);
  if (states.includes(BAD)) return BAD;
  return states.includes(UNKNOWN) ? UNKNOWN : OK;
}

export function sourcesHtml(payload) {
  const sources = payload.last_run?.sources ?? [];
  if (sources.length === 0) return "";
  const items = sources
    .map((s) => {
      const age = s.age_seconds > 0 ? ageText(s.age_seconds) : "live";
      const stale = s.stale ? " <strong>STALE</strong>" : "";
      return `<li>${escapeHtml(s.name)} — ${escapeHtml(age)}${stale}</li>`;
    })
    .join("");
  return `<section class="sources"><h2>Data sources, as of the last run</h2><ul>${items}</ul></section>`;
}

export function setupHtml(payload) {
  const missing = (payload.setup ?? []).filter((s) => !s.done);
  if (missing.length === 0) return "";
  return `<section class="setup"><h2>Setup: ${missing.length} step(s) left</h2><ul>${missing
    .map((s) => `<li>${escapeHtml(s.what)}<br><code>${escapeHtml(s.fix)}</code></li>`)
    .join("")}</ul></section>`;
}

export function healthHtml(payload) {
  return (
    `<section class="checks">${rows(payload).map(rowHtml).join("")}</section>` +
    setupHtml(payload) +
    sourcesHtml(payload)
  );
}
