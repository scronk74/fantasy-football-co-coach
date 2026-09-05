// Everything the Alerts page computes. No DOM here; alerts_main.js does that.
//
// The page controls what may *send*. It cannot switch detection off, and it
// deliberately cannot reach the ntfy topic: that lives in notify.yaml, which
// this endpoint neither reads nor writes, so there is no field here to leak.

import { escapeHtml } from "./render.js";

// Presets rather than a free-text instant. "Mute until I type a timestamp" is
// a control nobody uses at 9am on a Sunday, which is the only time it matters.
export const MUTE_PRESETS = [
  { id: "1h", label: "1 hour" },
  { id: "3h", label: "3 hours" },
  { id: "tomorrow", label: "Until 8am tomorrow" },
];

// An instant, never a flag. Every preset lands on a moment that arrives on its
// own, so a mute set in a hurry cannot outlive the reason for it.
export function muteInstant(now, id) {
  const when = new Date(now.getTime());
  if (id === "1h") when.setHours(when.getHours() + 1);
  else if (id === "3h") when.setHours(when.getHours() + 3);
  else if (id === "tomorrow") {
    when.setHours(8, 0, 0, 0);
    if (when <= now) when.setDate(when.getDate() + 1);
  } else return null;
  return when.toISOString();
}

export function whenText(iso) {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleString(undefined, {
    weekday: "short", hour: "numeric", minute: "2-digit",
  });
}

// The one sentence at the top. Ordered by what would surprise you most: a
// blanket mute hides everything below it, so it is said first.
export function summary(payload, now = new Date()) {
  const muted = payload.mute_until && new Date(payload.mute_until) > now;
  if (muted) return `Muted until ${whenText(payload.mute_until)} — nothing will be sent.`;
  const off = (payload.kinds ?? []).filter((k) => !k.enabled);
  if (off.length === 0) return "Every kind of problem can reach you.";
  const names = off.map((k) => k.name).join(", ");
  return `${off.length} of ${(payload.kinds ?? []).length} switched off: ${names}.`;
}

export function kindsHtml(payload) {
  const rows = (payload.kinds ?? []).map((kind) => {
    const checked = kind.enabled ? " checked" : "";
    return `<label class="kindrow">
  <input type="checkbox" name="kind" value="${escapeHtml(kind.name)}"${checked}>
  <span class="kindlabel">${escapeHtml(kind.label)}</span>
  <code class="kindname">${escapeHtml(kind.name)}</code>
</label>`;
  });
  return rows.join("\n");
}

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

function hourOptions(selected) {
  return HOURS.map(
    (hour) =>
      `<option value="${hour}"${hour === selected ? " selected" : ""}>` +
      `${String(hour).padStart(2, "0")}:00</option>`,
  ).join("");
}

export function quietHtml(payload) {
  const quiet = payload.quiet_hours ?? {};
  const checked = quiet.enabled ? " checked" : "";
  return `<label class="kindrow">
  <input type="checkbox" id="quiet-enabled"${checked}>
  <span class="kindlabel">Hold alerts overnight</span>
</label>
<p class="quietrow">
  from <select id="quiet-start">${hourOptions(quiet.start ?? 23)}</select>
  to <select id="quiet-end">${hourOptions(quiet.end ?? 8)}</select>
</p>`;
}

// Reads back exactly what the endpoint accepts, so a rejected save names a
// field the user can see on this page.
export function payloadFrom({ kinds, quietEnabled, quietStart, quietEnd, muteUntil }) {
  return {
    kinds,
    quiet_hours: { enabled: quietEnabled, start: quietStart, end: quietEnd },
    mute_until: muteUntil ?? "",
  };
}
