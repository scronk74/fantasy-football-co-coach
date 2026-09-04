import textwrap

import pytest

from ffcoach.config import ConfigError, EspnCredentials, LeagueConfig, load_config, load_espn_credentials


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


ESPN_VALID = """
    league_id: "123456"
    season: 2026
    espn_s2: "some-long-token"
    swid: "{ABCDEF12-3456-7890-ABCD-EF1234567890}"
"""


def write_espn(tmp_path, body):
    p = tmp_path / "espn.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_loads_valid_espn_credentials(tmp_path):
    creds = load_espn_credentials(write_espn(tmp_path, ESPN_VALID))
    assert creds == EspnCredentials(
        league_id="123456",
        season=2026,
        espn_s2="some-long-token",
        swid="{ABCDEF12-3456-7890-ABCD-EF1234567890}",
    )


def test_espn_credentials_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_espn_credentials(tmp_path / "espn.yaml")


def test_espn_credentials_missing_keys_raises_config_error(tmp_path):
    bad = ESPN_VALID.replace('swid: "{ABCDEF12-3456-7890-ABCD-EF1234567890}"', "")
    with pytest.raises(ConfigError, match="missing required keys"):
        load_espn_credentials(write_espn(tmp_path, bad))


# --- notification config: the topic is a credential ---

from ffcoach.config import load_notify_config  # noqa: E402


def write(tmp_path, text):
    p = tmp_path / "notify.yaml"
    p.write_text(text)
    return p


def test_a_valid_ntfy_config_loads(tmp_path):
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough'}\n")
    conf = load_notify_config(p)
    assert conf.channel == "ntfy"
    assert conf.topic == "x8Fj2kQ-longenough"
    assert conf.server == "https://ntfy.sh"


def test_a_self_hosted_server_overrides_the_default(tmp_path):
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough', server: 'https://n.example.com'}\n")
    assert load_notify_config(p).server == "https://n.example.com"


def test_a_missing_file_names_the_example_to_copy(tmp_path):
    with pytest.raises(ConfigError, match="notify.example.yaml"):
        load_notify_config(tmp_path / "absent.yaml")


def test_an_unsupported_channel_is_refused_rather_than_ignored(tmp_path):
    """Silently doing nothing would look exactly like a quiet week."""
    p = write(tmp_path, "channel: carrier-pigeon\nntfy: {topic: 'x'}\n")
    with pytest.raises(ConfigError, match="unknown notification channel"):
        load_notify_config(p)


def test_an_empty_topic_is_refused(tmp_path):
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: '   '}\n")
    with pytest.raises(ConfigError, match="topic is required"):
        load_notify_config(p)


def test_a_guessable_topic_is_refused(tmp_path):
    """A public ntfy topic has no authentication at all: the name is the key."""
    for guessable in ("ffcoach", "fantasy", "test", "alerts"):
        p = write(tmp_path, f"channel: ntfy\nntfy: {{topic: '{guessable}'}}\n")
        with pytest.raises(ConfigError, match="guessable"):
            load_notify_config(p)


# --- E3 config ---


def test_watchdog_defaults_are_sane_without_a_watchdog_block(tmp_path):
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough'}\n")
    conf = load_notify_config(p)
    assert conf.max_silence_hours == 12
    assert conf.min_consecutive_failures == 3
    assert conf.has_heartbeat is False


def test_a_heartbeat_url_is_read_and_reported_as_configured(tmp_path):
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough'}\n"
                        "heartbeat: {url: 'https://hc-ping.com/abc'}\n")
    conf = load_notify_config(p)
    assert conf.has_heartbeat
    assert conf.heartbeat_url == "https://hc-ping.com/abc"
    assert conf.heartbeat_fail_url == ""


def test_a_single_failure_threshold_is_refused(tmp_path):
    """One is not a streak. A flaky fetch would page you, and a channel that
    cries wolf is the one you mute before the week that matters."""
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough'}\n"
                        "watchdog: {min_consecutive_failures: 1}\n")
    with pytest.raises(ConfigError, match="at least 2"):
        load_notify_config(p)


def test_a_zero_silence_window_is_refused(tmp_path):
    """It would trip on every run, forever."""
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough'}\n"
                        "watchdog: {max_silence_hours: 0}\n")
    with pytest.raises(ConfigError, match="must be positive"):
        load_notify_config(p)


def test_a_non_numeric_watchdog_value_is_refused_rather_than_defaulted(tmp_path):
    """Silently falling back would leave the user believing a value they set."""
    p = write(tmp_path, "channel: ntfy\nntfy: {topic: 'x8Fj2kQ-longenough'}\n"
                        "watchdog: {max_silence_hours: soon}\n")
    with pytest.raises(ConfigError, match="must be numbers"):
        load_notify_config(p)
