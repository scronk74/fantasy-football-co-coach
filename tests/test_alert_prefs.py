"""D4: which findings are allowed to reach a phone.

Two properties carry the weight here, and both point the same way -- toward
alerting rather than toward silence.

**Absence means on.** The file records what is switched *off*, so a kind this
build has never seen (one a later version writes, one an older file predates)
still alerts. The cost of the other default is a missed lineup fix, which is
the only failure this product exists to prevent.

**A mute is an instant.** There is no permanent one, because a permanent mute
set in September is a silent November.
"""

import datetime as dt

import pytest

from ffcoach.config import (
    ALERT_KINDS,
    AlertPrefs,
    ConfigError,
    load_alert_prefs,
    prefs_from_payload,
    save_alert_prefs,
)

ET = dt.timezone(dt.timedelta(hours=-4))
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=ET)


# --- defaults ---


def test_a_missing_file_is_the_old_behaviour_not_an_error(tmp_path):
    """An install that never opens the Alerts page must keep working."""
    prefs = load_alert_prefs(tmp_path / "nope.yaml")
    assert prefs == AlertPrefs()
    assert all(prefs.sends(kind) for kind in ALERT_KINDS)


def test_an_unknown_kind_is_allowed_to_alert(tmp_path):
    """The direction is chosen: an unrecognized kind costs a message you did
    not need, never a missed one you did."""
    path = tmp_path / "alerts.yaml"
    path.write_text("kinds:\n  out: off\n")
    prefs = load_alert_prefs(path)
    assert not prefs.sends("out")
    assert prefs.sends("some_kind_from_2027")


def test_an_empty_file_reads_as_defaults(tmp_path):
    path = tmp_path / "alerts.yaml"
    path.write_text("")
    assert load_alert_prefs(path) == AlertPrefs()


# --- round trip ---


def test_what_is_saved_is_what_is_read_back(tmp_path):
    path = tmp_path / "alerts.yaml"
    original = AlertPrefs(
        disabled_kinds=frozenset({"bye_next_week", "bye"}),
        quiet_enabled=False,
        quiet_start=22,
        quiet_end=7,
        mute_until=NOW + dt.timedelta(hours=3),
    )
    save_alert_prefs(path, original)
    assert load_alert_prefs(path) == original


def test_the_written_file_keeps_its_explanations(tmp_path):
    """A full rewrite is only safe because the comments are generated. If they
    stop being written, the next hand-editor has an undocumented file."""
    path = tmp_path / "alerts.yaml"
    save_alert_prefs(path, AlertPrefs())
    text = path.read_text()
    assert "notify.yaml" in text
    assert "no credentials" in text


def test_the_written_file_names_every_kind(tmp_path):
    """So the file itself is the list of what can be switched off."""
    path = tmp_path / "alerts.yaml"
    save_alert_prefs(path, AlertPrefs())
    for kind in ALERT_KINDS:
        assert f"  {kind}: " in path.read_text()


def test_a_kind_this_build_does_not_know_survives_a_save(tmp_path):
    """Saving from an older version must not silently re-enable something a
    newer one switched off."""
    path = tmp_path / "alerts.yaml"
    save_alert_prefs(path, AlertPrefs(disabled_kinds=frozenset({"future_kind"})))
    assert "future_kind: off" in path.read_text()


# --- refusals ---


def test_a_naive_mute_is_refused_rather_than_read_as_utc(tmp_path):
    """The same rule `--now` follows. A four-hour error in when silence lifts
    is invisible and lands on a Sunday afternoon."""
    path = tmp_path / "alerts.yaml"
    path.write_text('mute_until: "2026-09-13T17:00"\n')
    with pytest.raises(ConfigError, match="offset"):
        load_alert_prefs(path)


def test_an_unparseable_mute_names_the_shape_it_wanted(tmp_path):
    path = tmp_path / "alerts.yaml"
    path.write_text('mute_until: "next tuesday"\n')
    with pytest.raises(ConfigError, match="ISO"):
        load_alert_prefs(path)


@pytest.mark.parametrize("hour", [-1, 24, "noon"])
def test_an_impossible_quiet_hour_is_refused(tmp_path, hour):
    path = tmp_path / "alerts.yaml"
    path.write_text(f"quiet_hours:\n  start: {hour}\n")
    with pytest.raises(ConfigError, match="0-23"):
        load_alert_prefs(path)


def test_malformed_yaml_is_refused_with_the_path(tmp_path):
    path = tmp_path / "alerts.yaml"
    path.write_text("kinds: [this is not a mapping]\n")
    with pytest.raises(ConfigError, match="kinds"):
        load_alert_prefs(path)


# --- the mute clock ---


def test_a_mute_lapses_by_itself():
    prefs = AlertPrefs(mute_until=NOW + dt.timedelta(hours=1))
    assert prefs.muted_at(NOW)
    assert not prefs.muted_at(NOW + dt.timedelta(hours=2))


def test_no_mute_is_not_a_mute():
    assert not AlertPrefs().muted_at(NOW)


# --- what the control page may post ---


def test_a_payload_switches_a_kind_off():
    prefs = prefs_from_payload({"kinds": {"bye_next_week": False}})
    assert not prefs.sends("bye_next_week")
    assert prefs.sends("out")


def test_an_unknown_kind_over_http_is_refused_not_stored():
    """Tolerated in a file, refused on the wire: a typo that saves cleanly
    while the real alert keeps firing is the worst of both."""
    with pytest.raises(ConfigError, match="unknown alert kind"):
        prefs_from_payload({"kinds": {"bye_next_wek": False}})


def test_an_omitted_field_keeps_its_current_value():
    current = AlertPrefs(disabled_kinds=frozenset({"bye"}), quiet_start=21)
    prefs = prefs_from_payload({"quiet_hours": {"start": 22, "end": 6}}, current)
    assert not prefs.sends("bye")
    assert prefs.quiet_start == 22


def test_an_omitted_mute_is_left_alone_but_an_empty_one_clears_it():
    current = AlertPrefs(mute_until=NOW)
    assert prefs_from_payload({}, current).mute_until == NOW
    assert prefs_from_payload({"mute_until": ""}, current).mute_until is None


def test_equal_quiet_bounds_are_refused():
    """`QuietHours.covers` reads them as an empty window, so the page would
    show quiet hours enabled while nothing was ever held."""
    with pytest.raises(ConfigError, match="differ"):
        prefs_from_payload({"quiet_hours": {"enabled": True, "start": 8, "end": 8}})
