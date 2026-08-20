# Phase 1 — Draft Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A draft board the user opens during their fantasy draft that ranks every available player for their league's scoring rules, shows who is a bargain or a reach, estimates who will still be there at their next pick, and recomputes live as players come off the board.

**Architecture:** Deterministic Python fetches and caches free ADP and player data, computes rankings and tiers as pure tested functions, and writes a single JSON file. A dependency-free browser page renders that JSON, with all client-side logic in pure ES-module functions tested by `node --test`. No server, no build step, no npm packages.

**Tech Stack:** Python 3.12 (via `uv`), pytest, SQLite (stdlib), `httpx`, `PyYAML`, vanilla ES modules, `node --test` (Node 26).

**Spec:** `docs/superpowers/specs/2026-08-20-fantasy-football-co-coach-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.12**, pinned via `uv`. Never invoke the system `python3` (it is 3.7).
- **No npm packages, ever.** Node is installed solely for its built-in test runner. The browser page loads no external resource of any kind.
- **`src/ffcoach/model/` is pure.** No network, no filesystem, no clock, no randomness. Every function is deterministic given its arguments.
- **No live network in tests.** All HTTP is served from committed fixtures.
- **Terminology is never renamed.** The UI says "ADP", not "Typical pick". Terms are annotated via explain mode, never replaced. (Spec UX rule 1.)
- **Explain mode is annotation-only.** Toggling it must never change layout, column order, or row order — only what is annotated. (Spec UX rule 2.)
- **Every recommendation states its reason inline, in both modes.** No unexplained highlight, badge, or flag. (Spec UX rule 4.)
- **Nothing about league format is hardcoded.** Scoring, roster slots, and team count come from config. Never render a dollar figure. (Spec UX rule 5.)
- **Scoring format values** are exactly `standard`, `half-ppr`, `ppr`.
- **Position values** are exactly `QB`, `RB`, `WR`, `TE`, `K`, `DEF`.
- Commit after every task.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, deps, pytest config |
| `.python-version` | Pins 3.12 for uv |
| `src/ffcoach/config.py` | Load/validate `league.yaml` into a `LeagueConfig` |
| `src/ffcoach/cache.py` | SQLite key/value cache with per-entry TTL |
| `src/ffcoach/sources/ffcalc.py` | Fetch ADP from Fantasy Football Calculator |
| `src/ffcoach/sources/sleeper.py` | Fetch player metadata and injury status |
| `src/ffcoach/sources/match.py` | Join FFC and Sleeper records |
| `src/ffcoach/model/players.py` | `Player` dataclass — the unit every layer passes around |
| `src/ffcoach/model/tiers.py` | Group ranked players into tiers by ADP gaps |
| `src/ffcoach/model/value.py` | Bargain/Fair/Reach verdict and availability |
| `src/ffcoach/advisors/draft.py` | Assemble the board from config + players |
| `src/ffcoach/report/build.py` | Write `web/data/board.json` |
| `src/ffcoach/cli.py` | `ffcoach refresh` / `build` / `doctor` |
| `web/index.html` | Static shell |
| `web/render.js` | Pure render/filter/sort/recompute functions |
| `web/render.test.js` | `node --test` suite |
| `web/main.js` | DOM wiring only |
| `web/style.css` | Styles, light and dark |

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `.python-version`, `package.json`, `src/ffcoach/__init__.py`, `tests/test_smoke.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: `ffcoach.__version__` (`str`); a working `uv run pytest` and `node --test`

- [ ] **Step 1: Pin Python and create the package files**

`.python-version`:
```
3.12
```

