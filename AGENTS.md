# AGENTS.md

**Reviewing this repo?** Read [`CODEX_README.md`](CODEX_README.md) first. It says what feedback is
wanted, what is already known to be broken or unverified (so you do not spend the budget
rediscovering it), the invariants worth trying to break, and the six areas to cover.

**Working in this repo?** Read [`CLAUDE.md`](CLAUDE.md). It carries the architecture, the source-module
template every new source must follow, the traps in the player-identity data, the browser
compute/DOM split, and the UX rules that have executable tests behind them. Ignoring it produces
changes that fail the suite in non-obvious ways.

Plans, decisions, and roadblocks live in [`ROADMAP.md`](ROADMAP.md); design docs in
`docs/superpowers/specs/`.

Verify any change with `uv run pytest` **and** `npm test`. Both run fully offline with no
credentials.
