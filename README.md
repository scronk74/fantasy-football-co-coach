# Fantasy Football Co-Coach

Phase 1: a draft board for your league's scoring rules.

## Setup

```bash
uv sync
cp league.example.yaml league.yaml
# edit league.yaml with your league's real settings
```

## Use

```bash
uv run ffcoach build     # fetch data and write web/data/board.json
uv run ffcoach doctor    # show what config and cache it sees
```

Then open `web/index.html` with VS Code Live Server. Opening the file
directly will not work: `file://` blocks loading the JSON.

## Tests

```bash
uv run pytest    # python
npm test         # browser logic (no npm packages are installed)
```

## Design

See `docs/superpowers/specs/2026-08-20-fantasy-football-co-coach-design.md`.
