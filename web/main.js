// DOM wiring only. Every computation lives in render.js, which is tested.
import { applyFilters, bestAvailable, boardHtml, playerId } from "./render.js";

const DRAFTED_KEY = "ffcoach.drafted";
const EXPLAIN_KEY = "ffcoach.explain";
const POSITIONS = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"];

const state = {
  players: [],
  league: null,
  position: "ALL",
  hideDrafted: false,
  explain: localStorage.getItem(EXPLAIN_KEY) === "true",
  draftedIds: new Set(JSON.parse(localStorage.getItem(DRAFTED_KEY) ?? "[]")),
};

const $ = (id) => document.getElementById(id);

function persist() {
  localStorage.setItem(DRAFTED_KEY, JSON.stringify([...state.draftedIds]));
  localStorage.setItem(EXPLAIN_KEY, String(state.explain));
}

function render() {
  const visible = applyFilters(state.players, state);
  $("board").innerHTML = boardHtml(visible, {
    explain: state.explain,
    draftedIds: state.draftedIds,
  });

  const next = bestAvailable(state.players, state.draftedIds);
  $("best").textContent = next
    ? `Best available: ${next.name} (${next.position}, ADP ${next.adp.toFixed(1)})`
    : "Every player on this board has been drafted.";
}

function buildChips() {
  $("positions").innerHTML = POSITIONS.map(
    (p) => `<button class="chip${p === state.position ? " on" : ""}" data-pos="${p}">${p}</button>`
  ).join("");
}

function wire() {
  $("positions").addEventListener("click", (e) => {
    const button = e.target.closest("[data-pos]");
    if (!button) return;
    state.position = button.dataset.pos;
    buildChips();
    render();
  });

  $("board").addEventListener("click", (e) => {
    const button = e.target.closest(".mark");
    if (!button) return;
    const id = e.target.closest("tr").dataset.id;
    state.draftedIds.has(id) ? state.draftedIds.delete(id) : state.draftedIds.add(id);
    persist();
    render();
  });

  $("hide-drafted").addEventListener("change", (e) => {
    state.hideDrafted = e.target.checked;
    render();
  });

  $("explain").addEventListener("change", (e) => {
    state.explain = e.target.checked;
    persist();
    render();
  });

  $("reset").addEventListener("click", () => {
    if (!confirm("Clear every drafted mark and start over?")) return;
    state.draftedIds.clear();
    persist();
    render();
  });
}

async function load() {
  try {
    const response = await fetch("data/board.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.players = payload.players;
    state.league = payload.league;

    $("league").textContent = `${payload.league.name} — Draft Board`;
    const bits = [
      `${payload.league.teams} teams`,
      payload.league.scoring,
      `you pick ${payload.league.my_pick}, then ${payload.league.next_pick}`,
    ];
    if (payload.stale) bits.push("data is stale — run ffcoach refresh");
    if (payload.unmatched?.length) bits.push(`${payload.unmatched.length} players unmatched`);
    $("status").textContent = bits.join(" · ");

    $("explain").checked = state.explain;
    buildChips();
    render();
  } catch (error) {
    $("status").textContent =
      `Could not load data/board.json (${error.message}). ` +
      `Run "uv run ffcoach build", and make sure you are viewing this through ` +
      `Live Server rather than opening the file directly.`;
  }
}

wire();
load();
