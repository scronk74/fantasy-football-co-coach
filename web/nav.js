// Shared site navigation. A future section (lineup, waivers, trades) adds
// one entry here and every page picks up the link -- no per-page markup to
// hunt down and update.

export const PAGES = [
  { id: "draft", label: "Draft Board", href: "index.html" },
  { id: "league", label: "My League", href: "league.html" },
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
