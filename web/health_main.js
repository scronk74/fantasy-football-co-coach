// DOM wiring only. Everything computed lives in health.js, which is tested.
import { navHtml } from "./nav.js";
import { escapeHtml } from "./render.js";
import { BAD, UNKNOWN, healthHtml, overall } from "./health.js";

const $ = (id) => document.getElementById(id);

const HEADLINE = {
  ok: "Everything is running.",
  bad: "Something needs attention.",
  unknown: "Running, but some things could not be checked.",
};

async function load() {
  $("nav").innerHTML = navHtml("health");
  try {
    const response = await fetch("api/health");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();

    const state = overall(payload);
    $("headline").textContent = HEADLINE[state] ?? HEADLINE.unknown;
    $("headline").className = `headline h-${state}`;
    $("host").textContent = `Viewed on ${payload.host} · built ${payload.generated_at}`;
    $("body").innerHTML = healthHtml(payload);
  } catch (error) {
    // A health page that cannot reach its own endpoint must not look healthy.
    $("headline").textContent = "This page could not read the health endpoint.";
    $("headline").className = `headline h-${BAD}`;
    $("body").innerHTML =
      `<p class="warn">${escapeHtml(error.message)}. This page needs ` +
      `<code>uv run ffcoach serve</code> — it asks the server for live state ` +
      `rather than reading a file, because a cached health panel is a ` +
      `contradiction.</p>`;
  }
}

async function refresh() {
  const button = $("refresh");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Checking…";
  try {
    const response = await fetch("api/refresh", { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (response.status === 429) {
      button.textContent = `Wait ${body.retry_after_seconds ?? "a moment"}s`;
    } else if (!response.ok || body.ok === false) {
      button.textContent = "Failed";
      $("note").textContent = body.message ?? body.error ?? "The check did not finish.";
    } else {
      $("note").textContent = body.message ?? "";
      await load();
      button.textContent = original;
    }
  } catch (error) {
    button.textContent = "Failed";
    $("note").textContent = error.message;
  } finally {
    // Re-enabled after the server-side cooldown, so the button cannot become a
    // load generator against ESPN's unofficial API.
    setTimeout(() => {
      button.disabled = false;
      button.textContent = original;
    }, 30000);
  }
}

$("refresh").addEventListener("click", refresh);
load();