`pyproject.toml`:
```toml
[project]
name = "ffcoach"
version = "0.1.0"
description = "Fantasy football co-coach"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "PyYAML>=6.0",
]

[project.scripts]
ffcoach = "ffcoach.cli:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ffcoach"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`package.json` — declares ES modules so `node --test` treats `.js` as modules. It has no dependencies and never will:
```json
{
  "name": "ffcoach-web",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test web/*.test.js"
  }
}
```

`src/ffcoach/__init__.py`:
```python
__version__ = "0.1.0"
```

Append to `.gitignore`:
```
web/data/
*.sqlite3
.venv/
```

- [ ] **Step 2: Write the failing test**

`tests/test_smoke.py`:
```python
import sys

import ffcoach


def test_version_is_exposed():
    assert ffcoach.__version__ == "0.1.0"


def test_running_on_python_312_or_newer():
    assert sys.version_info >= (3, 12)
```

- [ ] **Step 3: Run it and watch it fail**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach'` (the venv does not exist yet).

- [ ] **Step 4: Create the environment**

Run:
```bash
uv sync
```
Expected: uv downloads CPython 3.12, creates `.venv/`, installs `httpx`, `PyYAML`, `pytest`, and `ffcoach` itself in editable mode.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 6: Verify the Node runner**

Create `web/render.js`:
```js
export function ping() {
  return "pong";
}
```

Create `web/render.test.js`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { ping } from "./render.js";

test("module loading works", () => {
  assert.equal(ping(), "pong");
});
```

Run: `npm test`
Expected: `# pass 1`, `# fail 0`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version package.json .gitignore src tests web
git commit -m "chore: scaffold python and node test harnesses"
```

---

## Task 2: League configuration

**Files:**
- Create: `src/ffcoach/config.py`, `league.example.yaml`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `LeagueConfig` frozen dataclass with fields `name: str`, `teams: int`, `scoring: str`, `roster: dict[str, int]`, `my_pick: int`, `season: int`
  - `LeagueConfig.starters_total` → `int`
  - `LeagueConfig.next_pick_after(pick: int) -> int | None` — snake-draft arithmetic
  - `load_config(path: Path) -> LeagueConfig`
  - `ConfigError(Exception)`

The user does not yet know their league's real settings. The example file ships with commented defaults they replace later; nothing downstream may hardcode these values.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import textwrap

import pytest

from ffcoach.config import ConfigError, LeagueConfig, load_config


def write(tmp_path, body):
    p = tmp_path / "league.yaml"
    p.write_text(textwrap.dedent(body))
    return p


VALID = """
    name: Test League
    season: 2026
    teams: 12
    scoring: ppr
    my_pick: 7
    roster:
      QB: 1
      RB: 2
      WR: 2
      TE: 1
      FLEX: 1
      K: 1
      DEF: 1
      BN: 6
"""


def test_loads_valid_config(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.name == "Test League"
    assert cfg.teams == 12
    assert cfg.scoring == "ppr"
    assert cfg.my_pick == 7
    assert cfg.roster["FLEX"] == 1


def test_starters_total_excludes_bench(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.starters_total == 9


def test_next_pick_uses_snake_order(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    # 12 teams, picking 7th: round 1 = 7, round 2 = 18, round 3 = 31.
    assert cfg.next_pick_after(7) == 18
    assert cfg.next_pick_after(18) == 31
    assert cfg.next_pick_after(31) == 42


def test_next_pick_returns_none_past_final_round(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    last = cfg.teams * cfg.rounds
    assert cfg.next_pick_after(last) is None


def test_rejects_unknown_scoring_format(tmp_path):
    bad = VALID.replace("scoring: ppr", "scoring: superflex")
    with pytest.raises(ConfigError, match="scoring must be one of"):
        load_config(write(tmp_path, bad))


def test_rejects_pick_outside_team_count(tmp_path):
    bad = VALID.replace("my_pick: 7", "my_pick: 13")
    with pytest.raises(ConfigError, match="my_pick must be between"):
        load_config(write(tmp_path, bad))


def test_rejects_unknown_roster_slot(tmp_path):
    bad = VALID.replace("  K: 1", "  PUNTER: 1")
    with pytest.raises(ConfigError, match="unknown roster slot"):
        load_config(write(tmp_path, bad))


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.config'`.

- [ ] **Step 3: Implement**

`src/ffcoach/config.py`:
```python
"""League configuration: the single source of truth for format-specific rules.

Nothing downstream may hardcode scoring, roster shape, or team count.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

SCORING_FORMATS = ("standard", "half-ppr", "ppr")
STARTER_SLOTS = ("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")
BENCH_SLOT = "BN"
VALID_SLOTS = STARTER_SLOTS + (BENCH_SLOT,)


class ConfigError(Exception):
    """Raised when league.yaml is missing, malformed, or invalid."""


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    season: int
    teams: int
    scoring: str
    my_pick: int
    roster: dict[str, int]

    @property
    def starters_total(self) -> int:
        return sum(n for slot, n in self.roster.items() if slot != BENCH_SLOT)

    @property
    def rounds(self) -> int:
        return sum(self.roster.values())

    def next_pick_after(self, pick: int) -> int | None:
        """Next overall pick number in a snake draft, or None past the end.

        In a snake, the order reverses every round, so your next pick is
        always mirrored around the turn. Both the odd->even and even->odd
        transitions reduce to the same expression.
        """
        rnd = (pick - 1) // self.teams + 1
        if rnd >= self.rounds:
            return None
        pos_in_round = (pick - 1) % self.teams + 1
        return rnd * self.teams + (self.teams - pos_in_round + 1)


def load_config(path: Path) -> LeagueConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"league config not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    missing = {"name", "season", "teams", "scoring", "my_pick", "roster"} - raw.keys()
    if missing:
        raise ConfigError(f"missing required keys: {', '.join(sorted(missing))}")

    scoring = str(raw["scoring"]).lower()
    if scoring not in SCORING_FORMATS:
        raise ConfigError(f"scoring must be one of {SCORING_FORMATS}, got {scoring!r}")

    roster = raw["roster"] or {}
    for slot in roster:
        if slot not in VALID_SLOTS:
            raise ConfigError(f"unknown roster slot {slot!r}; valid: {VALID_SLOTS}")

    teams = int(raw["teams"])
    my_pick = int(raw["my_pick"])
    if not 1 <= my_pick <= teams:
        raise ConfigError(f"my_pick must be between 1 and {teams}, got {my_pick}")

    return LeagueConfig(
        name=str(raw["name"]),
        season=int(raw["season"]),
        teams=teams,
        scoring=scoring,
        my_pick=my_pick,
        roster={str(k): int(v) for k, v in roster.items()},
    )
```

- [ ] **Step 4: Write the example config**

`league.example.yaml`:
```yaml
# Copy to league.yaml and replace with your league's real settings.
# Ask your commissioner for the scoring breakdown and roster rules.

name: My League
season: 2026

# How many teams. Determines how deep the talent pool goes.
teams: 12

# Scoring format. This matters a lot: PPR awards a point per reception,
# which moves receivers and pass-catching running backs up the board.
#   standard  - no points for receptions
#   half-ppr  - 0.5 per reception
#   ppr       - 1.0 per reception
scoring: ppr

# Your draft slot, 1 through <teams>.
my_pick: 7

# Starting lineup plus bench. FLEX accepts RB/WR/TE.
roster:
  QB: 1
  RB: 2
  WR: 2
  TE: 1
  FLEX: 1
  K: 1
  DEF: 1
  BN: 6
```

- [ ] **Step 5: Run and watch it pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/ffcoach/config.py tests/test_config.py league.example.yaml
git commit -m "feat: league config loading and validation"
```

---

## Task 3: SQLite cache

**Files:**
- Create: `src/ffcoach/cache.py`, `tests/test_cache.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Cache(path: Path)` with `get(key: str) -> str | None`, `set(key: str, value: str, ttl_seconds: int) -> None`, `get_stale(key: str) -> tuple[str, float] | None`, `age_seconds(key: str) -> float | None`
  - Constructor accepts `now: Callable[[], float] = time.time` so tests control the clock.

`get` returns `None` once expired. `get_stale` ignores expiry and returns the value plus its age — this is what lets a failed fetch fall back to old data rather than crashing.

- [ ] **Step 1: Write the failing tests**

`tests/test_cache.py`:
```python
from ffcoach.cache import Cache


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make(tmp_path, clock):
    return Cache(tmp_path / "c.sqlite3", now=clock)


def test_returns_none_for_missing_key(tmp_path):
    assert make(tmp_path, FakeClock()).get("nope") is None


def test_round_trips_a_value(tmp_path):
    c = make(tmp_path, FakeClock())
    c.set("k", "hello", ttl_seconds=60)
    assert c.get("k") == "hello"


def test_expires_after_ttl(tmp_path):
    clock = FakeClock()
    c = make(tmp_path, clock)
    c.set("k", "hello", ttl_seconds=60)
    clock.advance(59)
    assert c.get("k") == "hello"
    clock.advance(2)
    assert c.get("k") is None


def test_get_stale_survives_expiry(tmp_path):
    clock = FakeClock()
    c = make(tmp_path, clock)
    c.set("k", "hello", ttl_seconds=10)
    clock.advance(500)
    assert c.get("k") is None
    value, age = c.get_stale("k")
    assert value == "hello"
    assert age == 500


def test_set_overwrites_and_resets_age(tmp_path):
    clock = FakeClock()
    c = make(tmp_path, clock)
    c.set("k", "old", ttl_seconds=10)
    clock.advance(5)
    c.set("k", "new", ttl_seconds=10)
    assert c.get("k") == "new"
    assert c.age_seconds("k") == 0


def test_persists_across_instances(tmp_path):
    clock = FakeClock()
    make(tmp_path, clock).set("k", "durable", ttl_seconds=60)
    assert make(tmp_path, clock).get("k") == "durable"


def test_age_of_missing_key_is_none(tmp_path):
    assert make(tmp_path, FakeClock()).age_seconds("nope") is None
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.cache'`.

- [ ] **Step 3: Implement**

`src/ffcoach/cache.py`:
```python
"""SQLite-backed cache with per-entry TTL.

Stale reads are a feature: a failed fetch on a Sunday morning should serve
old data with a visible staleness marker, not crash.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    stored_at  REAL NOT NULL,
    ttl        REAL NOT NULL
)
"""


class Cache:
    def __init__(self, path: Path, now: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._conn.execute(
            "INSERT INTO entries (key, value, stored_at, ttl) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "stored_at=excluded.stored_at, ttl=excluded.ttl",
            (key, value, self._now(), float(ttl_seconds)),
        )
        self._conn.commit()

    def _row(self, key: str) -> tuple[str, float, float] | None:
        cur = self._conn.execute(
            "SELECT value, stored_at, ttl FROM entries WHERE key = ?", (key,)
        )
        return cur.fetchone()

    def get(self, key: str) -> str | None:
        row = self._row(key)
        if row is None:
            return None
        value, stored_at, ttl = row
        if self._now() - stored_at > ttl:
            return None
        return value

    def get_stale(self, key: str) -> tuple[str, float] | None:
        row = self._row(key)
        if row is None:
            return None
        value, stored_at, _ = row
        return value, self._now() - stored_at

    def age_seconds(self, key: str) -> float | None:
        row = self._row(key)
        if row is None:
            return None
        return self._now() - row[1]
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_cache.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ffcoach/cache.py tests/test_cache.py
git commit -m "feat: sqlite cache with ttl and stale fallback"
```

---

## Task 4: The Player model

**Files:**
- Create: `src/ffcoach/model/__init__.py`, `src/ffcoach/model/players.py`, `tests/test_players.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Player` frozen dataclass: `name: str`, `position: str`, `team: str`, `adp: float`, `stdev: float`, `bye: int | None`, `times_drafted: int`, `injury_status: str | None`, `sleeper_id: str | None`
  - `normalize_name(name: str) -> str`
  - `POSITIONS: tuple[str, ...]`

`normalize_name` is the join key between two sources with unrelated ID spaces. It must strip punctuation, suffixes, case, and whitespace.

- [ ] **Step 1: Write the failing tests**

`tests/test_players.py`:
```python
import pytest

from ffcoach.model.players import POSITIONS, Player, normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ja'Marr Chase", "jamarrchase"),
        ("JA'MARR CHASE", "jamarrchase"),
        ("Ja Marr  Chase", "jamarrchase"),
        ("Kenneth Walker III", "kennethwalker"),
        ("Michael Pittman Jr.", "michaelpittman"),
        ("Marvin Harrison Jr", "marvinharrison"),
        ("Amon-Ra St. Brown", "amonrastbrown"),
        ("  Bijan Robinson  ", "bijanrobinson"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_positions_are_the_agreed_set():
    assert POSITIONS == ("QB", "RB", "WR", "TE", "K", "DEF")


def test_player_is_hashable_and_frozen():
    p = Player(
        name="Bijan Robinson",
        position="RB",
        team="ATL",
        adp=1.7,
        stdev=0.8,
        bye=11,
        times_drafted=1154,
        injury_status=None,
        sleeper_id="9509",
    )
    assert hash(p)
    with pytest.raises(AttributeError):
        p.adp = 2.0


def test_player_key_matches_normalized_name_and_position():
    p = Player(
        name="Kenneth Walker III",
        position="RB",
        team="SEA",
        adp=30.2,
        stdev=5.0,
        bye=8,
        times_drafted=400,
        injury_status=None,
        sleeper_id=None,
    )
    assert p.key == ("kennethwalker", "RB")
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_players.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.model'`.

- [ ] **Step 3: Implement**

`src/ffcoach/model/__init__.py`:
```python
```
(empty file)

`src/ffcoach/model/players.py`:
```python
"""The Player record every layer passes around.

Pure module: no network, no filesystem, no clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

_SUFFIXES = ("jr", "sr", "ii", "iii", "iv", "v")
_NON_ALPHA = re.compile(r"[^a-z]+")


def normalize_name(name: str) -> str:
    """Collapse a display name to a stable join key.

    Two sources with unrelated ID spaces are matched on this plus position,
    so it must survive punctuation, casing, spacing, and generational
    suffixes.
    """
    lowered = name.lower().strip()
    words = [_NON_ALPHA.sub("", w) for w in lowered.split()]
    words = [w for w in words if w]
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return "".join(words)


@dataclass(frozen=True)
class Player:
    name: str
    position: str
    team: str
    adp: float
    stdev: float
    bye: int | None
    times_drafted: int
    injury_status: str | None
    sleeper_id: str | None

    @property
    def key(self) -> tuple[str, str]:
        return normalize_name(self.name), self.position
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_players.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ffcoach/model tests/test_players.py
git commit -m "feat: player model and name normalization"
```

---

## Task 5: Tiers

**Files:**
- Create: `src/ffcoach/model/tiers.py`, `tests/test_tiers.py`

**Interfaces:**
- Consumes: `Player` from Task 4
- Produces: `assign_tiers(players: Sequence[Player], gap_multiplier: float = 1.5) -> list[int]`

Returns one tier number per player, in the same order, starting at 1. A new tier begins where the ADP gap to the previous player exceeds `gap_multiplier` times the mean gap so far. This is what "a noticeable drop in quality" means — a cliff, not a fixed bucket size.

- [ ] **Step 1: Write the failing tests**

`tests/test_tiers.py`:
```python
from ffcoach.model.players import Player
from ffcoach.model.tiers import assign_tiers


def p(name, adp):
    return Player(
        name=name,
        position="RB",
        team="X",
        adp=adp,
        stdev=1.0,
        bye=None,
        times_drafted=1,
        injury_status=None,
        sleeper_id=None,
    )


def test_empty_input_returns_empty():
    assert assign_tiers([]) == []


def test_single_player_is_tier_one():
    assert assign_tiers([p("a", 1.0)]) == [1]


def test_evenly_spaced_players_stay_in_one_tier():
    players = [p(str(i), float(i)) for i in range(1, 8)]
    assert assign_tiers(players) == [1] * 7


def test_large_gap_starts_a_new_tier():
    players = [p("a", 1.0), p("b", 2.0), p("c", 3.0), p("d", 20.0), p("e", 21.0)]
    assert assign_tiers(players) == [1, 1, 1, 2, 2]


def test_multiple_cliffs_produce_multiple_tiers():
    players = [p("a", 1.0), p("b", 2.0), p("c", 15.0), p("d", 16.0), p("e", 40.0)]
    assert assign_tiers(players) == [1, 1, 2, 2, 3]


def test_lower_multiplier_splits_more_aggressively():
    players = [p("a", 1.0), p("b", 2.0), p("c", 4.5)]
    assert assign_tiers(players, gap_multiplier=1.2) == [1, 1, 2]
    assert assign_tiers(players, gap_multiplier=5.0) == [1, 1, 1]


def test_input_order_is_preserved_not_sorted():
    players = [p("a", 1.0), p("b", 2.0), p("c", 3.0)]
    assert len(assign_tiers(players)) == len(players)
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_tiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.model.tiers'`.

- [ ] **Step 3: Implement**

`src/ffcoach/model/tiers.py`:
```python
"""Tier assignment by ADP cliff detection.

A tier break is where the market's opinion drops off sharply, which is more
useful than fixed-size buckets: it tells you when waiting costs you real
quality rather than one ranking slot.
"""

from __future__ import annotations

from collections.abc import Sequence

from ffcoach.model.players import Player


def assign_tiers(players: Sequence[Player], gap_multiplier: float = 1.5) -> list[int]:
    """Return a tier number per player, in input order, starting at 1."""
    if not players:
        return []

    tiers = [1]
    gaps: list[float] = []
    tier = 1

    for prev, cur in zip(players, players[1:]):
        gap = cur.adp - prev.adp
        if gaps:
            mean_gap = sum(gaps) / len(gaps)
            if mean_gap > 0 and gap > mean_gap * gap_multiplier:
                tier += 1
                gaps = []
                tiers.append(tier)
                continue
        gaps.append(gap)
        tiers.append(tier)

    return tiers
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_tiers.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ffcoach/model/tiers.py tests/test_tiers.py
git commit -m "feat: tier assignment by adp cliff detection"
```

---

## Task 6: Value verdict and availability

**Files:**
- Create: `src/ffcoach/model/value.py`, `tests/test_value.py`

**Interfaces:**
- Consumes: `Player` from Task 4
- Produces:
  - `verdict(rank: int, adp: float, threshold: float = 6.0) -> str` → `"bargain" | "fair" | "reach"`
  - `verdict_text(v: str) -> str` — the explain-mode sentence
  - `availability(adp: float, stdev: float, pick: int) -> str` → `"gone" | "toss-up" | "likely"`
  - `availability_text(a: str, pick: int) -> str`

`availability` uses the normal CDF over ADP and its standard deviation to answer "what are the odds he lasts to pick N". FFC supplies `stdev`, so this is a real calculation. Probability above 0.65 is `likely`, below 0.25 is `gone`, between is `toss-up`.

- [ ] **Step 1: Write the failing tests**

`tests/test_value.py`:
```python
import pytest

from ffcoach.model.value import (
    availability,
    availability_text,
    verdict,
    verdict_text,
)


def test_falling_past_adp_is_a_bargain():
    # Ranked 5th but the market takes him around 20 -> he is falling to you.
    assert verdict(rank=5, adp=20.0) == "bargain"


def test_going_near_adp_is_fair():
    assert verdict(rank=10, adp=11.0) == "fair"
    assert verdict(rank=10, adp=5.0) == "fair"


def test_taking_someone_early_is_a_reach():
    assert verdict(rank=30, adp=10.0) == "reach"


def test_threshold_is_configurable():
    assert verdict(rank=10, adp=17.0, threshold=6.0) == "bargain"
    assert verdict(rank=10, adp=17.0, threshold=20.0) == "fair"


def test_verdict_text_is_plain_language_and_mentions_no_money():
    for v in ("bargain", "fair", "reach"):
        text = verdict_text(v)
        assert text and text[0].isupper()
        assert "$" not in text


def test_verdict_text_rejects_unknown_verdict():
    with pytest.raises(ValueError, match="unknown verdict"):
        verdict_text("amazing")


def test_player_well_past_his_adp_is_gone():
    # ADP 10, tight spread, your next pick is 31 -> no chance.
    assert availability(adp=10.0, stdev=2.0, pick=31) == "gone"


def test_player_well_after_your_pick_is_likely_there():
    assert availability(adp=60.0, stdev=5.0, pick=31) == "likely"


def test_player_near_your_pick_is_a_toss_up():
    assert availability(adp=31.0, stdev=4.0, pick=31) == "toss-up"


def test_wide_spread_softens_a_gone_verdict():
    tight = availability(adp=20.0, stdev=1.0, pick=31)
    wide = availability(adp=20.0, stdev=30.0, pick=31)
    assert tight == "gone"
    assert wide in ("toss-up", "likely")


def test_zero_stdev_does_not_divide_by_zero():
    assert availability(adp=10.0, stdev=0.0, pick=31) == "gone"
    assert availability(adp=90.0, stdev=0.0, pick=31) == "likely"


def test_availability_text_names_the_pick_number():
    assert "31" in availability_text("likely", pick=31)
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_value.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.model.value'`.

- [ ] **Step 3: Implement**

`src/ffcoach/model/value.py`:
```python
"""Value verdicts and availability odds.

Spec UX rules 1 and 3: the raw number is always shown, and this module
supplies the plain-language reading that sits beside it under explain mode.
No output here ever mentions currency.
"""

from __future__ import annotations

import math

VERDICT_TEXT = {
    "bargain": (
        "He is lasting later than the rest of the fantasy world usually "
        "takes him, so you are getting him below his normal cost."
    ),
    "fair": (
        "He is going right about where he normally goes. No bargain, "
        "no mistake."
    ),
    "reach": (
        "You would be taking him earlier than he usually goes. Fine if you "
        "love him, but you could probably wait a round."
    ),
}

AVAILABILITY_TEXT = {
    "gone": "Almost certainly drafted before pick {pick}. Take him now or move on.",
    "toss-up": "Roughly a coin flip whether he lasts to pick {pick}.",
    "likely": "Very likely still available at pick {pick}, so you can wait.",
}


def verdict(rank: int, adp: float, threshold: float = 6.0) -> str:
    """Compare our ranking to the market's average draft position.

    Positive difference means he is falling past where he should go.
    """
    difference = adp - rank
    if difference > threshold:
        return "bargain"
    if difference < -threshold:
        return "reach"
    return "fair"


def verdict_text(v: str) -> str:
    try:
        return VERDICT_TEXT[v]
    except KeyError:
        raise ValueError(f"unknown verdict: {v!r}") from None


def _probability_available_at(adp: float, stdev: float, pick: int) -> float:
    """P(this player is still on the board at `pick`)."""
    if stdev <= 0:
        return 1.0 if adp > pick else 0.0
    z = (adp - pick) / (stdev * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def availability(adp: float, stdev: float, pick: int) -> str:
    p = _probability_available_at(adp, stdev, pick)
    if p >= 0.65:
        return "likely"
    if p <= 0.25:
        return "gone"
    return "toss-up"


def availability_text(a: str, pick: int) -> str:
    try:
        return AVAILABILITY_TEXT[a].format(pick=pick)
    except KeyError:
        raise ValueError(f"unknown availability: {a!r}") from None
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_value.py -v`
Expected: PASS, 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ffcoach/model/value.py tests/test_value.py
git commit -m "feat: bargain/fair/reach verdicts and availability odds"
```

---

## Task 7: Fantasy Football Calculator ADP source

**Files:**
- Create: `src/ffcoach/sources/__init__.py`, `src/ffcoach/sources/ffcalc.py`, `tests/fixtures/ffc_ppr_12.json`, `tests/test_ffcalc.py`

**Interfaces:**
- Consumes: `Cache` (Task 3), `Player` (Task 4)
- Produces:
  - `FFCALC_URL: str`
  - `fetch_adp(scoring: str, teams: int, season: int, cache: Cache, client: httpx.Client | None = None) -> str` — returns raw JSON text, cached 6 hours, falling back to stale on failure
  - `parse_adp(raw: str) -> list[Player]` — pure
  - `AdpUnavailable(Exception)`

- [ ] **Step 1: Capture the fixture**

Run this once to record a real response for tests. Tests never hit the network afterwards.

```bash
mkdir -p tests/fixtures
curl -s "https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams=12&year=2026" \
  | uv run python -c "import json,sys; d=json.load(sys.stdin); d['players']=d['players'][:40]; print(json.dumps(d,indent=1))" \
  > tests/fixtures/ffc_ppr_12.json
```
Expected: a file of roughly 40 players with `status`, `meta`, and `players`.

- [ ] **Step 2: Write the failing tests**

`tests/test_ffcalc.py`:
```python
import json
from pathlib import Path

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.sources.ffcalc import (
    AdpUnavailable,
    _cache_key,
    fetch_adp,
    parse_adp,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ffc_ppr_12.json"


@pytest.fixture
def raw():
    return FIXTURE.read_text()


def client_returning(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_produces_players(raw):
    players = parse_adp(raw)
    assert players
    first = players[0]
    assert first.name
    assert first.position in ("QB", "RB", "WR", "TE", "K", "DEF")
    assert first.adp > 0
    assert first.stdev >= 0


def test_parse_sorts_by_adp(raw):
    players = parse_adp(raw)
    assert players == sorted(players, key=lambda p: p.adp)


def test_parse_maps_defense_position_to_def():
    payload = json.dumps(
        {
            "status": "Success",
            "meta": {"type": "PPR", "teams": 12},
            "players": [
                {
                    "name": "Ravens",
                    "position": "DST",
                    "team": "BAL",
                    "adp": 120.0,
                    "stdev": 10.0,
                    "times_drafted": 50,
                    "bye": 7,
                }
            ],
        }
    )
    assert parse_adp(payload)[0].position == "DEF"


def test_parse_rejects_error_status():
    with pytest.raises(AdpUnavailable, match="status"):
        parse_adp(json.dumps({"status": "Error", "players": []}))


def test_parse_rejects_malformed_json():
    with pytest.raises(AdpUnavailable, match="parse"):
        parse_adp("<html>nope</html>")


def test_fetch_hits_network_once_then_serves_cache(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning(raw, calls=calls)
    a = fetch_adp("ppr", 12, 2026, cache, client=client)
    b = fetch_adp("ppr", 12, 2026, cache, client=client)
    assert a == b == raw
    assert len(calls) == 1


def test_fetch_url_carries_format_teams_and_year(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    fetch_adp("half-ppr", 10, 2026, cache, client=client_returning(raw, calls=calls))
    url = calls[0]
    assert "half-ppr" in url
    assert "teams=10" in url
    assert "year=2026" in url


def test_fetch_falls_back_to_stale_cache_on_failure(tmp_path, raw):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_adp("ppr", 12, 2026, cache, client=client_returning(raw))
    # Force expiry, then fail the network.
    cache.set(_cache_key("ppr", 12, 2026), raw, ttl_seconds=-1)
    got = fetch_adp("ppr", 12, 2026, cache, client=client_returning("", status=500))
    assert got == raw


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(AdpUnavailable, match="500"):
        fetch_adp("ppr", 12, 2026, cache, client=client_returning("", status=500))
```

- [ ] **Step 3: Run and watch it fail**

Run: `uv run pytest tests/test_ffcalc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.sources'`.

- [ ] **Step 4: Implement**

`src/ffcoach/sources/__init__.py`:
```python
```
(empty file)

`src/ffcoach/sources/ffcalc.py`:
```python
"""Average Draft Position from Fantasy Football Calculator.

Free, public, unauthenticated. Chosen over Sleeper because Sleeper exposes
no aggregate ADP endpoint. The `stdev` field is what makes a real
availability calculation possible instead of a guess.
"""

from __future__ import annotations

import json

import httpx

from ffcoach.cache import Cache
from ffcoach.model.players import Player

FFCALC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"
TTL_SECONDS = 6 * 60 * 60

_POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}


class AdpUnavailable(Exception):
    """Raised when ADP cannot be fetched or parsed and no cache exists."""


def _cache_key(scoring: str, teams: int, season: int) -> str:
    return f"adp:{scoring}:{teams}:{season}"


def fetch_adp(
    scoring: str,
    teams: int,
    season: int,
    cache: Cache,
    client: httpx.Client | None = None,
) -> str:
    key = _cache_key(scoring, teams, season)
    cached = cache.get(key)
    if cached is not None:
        return cached

    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        response = client.get(
            FFCALC_URL.format(scoring=scoring),
            params={"teams": teams, "year": season},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stale = cache.get_stale(key)
        if stale is not None:
            return stale[0]
        raise AdpUnavailable(f"could not fetch ADP and no cached copy exists: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    cache.set(key, response.text, ttl_seconds=TTL_SECONDS)
    return response.text


def parse_adp(raw: str) -> list[Player]:
    """Pure: JSON text in, sorted Players out."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdpUnavailable(f"could not parse ADP response: {exc}") from exc

    if payload.get("status") != "Success":
        raise AdpUnavailable(f"ADP response status was {payload.get('status')!r}")

    players = [
        Player(
            name=row["name"],
            position=_POSITION_ALIASES.get(row["position"], row["position"]),
            team=row.get("team") or "",
            adp=float(row["adp"]),
            stdev=float(row.get("stdev") or 0.0),
            bye=int(row["bye"]) if row.get("bye") else None,
            times_drafted=int(row.get("times_drafted") or 0),
            injury_status=None,
            sleeper_id=None,
        )
        for row in payload.get("players", [])
    ]
    return sorted(players, key=lambda p: p.adp)
```

- [ ] **Step 5: Run and watch it pass**

Run: `uv run pytest tests/test_ffcalc.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 6: Commit**

```bash
git add src/ffcoach/sources tests/test_ffcalc.py tests/fixtures/ffc_ppr_12.json
git commit -m "feat: fantasy football calculator adp source"
```

---

## Task 8: Sleeper player metadata and the join

**Files:**
- Create: `src/ffcoach/sources/sleeper.py`, `src/ffcoach/sources/match.py`, `tests/fixtures/sleeper_players.json`, `tests/test_sleeper.py`, `tests/test_match.py`

**Interfaces:**
- Consumes: `Cache` (Task 3), `Player`, `normalize_name` (Task 4)
- Produces:
  - `fetch_players(cache: Cache, client: httpx.Client | None = None) -> str` — cached 24 hours
  - `parse_players(raw: str) -> dict[tuple[str, str], dict]` — keyed by `(normalized_name, position)`
  - `enrich(players: list[Player], meta: dict[tuple[str, str], dict]) -> tuple[list[Player], list[str]]` — returns enriched players plus names that failed to match

Unmatched players are returned, never silently dropped — a silent join failure would quietly strip injury data from the board.

- [ ] **Step 1: Capture the fixture**

```bash
curl -s "https://api.sleeper.app/v1/players/nfl" \
  | uv run python -c "
import json,sys
d=json.load(sys.stdin)
keep={k:v for k,v in d.items() if v.get('active') and v.get('position') in ('QB','RB','WR','TE','K','DEF')}
sub=dict(list(keep.items())[:300])
fields=('player_id','full_name','first_name','last_name','position','team','injury_status','status','active')
print(json.dumps({k:{f:v.get(f) for f in fields} for k,v in sub.items()},indent=1))
" > tests/fixtures/sleeper_players.json
```
Expected: roughly 300 trimmed player records.

- [ ] **Step 2: Write the failing tests**

`tests/test_sleeper.py`:
```python
import json
from pathlib import Path

import httpx
import pytest

from ffcoach.cache import Cache
from ffcoach.sources.sleeper import PlayersUnavailable, fetch_players, parse_players

FIXTURE = Path(__file__).parent / "fixtures" / "sleeper_players.json"


def client_returning(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_keys_by_normalized_name_and_position():
    meta = parse_players(FIXTURE.read_text())
    assert meta
    for (name, position), row in meta.items():
        assert name == name.lower()
        assert " " not in name
        assert position in ("QB", "RB", "WR", "TE", "K", "DEF")
        assert "player_id" in row


def test_parse_skips_players_without_a_name():
    payload = json.dumps({"1": {"player_id": "1", "position": "RB", "full_name": None}})
    assert parse_players(payload) == {}


def test_parse_rejects_malformed_json():
    with pytest.raises(PlayersUnavailable, match="parse"):
        parse_players("not json")


def test_fetch_caches_after_first_call(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    calls = []
    client = client_returning("{}", calls=calls)
    fetch_players(cache, client=client)
    fetch_players(cache, client=client)
    assert len(calls) == 1


def test_fetch_raises_when_failing_with_no_cache(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    with pytest.raises(PlayersUnavailable, match="500"):
        fetch_players(cache, client=client_returning("", status=500))
```

`tests/test_match.py`:
```python
from ffcoach.model.players import Player
from ffcoach.sources.match import enrich


def player(name, position="RB"):
    return Player(
        name=name,
        position=position,
        team="ATL",
        adp=10.0,
        stdev=2.0,
        bye=11,
        times_drafted=100,
        injury_status=None,
        sleeper_id=None,
    )


META = {
    ("bijanrobinson", "RB"): {"player_id": "9509", "injury_status": None},
    ("kennethwalker", "RB"): {"player_id": "8151", "injury_status": "Questionable"},
}


def test_enrich_attaches_sleeper_id_and_injury():
    out, unmatched = enrich([player("Bijan Robinson")], META)
    assert out[0].sleeper_id == "9509"
    assert unmatched == []


def test_enrich_carries_injury_status():
    out, _ = enrich([player("Kenneth Walker III")], META)
    assert out[0].injury_status == "Questionable"


def test_enrich_reports_unmatched_rather_than_dropping():
    out, unmatched = enrich([player("Nobody Here")], META)
    assert len(out) == 1
    assert out[0].sleeper_id is None
    assert unmatched == ["Nobody Here"]


def test_enrich_does_not_match_across_positions():
    out, unmatched = enrich([player("Bijan Robinson", position="WR")], META)
    assert out[0].sleeper_id is None
    assert unmatched == ["Bijan Robinson"]


def test_enrich_preserves_order_and_length():
    players = [player("Bijan Robinson"), player("Nobody Here"), player("Kenneth Walker III")]
    out, _ = enrich(players, META)
    assert [p.name for p in out] == [p.name for p in players]
```

- [ ] **Step 3: Run and watch them fail**

Run: `uv run pytest tests/test_sleeper.py tests/test_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.sources.sleeper'`.

- [ ] **Step 4: Implement**

`src/ffcoach/sources/sleeper.py`:
```python
"""Player metadata from the Sleeper API.

Free, public, unauthenticated. Roughly 12,000 players and about 14MB, so it
is cached for a day. Sleeper supplies injury status and identity; it does
not supply ADP.
"""

from __future__ import annotations

import json

import httpx

from ffcoach.model.players import normalize_name

SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
TTL_SECONDS = 24 * 60 * 60
CACHE_KEY = "sleeper:players:nfl"

_POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}
_KEEP = ("QB", "RB", "WR", "TE", "K", "DEF")


class PlayersUnavailable(Exception):
    """Raised when player metadata cannot be fetched or parsed."""


def fetch_players(cache, client: httpx.Client | None = None) -> str:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        response = client.get(SLEEPER_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stale = cache.get_stale(CACHE_KEY)
        if stale is not None:
            return stale[0]
        raise PlayersUnavailable(
            f"could not fetch Sleeper players and no cached copy exists: {exc}"
        ) from exc
    finally:
        if owns_client:
            client.close()

    cache.set(CACHE_KEY, response.text, ttl_seconds=TTL_SECONDS)
    return response.text


def parse_players(raw: str) -> dict[tuple[str, str], dict]:
    """Pure: JSON text in, lookup keyed by (normalized name, position) out."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlayersUnavailable(f"could not parse Sleeper response: {exc}") from exc

    out: dict[tuple[str, str], dict] = {}
    for row in payload.values():
        name = row.get("full_name")
        position = _POSITION_ALIASES.get(row.get("position"), row.get("position"))
        if not name or position not in _KEEP:
            continue
        out[(normalize_name(name), position)] = row
    return out
```

`src/ffcoach/sources/match.py`:
```python
"""Join ADP records to player metadata.

The two sources have unrelated ID spaces, so the join key is normalized
name plus position. Unmatched players are reported rather than dropped: a
silent join failure would quietly strip injury data off the board.
"""

from __future__ import annotations

import dataclasses

from ffcoach.model.players import Player


def enrich(
    players: list[Player], meta: dict[tuple[str, str], dict]
) -> tuple[list[Player], list[str]]:
    enriched: list[Player] = []
    unmatched: list[str] = []

    for player in players:
        row = meta.get(player.key)
        if row is None:
            unmatched.append(player.name)
            enriched.append(player)
            continue
        enriched.append(
            dataclasses.replace(
                player,
                sleeper_id=row.get("player_id"),
                injury_status=row.get("injury_status"),
            )
        )

    return enriched, unmatched
```

- [ ] **Step 5: Run and watch them pass**

Run: `uv run pytest tests/test_sleeper.py tests/test_match.py -v`
Expected: PASS, 10 passed.

- [ ] **Step 6: Commit**

```bash
git add src/ffcoach/sources tests/test_sleeper.py tests/test_match.py tests/fixtures/sleeper_players.json
git commit -m "feat: sleeper player source and cross-source join"
```

---

## Task 9: The draft advisor

**Files:**
- Create: `src/ffcoach/advisors/__init__.py`, `src/ffcoach/advisors/draft.py`, `tests/test_draft_advisor.py`

**Interfaces:**
- Consumes: `LeagueConfig` (Task 2), `Player` (Task 4), `assign_tiers` (Task 5), `verdict`/`availability` (Task 6)
- Produces:
  - `BoardRow` frozen dataclass: `rank`, `name`, `position`, `team`, `adp`, `stdev`, `bye`, `value`, `verdict`, `verdict_text`, `availability`, `availability_text`, `tier`, `tier_break_after`, `injury_status`, `reason`
  - `build_board(players: list[Player], config: LeagueConfig) -> list[BoardRow]`

`reason` satisfies spec UX rule 4 — every row that gets a non-neutral verdict carries a sentence explaining it, in both modes.

- [ ] **Step 1: Write the failing tests**

`tests/test_draft_advisor.py`:
```python
from ffcoach.advisors.draft import BoardRow, build_board
from ffcoach.config import LeagueConfig
from ffcoach.model.players import Player


def cfg(**over):
    base = dict(
        name="T",
        season=2026,
        teams=12,
        scoring="ppr",
        my_pick=7,
        roster={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 6},
    )
    base.update(over)
    return LeagueConfig(**base)


def player(name, adp, position="RB", stdev=2.0):
    return Player(
        name=name,
        position=position,
        team="ATL",
        adp=adp,
        stdev=stdev,
        bye=11,
        times_drafted=100,
        injury_status=None,
        sleeper_id=None,
    )


def test_empty_input_produces_empty_board():
    assert build_board([], cfg()) == []


def test_rank_is_sequential_from_one():
    board = build_board([player("a", 1.0), player("b", 2.0), player("c", 3.0)], cfg())
    assert [r.rank for r in board] == [1, 2, 3]


def test_rows_are_sorted_by_adp():
    board = build_board([player("b", 9.0), player("a", 1.0)], cfg())
    assert [r.name for r in board] == ["a", "b"]


def test_value_is_adp_minus_rank():
    board = build_board([player("a", 5.0), player("b", 9.0)], cfg())
    assert board[0].value == 4.0
    assert board[1].value == 7.0


def test_every_row_carries_a_verdict_and_its_text():
    board = build_board([player("a", 1.0), player("b", 40.0)], cfg())
    for row in board:
        assert row.verdict in ("bargain", "fair", "reach")
        assert row.verdict_text
        assert "$" not in row.verdict_text


def test_every_row_carries_availability_text_naming_next_pick():
    board = build_board([player("a", 1.0)], cfg(my_pick=7))
    # 12 teams picking 7th: next pick after 7 is 18.
    assert "18" in board[0].availability_text


def test_tier_break_flag_is_set_on_the_last_row_of_each_tier():
    players = [player("a", 1.0), player("b", 2.0), player("c", 30.0)]
    board = build_board(players, cfg())
    assert board[1].tier_break_after is True
    assert board[2].tier_break_after is False


def test_last_row_never_flags_a_tier_break():
    board = build_board([player("a", 1.0), player("b", 50.0)], cfg())
    assert board[-1].tier_break_after is False


def test_non_neutral_verdicts_get_a_reason():
    board = build_board([player("a", 40.0), player("b", 41.0)], cfg())
    bargains = [r for r in board if r.verdict == "bargain"]
    assert bargains
    for row in bargains:
        assert row.reason


def test_injury_status_is_carried_through():
    hurt = Player(
        name="Hurt Guy",
        position="RB",
        team="ATL",
        adp=5.0,
        stdev=1.0,
        bye=9,
        times_drafted=10,
        injury_status="Questionable",
        sleeper_id="1",
    )
    board = build_board([hurt], cfg())
    assert board[0].injury_status == "Questionable"
    assert "Questionable" in board[0].reason


def test_board_row_is_frozen():
    board = build_board([player("a", 1.0)], cfg())
    assert isinstance(board[0], BoardRow)
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_draft_advisor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.advisors'`.

- [ ] **Step 3: Implement**

`src/ffcoach/advisors/__init__.py`:
```python
```
(empty file)

`src/ffcoach/advisors/draft.py`:
```python
"""Assemble the draft board.

Emits structured rows, never prose. Spec design rule 2: advisors produce
findings; the Claude skill turns findings into coaching.
"""

from __future__ import annotations

from dataclasses import dataclass

from ffcoach.config import LeagueConfig
from ffcoach.model.players import Player
from ffcoach.model.tiers import assign_tiers
from ffcoach.model.value import (
    availability,
    availability_text,
    verdict,
    verdict_text,
)


@dataclass(frozen=True)
class BoardRow:
    rank: int
    name: str
    position: str
    team: str
    adp: float
    stdev: float
    bye: int | None
    value: float
    verdict: str
    verdict_text: str
    availability: str
    availability_text: str
    tier: int
    tier_break_after: bool
    injury_status: str | None
    reason: str


def _reason(row_verdict: str, avail: str, injury: str | None) -> str:
    """One short sentence explaining why this row is highlighted.

    Spec UX rule 4: no unexplained badge, in either mode.
    """
    parts: list[str] = []
    if row_verdict == "bargain":
        parts.append("Falling past his usual draft slot")
    elif row_verdict == "reach":
        parts.append("Would be an early pick for him")
    if avail == "gone":
        parts.append("unlikely to last to your next pick")
    if injury:
        parts.append(f"listed {injury}")
    if not parts:
        return ""
    sentence = ", ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def build_board(players: list[Player], config: LeagueConfig) -> list[BoardRow]:
    if not players:
        return []

    ordered = sorted(players, key=lambda p: p.adp)
    tiers = assign_tiers(ordered)
    next_pick = config.next_pick_after(config.my_pick) or config.my_pick

    rows: list[BoardRow] = []
    for index, (player, tier) in enumerate(zip(ordered, tiers)):
        rank = index + 1
        row_verdict = verdict(rank=rank, adp=player.adp)
        avail = availability(adp=player.adp, stdev=player.stdev, pick=next_pick)
        is_last = index == len(ordered) - 1
        rows.append(
            BoardRow(
                rank=rank,
                name=player.name,
                position=player.position,
                team=player.team,
                adp=player.adp,
                stdev=player.stdev,
                bye=player.bye,
                value=round(player.adp - rank, 1),
                verdict=row_verdict,
                verdict_text=verdict_text(row_verdict),
                availability=avail,
                availability_text=availability_text(avail, next_pick),
                tier=tier,
                tier_break_after=(not is_last and tiers[index + 1] != tier),
                injury_status=player.injury_status,
                reason=_reason(row_verdict, avail, player.injury_status),
            )
        )
    return rows
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_draft_advisor.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ffcoach/advisors tests/test_draft_advisor.py
git commit -m "feat: draft board advisor"
```

---

## Task 10: JSON report writer

**Files:**
- Create: `src/ffcoach/report/__init__.py`, `src/ffcoach/report/build.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: `BoardRow` (Task 9), `LeagueConfig` (Task 2)
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `board_payload(rows: list[BoardRow], config: LeagueConfig, generated_at: str, unmatched: list[str], stale_seconds: float | None) -> dict`
  - `write_board(payload: dict, path: Path) -> None`

This is the contract the browser depends on, so it is asserted from the Python side.

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:
```python
import json

from ffcoach.advisors.draft import build_board
from ffcoach.config import LeagueConfig
from ffcoach.model.players import Player
from ffcoach.report.build import SCHEMA_VERSION, board_payload, write_board


def cfg():
    return LeagueConfig(
        name="T",
        season=2026,
        teams=12,
        scoring="ppr",
        my_pick=7,
        roster={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 6},
    )


def rows():
    players = [
        Player("A", "RB", "ATL", 1.0, 1.0, 11, 10, None, "1"),
        Player("B", "WR", "CIN", 20.0, 4.0, 6, 10, "Questionable", "2"),
    ]
    return build_board(players, cfg())


def payload():
    return board_payload(
        rows(), cfg(), generated_at="2026-08-20T12:00:00Z", unmatched=["X"], stale_seconds=None
    )


def test_payload_declares_schema_version():
    assert payload()["schema_version"] == SCHEMA_VERSION


def test_payload_includes_league_context_the_page_needs():
    league = payload()["league"]
    assert league["teams"] == 12
    assert league["scoring"] == "ppr"
    assert league["my_pick"] == 7
    assert league["next_pick"] == 18


def test_payload_never_contains_a_dollar_figure():
    assert "$" not in json.dumps(payload())


def test_every_row_has_the_documented_keys():
    expected = {
        "rank", "name", "position", "team", "adp", "stdev", "bye", "value",
        "verdict", "verdict_text", "availability", "availability_text",
        "tier", "tier_break_after", "injury_status", "reason",
    }
    for row in payload()["players"]:
        assert set(row) == expected


def test_payload_reports_unmatched_players():
    assert payload()["unmatched"] == ["X"]


def test_payload_marks_fresh_data_as_not_stale():
    assert payload()["stale"] is False


def test_payload_marks_stale_data_with_its_age():
    p = board_payload(
        rows(), cfg(), generated_at="2026-08-20T12:00:00Z", unmatched=[], stale_seconds=7200.0
    )
    assert p["stale"] is True
    assert p["stale_seconds"] == 7200.0


def test_write_board_creates_parent_directories(tmp_path):
    target = tmp_path / "web" / "data" / "board.json"
    write_board(payload(), target)
    assert json.loads(target.read_text())["schema_version"] == SCHEMA_VERSION
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.report'`.

- [ ] **Step 3: Implement**

`src/ffcoach/report/__init__.py`:
```python
```
(empty file)

`src/ffcoach/report/build.py`:
```python
"""Write the JSON contract the browser reads.

The shape here is asserted by tests on the Python side so the page's
contract cannot drift silently.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ffcoach.advisors.draft import BoardRow
from ffcoach.config import LeagueConfig

SCHEMA_VERSION = 1


def board_payload(
    rows: list[BoardRow],
    config: LeagueConfig,
    generated_at: str,
    unmatched: list[str],
    stale_seconds: float | None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "stale": stale_seconds is not None,
        "stale_seconds": stale_seconds,
        "unmatched": list(unmatched),
        "league": {
            "name": config.name,
            "season": config.season,
            "teams": config.teams,
            "scoring": config.scoring,
            "my_pick": config.my_pick,
            "next_pick": config.next_pick_after(config.my_pick),
            "rounds": config.rounds,
        },
        "players": [dataclasses.asdict(row) for row in rows],
    }


def write_board(payload: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1))
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_report.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ffcoach/report tests/test_report.py
git commit -m "feat: board json report writer"
```

---

## Task 11: CLI

**Files:**
- Create: `src/ffcoach/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `main(argv: list[str] | None = None) -> int`
  - Commands: `ffcoach refresh` (fetch and cache), `ffcoach build` (write `web/data/board.json`), `ffcoach doctor` (report config and cache state)
  - Flags: `--config PATH` (default `league.yaml`), `--cache PATH` (default `.ffcoach.sqlite3`), `--out PATH` (default `web/data/board.json`)

Uses `argparse` from the standard library. No new dependency.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
import json
from pathlib import Path

import pytest

from ffcoach.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
LEAGUE = """
name: Test League
season: 2026
teams: 12
scoring: ppr
my_pick: 7
roster: {QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DEF: 1, BN: 6}
"""


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "league.yaml").write_text(LEAGUE)
    cache_db = tmp_path / "c.sqlite3"

    from ffcoach.cache import Cache
    from ffcoach.sources.ffcalc import _cache_key
    from ffcoach.sources.sleeper import CACHE_KEY

    cache = Cache(cache_db)
    cache.set(_cache_key("ppr", 12, 2026), (FIXTURES / "ffc_ppr_12.json").read_text(), 3600)
    cache.set(CACHE_KEY, (FIXTURES / "sleeper_players.json").read_text(), 3600)
    return tmp_path


def test_build_writes_the_board(workspace):
    out = workspace / "web" / "data" / "board.json"
    code = main([
        "build",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["players"]
    assert payload["league"]["next_pick"] == 18


def test_build_ranks_players_from_one(workspace):
    out = workspace / "board.json"
    main([
        "build",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
        "--out", str(out),
    ])
    ranks = [r["rank"] for r in json.loads(out.read_text())["players"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_missing_config_exits_nonzero_with_a_clear_message(tmp_path, capsys):
    code = main([
        "build",
        "--config", str(tmp_path / "absent.yaml"),
        "--cache", str(tmp_path / "c.sqlite3"),
        "--out", str(tmp_path / "b.json"),
    ])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_doctor_reports_config_and_cache(workspace, capsys):
    code = main([
        "doctor",
        "--config", str(workspace / "league.yaml"),
        "--cache", str(workspace / "c.sqlite3"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "Test League" in out
    assert "ppr" in out


def test_unknown_command_exits_nonzero(capsys):
    with pytest.raises(SystemExit):
        main(["nonsense"])
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffcoach.cli'`.

- [ ] **Step 3: Implement**

`src/ffcoach/cli.py`:
```python
"""Command line entry point."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from ffcoach.advisors.draft import build_board
from ffcoach.cache import Cache
from ffcoach.config import ConfigError, load_config
from ffcoach.report.build import board_payload, write_board
from ffcoach.sources.ffcalc import AdpUnavailable, fetch_adp, parse_adp
from ffcoach.sources.match import enrich
from ffcoach.sources.sleeper import PlayersUnavailable, fetch_players, parse_players


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ffcoach")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("refresh", "fetch and cache player data"),
        ("build", "write web/data/board.json"),
        ("doctor", "report config and cache state"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default="league.yaml", type=Path)
        p.add_argument("--cache", default=".ffcoach.sqlite3", type=Path)
        if name == "build":
            p.add_argument("--out", default=Path("web/data/board.json"), type=Path)

    return parser


def _load_players(config, cache):
    raw_adp = fetch_adp(config.scoring, config.teams, config.season, cache)
    players = parse_adp(raw_adp)
    meta = parse_players(fetch_players(cache))
    return enrich(players, meta)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    cache = Cache(args.cache)

    if args.command == "doctor":
        print(f"League:   {config.name} ({config.season})")
        print(f"Format:   {config.scoring}, {config.teams} teams")
        print(f"Your pick: {config.my_pick} -> next {config.next_pick_after(config.my_pick)}")
        print(f"Cache:    {args.cache}")
        return 0

    try:
        players, unmatched = _load_players(config, cache)
    except (AdpUnavailable, PlayersUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "refresh":
        print(f"Cached {len(players)} players; {len(unmatched)} unmatched.")
        return 0

    rows = build_board(players, config)
    payload = board_payload(
        rows,
        config,
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        unmatched=unmatched,
        stale_seconds=None,
    )
    write_board(payload, args.out)
    print(f"Wrote {len(rows)} players to {args.out}")
    if unmatched:
        print(f"note: {len(unmatched)} players had no Sleeper match", file=sys.stderr)
    return 0
```

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Run the whole suite and generate a real board**

Run:
```bash
uv run pytest -q
cp league.example.yaml league.yaml
uv run ffcoach build
```
Expected: all tests pass; `Wrote N players to web/data/board.json`.

- [ ] **Step 6: Commit**

```bash
git add src/ffcoach/cli.py tests/test_cli.py
git commit -m "feat: cli with refresh, build, and doctor"
```

---

## Task 12: Browser render logic

**Files:**
- Create: `web/render.js`, `web/render.test.js` (replacing the Task 1 placeholder)

**Interfaces:**
- Consumes: `web/data/board.json` shape from Task 10
- Produces (all pure, no DOM):
  - `formatValue(value)` → `"+4.0"` / `"-2.0"` / `"0.0"`
  - `positionClass(position)` → CSS class name
  - `applyFilters(players, {position, hideDrafted, draftedIds})` → filtered array
  - `bestAvailable(players, draftedIds)` → the top undrafted player or `null`
  - `tierCounts(players, draftedIds)` → `{ "RB1": 3, ... }` of undrafted per position-tier
  - `rowHtml(player, {explain, drafted})` → HTML string
  - `boardHtml(players, opts)` → HTML string including tier-break rows
  - `playerId(player)` → stable id used for drafted tracking

`draftedIds` is a `Set`. This is the live-recompute logic that cannot be precomputed in Python.

- [ ] **Step 1: Write the failing tests**

`web/render.test.js`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyFilters,
  bestAvailable,
  boardHtml,
  formatValue,
  playerId,
  positionClass,
  rowHtml,
  tierCounts,
} from "./render.js";

const P = (over = {}) => ({
  rank: 1,
  name: "Bijan Robinson",
  position: "RB",
  team: "ATL",
  adp: 1.7,
  stdev: 0.8,
  bye: 11,
  value: 0.7,
  verdict: "fair",
  verdict_text: "He is going right about where he normally goes.",
  availability: "gone",
  availability_text: "Almost certainly drafted before pick 18.",
  tier: 1,
  tier_break_after: false,
  injury_status: null,
  reason: "",
  ...over,
});

test("formatValue always shows a sign and one decimal", () => {
  assert.equal(formatValue(4), "+4.0");
  assert.equal(formatValue(-2.25), "-2.3");
  assert.equal(formatValue(0), "0.0");
});

test("positionClass maps position to a class", () => {
  assert.equal(positionClass("RB"), "pos-rb");
  assert.equal(positionClass("DEF"), "pos-def");
});

test("playerId is stable and unique per name and position", () => {
  assert.equal(playerId(P()), playerId(P()));
  assert.notEqual(playerId(P()), playerId(P({ name: "Someone Else" })));
  assert.notEqual(playerId(P()), playerId(P({ position: "WR" })));
});

test("applyFilters returns everything by default", () => {
  const players = [P(), P({ name: "B", position: "WR" })];
  assert.equal(applyFilters(players, {}).length, 2);
});

test("applyFilters narrows by position", () => {
  const players = [P(), P({ name: "B", position: "WR" })];
  const out = applyFilters(players, { position: "WR" });
  assert.deepEqual(out.map((p) => p.name), ["B"]);
});

test("applyFilters can hide drafted players", () => {
  const a = P();
  const b = P({ name: "B" });
  const drafted = new Set([playerId(a)]);
  const out = applyFilters([a, b], { hideDrafted: true, draftedIds: drafted });
  assert.deepEqual(out.map((p) => p.name), ["B"]);
});

test("applyFilters keeps drafted players when not hiding", () => {
  const a = P();
  const drafted = new Set([playerId(a)]);
  assert.equal(applyFilters([a], { hideDrafted: false, draftedIds: drafted }).length, 1);
});

test("bestAvailable skips drafted players", () => {
  const a = P({ name: "A", rank: 1 });
  const b = P({ name: "B", rank: 2 });
  assert.equal(bestAvailable([a, b], new Set([playerId(a)])).name, "B");
});

test("bestAvailable returns null when everyone is gone", () => {
  const a = P();
  assert.equal(bestAvailable([a], new Set([playerId(a)])), null);
});

test("tierCounts counts undrafted players per position tier", () => {
  const players = [
    P({ name: "A", position: "RB", tier: 1 }),
    P({ name: "B", position: "RB", tier: 1 }),
    P({ name: "C", position: "WR", tier: 2 }),
  ];
  const counts = tierCounts(players, new Set());
  assert.equal(counts["RB1"], 2);
  assert.equal(counts["WR2"], 1);
});

test("tierCounts drops to zero as players are drafted", () => {
  const a = P({ position: "RB", tier: 1 });
  assert.equal(tierCounts([a], new Set([playerId(a)]))["RB1"], 0);
});

test("rowHtml shows the raw ADP number in both modes", () => {
  assert.match(rowHtml(P(), { explain: false }), /1\.7/);
  assert.match(rowHtml(P(), { explain: true }), /1\.7/);
});

test("rowHtml never renames ADP away", () => {
  const html = rowHtml(P(), { explain: true });
  assert.doesNotMatch(html, /Typical pick/i);
});

test("rowHtml shows the reason in both modes", () => {
  const p = P({ verdict: "bargain", reason: "Falling past his usual draft slot." });
  assert.match(rowHtml(p, { explain: false }), /Falling past his usual draft slot/);
  assert.match(rowHtml(p, { explain: true }), /Falling past his usual draft slot/);
});

test("explain mode adds the verdict explanation, plain mode does not", () => {
  const p = P({ verdict_text: "EXPLAIN ME" });
  assert.doesNotMatch(rowHtml(p, { explain: false }), /EXPLAIN ME/);
  assert.match(rowHtml(p, { explain: true }), /EXPLAIN ME/);
});

test("drafted rows are marked", () => {
  assert.match(rowHtml(P(), { drafted: true }), /drafted/);
});

test("rowHtml escapes html in player names", () => {
  const html = rowHtml(P({ name: "<script>x</script>" }), {});
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("rowHtml never emits a dollar sign", () => {
  assert.doesNotMatch(rowHtml(P({ verdict: "bargain" }), { explain: true }), /\$/);
});

test("boardHtml inserts a tier break row after a flagged player", () => {
  const players = [P({ name: "A", tier_break_after: true }), P({ name: "B", tier: 2 })];
  const html = boardHtml(players, {});
  assert.match(html, /tier-break/);
});

test("boardHtml renders one row per player plus breaks", () => {
  const players = [P({ name: "A" }), P({ name: "B" })];
  const html = boardHtml(players, {});
  assert.equal((html.match(/<tr/g) || []).length, 2);
});

test("boardHtml handles an empty roster", () => {
  assert.match(boardHtml([], {}), /no players/i);
});
```

- [ ] **Step 2: Run and watch it fail**

Run: `npm test`
Expected: FAIL — the placeholder `render.js` from Task 1 exports only `ping`.

- [ ] **Step 3: Implement**

`web/render.js`:
```js
// Pure render and filter logic. No DOM access lives here, which is what
// makes it testable with `node --test`. All DOM wiring is in main.js.

const POSITION_CLASSES = {
  QB: "pos-qb",
  RB: "pos-rb",
  WR: "pos-wr",
  TE: "pos-te",
  K: "pos-k",
  DEF: "pos-def",
};

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function playerId(player) {
  return `${player.name}|${player.position}`;
}

export function formatValue(value) {
  const n = Number(value);
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(1)}`;
}

export function positionClass(position) {
  return POSITION_CLASSES[position] ?? "pos-k";
}

export function applyFilters(players, { position, hideDrafted, draftedIds } = {}) {
  const drafted = draftedIds ?? new Set();
  return players.filter((p) => {
    if (position && position !== "ALL" && p.position !== position) return false;
    if (hideDrafted && drafted.has(playerId(p))) return false;
    return true;
  });
}

export function bestAvailable(players, draftedIds = new Set()) {
  const open = players.filter((p) => !draftedIds.has(playerId(p)));
  if (open.length === 0) return null;
  return open.reduce((best, p) => (p.rank < best.rank ? p : best));
}

export function tierCounts(players, draftedIds = new Set()) {
  const counts = {};
  for (const p of players) {
    const key = `${p.position}${p.tier}`;
    counts[key] = counts[key] ?? 0;
    if (!draftedIds.has(playerId(p))) counts[key] += 1;
  }
  return counts;
}

export function rowHtml(player, { explain = false, drafted = false } = {}) {
  const name = escapeHtml(player.name);
  const reason = player.reason
    ? `<span class="reason">${escapeHtml(player.reason)}</span>`
    : "";
  // Explain mode annotates; it never replaces a term or reorders a column.
  const verdictNote = explain
    ? `<span class="note">${escapeHtml(player.verdict_text)}</span>`
    : "";
  const availNote = explain
    ? `<span class="note">${escapeHtml(player.availability_text)}</span>`
    : "";
  const injury = player.injury_status
    ? `<span class="injury">${escapeHtml(player.injury_status)}</span>`
    : "";

  return `<tr class="row${drafted ? " drafted" : ""}" data-id="${escapeHtml(playerId(player))}">
  <td class="num">${player.rank}</td>
  <td><button class="mark" aria-label="Mark ${name} drafted">${drafted ? "↩" : "✓"}</button></td>
  <td class="name">${name} ${injury}${reason}</td>
  <td><span class="pos ${positionClass(player.position)}">${escapeHtml(player.position)}</span></td>
  <td class="num">${Number(player.adp).toFixed(1)}</td>
  <td class="num value ${player.verdict}">${formatValue(player.value)}${verdictNote}</td>
  <td class="avail ${player.availability}">${escapeHtml(player.availability)}${availNote}</td>
</tr>`;
}

export function boardHtml(players, opts = {}) {
  if (players.length === 0) {
    return `<tr><td colspan="7" class="empty">No players match this filter.</td></tr>`;
  }
  const drafted = opts.draftedIds ?? new Set();
  return players
    .map((p) => {
      const row = rowHtml(p, { ...opts, drafted: drafted.has(playerId(p)) });
      const brk = p.tier_break_after
        ? `<tr class="tier-break"><td colspan="7">Noticeable drop in quality below this line</td></tr>`
        : "";
      return row + brk;
    })
    .join("\n");
}
```

- [ ] **Step 4: Run and watch it pass**

Run: `npm test`
Expected: `# pass 21`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add web/render.js web/render.test.js
git commit -m "feat: tested browser render logic"
```

---

## Task 13: The page

**Files:**
- Create: `web/index.html`, `web/main.js`, `web/style.css`
- Modify: `README.md`

**Interfaces:**
- Consumes: `render.js` (Task 12), `web/data/board.json` (Task 10)
- Produces: the running page

`main.js` holds no computation — every derived value comes from `render.js`. Drafted players and explain mode both persist to `localStorage` so a mid-draft refresh loses nothing.

- [ ] **Step 1: Write the page shell**

`web/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Draft Board</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1 id="league">Draft Board</h1>
  <div class="controls">
    <div class="chips" id="positions"></div>
    <label class="toggle"><input type="checkbox" id="hide-drafted"> Hide drafted</label>
    <label class="toggle"><input type="checkbox" id="explain"> Explain mode</label>
    <button id="reset">Reset draft</button>
  </div>
  <p class="howto">
    When it is your turn, take the top player who is not crossed out. Tick a
    player off as each pick happens and the board updates.
  </p>
  <p class="status" id="status"></p>
</header>
<main>
  <p class="best" id="best"></p>
  <table>
    <thead>
      <tr>
        <th>Rank</th><th></th><th>Player</th><th>Pos</th>
        <th>ADP</th><th>Value</th><th>Available at next pick</th>
      </tr>
    </thead>
    <tbody id="board"></tbody>
  </table>
</main>
<script type="module" src="main.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write the DOM wiring**

`web/main.js`:
```js
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
```

- [ ] **Step 3: Write the styles**

`web/style.css`:
```css
:root {
  --bg: #f7f7f5; --panel: #fff; --ink: #1a1a18; --muted: #6b6b66;
  --line: #e4e4df; --accent: #c2410c;
  --good: #15803d; --bad: #b91c1c;
  --qb: #7c3aed; --rb: #15803d; --wr: #0369a1; --te: #b45309; --k: #6b7280;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16161a; --panel: #1e1e23; --ink: #ececea; --muted: #9d9d97;
    --line: #32323b; --accent: #fb923c;
    --good: #4ade80; --bad: #f87171;
    --qb: #a78bfa; --rb: #4ade80; --wr: #38bdf8; --te: #fbbf24; --k: #9ca3af;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
header, main { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
header { padding-top: 22px; }
h1 { font-size: 20px; margin: 0 0 12px; }
.controls { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.chips { display: flex; gap: 5px; flex-wrap: wrap; }
.chip {
  border: 1px solid var(--line); background: var(--panel); color: var(--muted);
  padding: 5px 12px; border-radius: 20px; font: inherit; font-size: 12.5px; cursor: pointer;
}
.chip.on { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.toggle { font-size: 13px; color: var(--muted); display: flex; gap: 5px; align-items: center; }
button#reset {
  border: 1px solid var(--line); background: var(--panel); color: var(--muted);
  border-radius: 6px; padding: 5px 11px; font: inherit; font-size: 12.5px; cursor: pointer;
}
.howto { font-size: 13px; color: var(--muted); margin: 0 0 6px; }
.status { font-size: 12px; color: var(--muted); margin: 0 0 14px; }
.best {
  background: var(--panel); border: 1px solid var(--line); border-left: 3px solid var(--accent);
  border-radius: 0 6px 6px 0; padding: 10px 14px; font-weight: 600; margin: 0 0 14px;
}
table { width: 100%; border-collapse: collapse; background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
th {
  text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); padding: 10px 12px; border-bottom: 1px solid var(--line);
}
td { padding: 9px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
.num { font-variant-numeric: tabular-nums; }
.name { font-weight: 550; }
.reason, .note { display: block; color: var(--muted); font-size: 11.5px; font-weight: 400; margin-top: 2px; }
.injury { color: var(--bad); font-size: 11px; font-weight: 700; }
.value.bargain { color: var(--good); font-weight: 650; }
.value.reach { color: var(--bad); }
.avail.gone { color: var(--bad); }
.avail.likely { color: var(--good); }
.pos {
  display: inline-block; min-width: 32px; text-align: center; color: #fff;
  font-size: 10px; font-weight: 700; padding: 2px 5px; border-radius: 3px;
}
.pos-qb { background: var(--qb); } .pos-rb { background: var(--rb); }
.pos-wr { background: var(--wr); } .pos-te { background: var(--te); }
.pos-k, .pos-def { background: var(--k); }
.mark { border: 1px solid var(--line); background: none; color: var(--muted);
  border-radius: 4px; cursor: pointer; font-size: 12px; padding: 1px 6px; }
.drafted { opacity: .35; }
.drafted .name { text-decoration: line-through; }
.tier-break td {
  background: var(--bg); color: var(--accent); font-size: 10.5px;
  font-weight: 700; letter-spacing: .05em; padding: 5px 12px;
}
.empty { color: var(--muted); text-align: center; padding: 24px; }
```

- [ ] **Step 4: Verify the whole suite still passes**

Run:
```bash
uv run pytest -q && npm test
```
Expected: both suites pass.

- [ ] **Step 5: Verify the page by hand**

Run: `uv run ffcoach build`, then open `web/index.html` through VS Code Live Server.

Confirm each of these:
- The board lists players with ranks, ADP, and value.
- Clicking ✓ crosses a player out and "Best available" advances.
- Reloading keeps the crossed-out players.
- "Explain mode" adds explanation text and does **not** reorder or move columns.
- "ADP" appears as a column header, unrenamed.
- No dollar figure appears anywhere.

- [ ] **Step 6: Document it**

Replace `README.md` with the following (note the outer fence is four
backticks, because the content itself contains fenced blocks):

````markdown
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
````

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/main.js web/style.css README.md
git commit -m "feat: draft board page with live recompute and explain mode"
```

---

## Verification

After Task 13, all of the following must hold:

```bash
uv run pytest -q          # every python test passes
npm test                  # every browser test passes
uv run ffcoach doctor     # prints league config
uv run ffcoach build      # writes web/data/board.json
```

Spec requirements and where they are satisfied:

| Spec requirement | Task |
|---|---|
| Deterministic core, tested | 3–10 |
| `model/` pure, no I/O | 4, 5, 6 |
| Advisors emit findings, not prose | 9 |
| Sources behind interface with cache | 3, 7, 8 |
| Stale cache served on failure | 3, 7, 8 |
| Unmatched players reported, not dropped | 8, 10, 13 |
| UX 1 — terminology never renamed | 12 (test), 13 |
| UX 2 — explain mode, layout unchanged | 12 (test), 13 |
| UX 3 — raw number plus plain reading | 6, 12 |
| UX 4 — reason inline in both modes | 9, 12 (test) |
| UX 5 — no hardcoded format, no dollars | 2, 10 (test), 12 (test) |
| UX 6 — "how to use this" line | 13 |
| Live recompute as players are drafted | 12, 13 |
| Tests on every layer from task one | 1–13 |
