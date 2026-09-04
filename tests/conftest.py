"""Keep the suite out of the developer's own working directory.

Several CLI options default to a path relative to the current directory --
`--log` to `.ffcoach-runs.jsonl`, `--notify-config` to `notify.yaml`, `--cache`
to `.ffcoach.sqlite3`. Any test that did not override every one of them was
reading and writing the *real* files: 463 test records had accumulated in the
actual run log, and `_watch` was loading the developer's real `notify.yaml` on
every check test. Had a heartbeat URL been configured there, the suite would
have been pinging a live monitoring service and faking a healthy machine.

Chdir-per-test rather than fixing each call site: the defaults are the whole
point of those options, so the next test written will forget again. Every path
the suite actually depends on (`tests/fixtures/...`) is absolute already.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    scratch = tmp_path / "cwd"
    scratch.mkdir(exist_ok=True)
    monkeypatch.chdir(scratch)
    yield scratch
