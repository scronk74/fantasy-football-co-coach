# Fantasy Football Co-Coach

A draft board, plus your ESPN league's teams and rosters.

## Setup

```bash
uv sync
cp league.example.yaml league.yaml
# edit league.yaml with your league's real settings
```

### ESPN league access (optional, for the "My League" page)

The league runs on ESPN. If it's private, you need two cookies from a
logged-in browser session -- log into fantasy.espn.com, open dev tools ->
Application/Storage -> Cookies -> espn.com, and copy `espn_s2` and `SWID`.

```bash
cp espn.example.yaml espn.yaml
# edit espn.yaml with your league_id, season, espn_s2, and swid
```

`espn.yaml` is gitignored, same as `league.yaml` -- never commit it, those
cookies authenticate as you. There's no documented expiry; when they stop
working, `ffcoach league` will say so and you repeat the steps above.

No league yet? `ffcoach league --fixture tests/fixtures/espn_league.json`
renders the page against sample data with no ESPN access at all.

## Use

```bash
uv run ffcoach check      # this week's lineup: what to fix, and by when
uv run ffcoach league     # fetch ESPN league data and write web/data/league.json
uv run ffcoach build      # fetch ADP data and write web/data/board.json
uv run ffcoach doctor     # show what config and cache it sees
```

Then serve the pages and open the link it prints:

```bash
uv run ffcoach serve      # http://127.0.0.1:8765/
```

`index.html` is this week's action queue, `league.html` is teams and rosters,
`draft.html` is the (legacy) draft board -- all linked from the nav bar at the
top of each page. Opening a file directly will not work: `file://` blocks
loading the JSON.

## Tests

```bash
uv run pytest    # python
npm test         # browser logic (no npm packages are installed)
```

## Design

See `docs/superpowers/specs/2026-08-20-fantasy-football-co-coach-design.md`.
