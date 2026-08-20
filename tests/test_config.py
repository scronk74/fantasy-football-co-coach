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
