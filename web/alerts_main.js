// DOM wiring only. Everything computed lives in alerts.js, which is tested.
import { navHtml } from "./nav.js";
import { escapeHtml } from "./render.js";
import {
  MUTE_PRESETS, kindsHtml, muteInstant, payloadFrom, quietHtml, summary, whenText,
} from "./alerts.js";

const $ = (id) => document.getElementById(id);

let pending = null;   // the mute instant chosen but not yet saved
let writable = true;

function renderMute(payload) {
  const chosen = pending !== null ? pending : payload.mute_until;
  const active = chosen && new Date(chosen) > new Date();
  $("mute-state").textContent = active
    ? `Muted until ${whenText(chosen)}${pending !== null ? " (unsaved)" : ""}`
    : "Not muted.";
  $("mute-buttons").innerHTML =
    MUTE_PRESETS.map(
      (preset) =>
        `<button type="button" class="mark" data-mute="${preset.id}">${preset.label}</button> `,
    ).join("") +
    (active ? `<button type="button" class="mark" data-mute="off">Unmute</button>` : "");

  for (const button of $("mute-buttons").querySelectorAll("[data-mute]")) {
    button.addEventListener("click", () => {
      const id = button.dataset.mute;
      pending = id === "off" ? "" : muteInstant(new Date(), id);
      renderMute(payload);
    });
  }
}

async function load() {
  $("nav").innerHTML = navHtml("alerts");
  try {
    const response = await fetch("api/alerts");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    pending = null;
    writable = payload.writable !== false;

    $("headline").textContent = summary(payload);
    $("kinds").innerHTML = kindsHtml(payload);
    $("quiet").innerHTML = quietHtml(payload);
    renderMute(payload);
    $("body").hidden = false;

    const where = payload.exists
      ? `Reading ${payload.path}`
      : `${payload.path} does not exist yet — these are the defaults`;
    $("where").textContent = payload.error ? `${payload.path}: ${payload.error}` : where;

    if (!writable) {
      // Said before anything is edited, not as a 403 after the fact.
      $("save").disabled = true;
      $("note").textContent =
        "Read-only while serving to the network. Restart without --lan to change these.";
    }
  } catch (error) {
    $("headline").textContent = "This page could not read your alert preferences.";
    $("body").innerHTML =
      `<p class="warn">${escapeHtml(error.message)}. This page needs ` +
      `<code>uv run ffcoach serve</code>.</p>`;
    $("body").hidden = false;
  }
}

function collect() {
  const kinds = {};
  for (const box of $("kinds").querySelectorAll('input[name="kind"]')) {
    kinds[box.value] = box.checked;
  }
  return payloadFrom({
    kinds,
    quietEnabled: $("quiet-enabled").checked,
    quietStart: Number($("quiet-start").value),
    quietEnd: Number($("quiet-end").value),
    // undefined leaves the stored mute alone; "" clears it.
    muteUntil: pending === null ? undefined : pending,
  });
}

async function save() {
  const button = $("save");
  button.disabled = true;
  $("note").textContent = "Saving…";
  try {
    const response = await fetch("api/alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      $("note").textContent = body.message ?? body.error ?? "Not saved.";
    } else {
      $("note").textContent = body.message ?? "Saved.";
      await load();
    }
  } catch (error) {
    $("note").textContent = error.message;
  } finally {
    button.disabled = !writable;
  }
}

$("save").addEventListener("click", save);
load();
