"""The single-scheduler guard.

Two machines running the check means every alert twice -- alert history is a
local SQLite file -- and, far worse, a laptop that checks occasionally keeps
the heartbeat green while the scheduler machine is face-down. That is E3
defeated: the dead-man's switch cannot tell "the iMac is fine" from "the
laptop pinged for it".
"""

from ffcoach.host import is_scheduler_host, normalize_host, this_host


def test_an_unset_host_lets_everything_through():
    """One machine is the common case. A guard you must configure before
    anything works is a setup step that buys nothing until a second machine."""
    assert is_scheduler_host("") is True
    assert is_scheduler_host("   ") is True


def test_this_machine_matches_itself():
    assert is_scheduler_host(this_host()) is True


def test_another_machine_does_not():
    assert is_scheduler_host("some-other-box") is False


def test_the_mdns_suffix_is_ignored():
    """macOS returns `MacBook-Air.local` on one network and `MacBook-Air` on
    another. A guard that fires after a Wi-Fi change is a guard that gets
    deleted."""
    assert normalize_host("Steve-iMac.local") == normalize_host("steve-imac")
    assert is_scheduler_host(this_host() + ".local") is True


def test_case_and_trailing_dots_are_ignored():
    assert normalize_host("STEVE-IMAC.") == "steve-imac"
    assert normalize_host("  Steve-iMac  ") == "steve-imac"


def test_other_common_suffixes_are_handled():
    for suffix in (".lan", ".home", ".localdomain"):
        assert normalize_host("box" + suffix) == "box"


def test_only_one_suffix_is_stripped():
    """`.local.local` is not a thing, and chewing repeatedly could eat a real
    name like `my.home` down to nothing."""
    assert normalize_host("my.home.local") == "my.home"


def test_an_empty_name_normalises_to_empty_rather_than_raising():
    assert normalize_host("") == ""
    assert normalize_host(None) == ""
