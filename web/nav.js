// Shared site navigation. A future section (lineup, waivers, trades) adds
// one entry here and every page picks up the link -- no per-page markup to
// hunt down and update.

export const PAGES = [
  // The front door is this week's problems (D-051). The draft board moved off
  // index.html on 2026-09-04: it is legacy scaffolding (D-050), and the app
  // opening on it meant the first thing you saw was the one page you did not
  // want.
  { id: "week", label: "This Week", href: "index.html" },
  { id: "league", label: "My League", href: "league.html" },
  { id: "draft", label: "Draft Board", href: "draft.html" },
  { id: "alerts", label: "Alerts", href: "alerts.html" },
  { id: "health", label: "Health", href: "health.html" },
];

export function navHtml(currentPageId) {
  return PAGES.map((page) => {
    const current = page.id === currentPageId;
    return (
      `<a class="navlink${current ? " current" : ""}" href="${page.href}"` +
      `${current ? ' aria-current="page"' : ""}>${page.label}</a>`
    );
  }).join("");
}
