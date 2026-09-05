"""F0: the local web server.

The load-bearing tests here are the two about what is *not* served.
`espn.yaml` and `notify.yaml` sit one directory above the pages, and a server
rooted a level too high would publish session cookies that authenticate as the
user and an ntfy topic anyone can publish to.
"""

import threading

import httpx
import pytest

from ffcoach.serve import (
    DEFAULT_PORT,
    LOCALHOST,
    NoStoreHandler,
    ServeError,
    build_server,
    web_root,
)


@pytest.fixture
def project(tmp_path):
    """A directory shaped like the repo: pages inside, secrets outside."""
    web = tmp_path / "web"
    (web / "data").mkdir(parents=True)
    (web / "index.html").write_text("<h1>This Week</h1>")
    (web / "data" / "check.json").write_text('{"week": 1}')
    (tmp_path / "espn.yaml").write_text("espn_s2: SUPERSECRET\nswid: '{S}'\n")
    (tmp_path / "notify.yaml").write_text("ntfy:\n  topic: SECRETTOPIC\n")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_refresh_cooldown():
    """The cooldown is class state, so one test must not gate the next."""
    NoStoreHandler._last_refresh = 0.0
    yield
    NoStoreHandler._last_refresh = 0.0


@pytest.fixture
def server(project):
    srv = build_server(web_root(project), LOCALHOST, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://{LOCALHOST}:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


# --- what is served ---


def test_the_pages_are_served(server):
    response = httpx.get(f"{server}/index.html")
    assert response.status_code == 200
    assert "This Week" in response.text


def test_the_index_is_the_default_document(server):
    assert "This Week" in httpx.get(f"{server}/").text


def test_the_payloads_are_served(server):
    assert httpx.get(f"{server}/data/check.json").json() == {"week": 1}


# --- what is NOT served ---


def test_the_credentials_one_directory_up_are_unreachable(server):
    """The whole reason the root is `web/` and not the project directory."""
    for attempt in (
        "/../espn.yaml",
        "/../notify.yaml",
        "/..%2fespn.yaml",
        "/data/../../espn.yaml",
        "/%2e%2e/espn.yaml",
    ):
        response = httpx.get(f"{server}{attempt}")
        assert "SUPERSECRET" not in response.text, attempt
        assert "SECRETTOPIC" not in response.text, attempt


def test_an_absolute_path_escape_is_refused(server):
    assert "SUPERSECRET" not in httpx.get(f"{server}//etc/hosts").text


# --- caching: a stale payload is a lie with a fresh face ---


def test_json_is_never_cached(server):
    """`check.json` is rewritten every scheduler run. A cached copy shows last
    hour's findings with this hour's confidence."""
    headers = httpx.get(f"{server}/data/check.json").headers
    assert "no-store" in headers.get("cache-control", "")


def test_html_may_cache_normally(server):
    """Only the data is volatile; forbidding all caching would be cargo cult."""
    assert "no-store" not in httpx.get(f"{server}/index.html").headers.get(
        "cache-control", ""
    )


# --- refusing to guess the root ---


def test_a_directory_with_no_pages_is_refused(tmp_path):
    """A plausible fallback here is the repo root, which is where the
    credentials live. So there is no fallback."""
    with pytest.raises(ServeError, match="no pages found"):
        web_root(tmp_path)


def test_running_from_inside_web_works_too(project):
    assert web_root(project / "web") == (project / "web").resolve()


def test_running_from_the_project_directory_finds_web(project):
    assert web_root(project) == (project / "web").resolve()


def test_a_busy_port_is_reported_rather_than_silently_failing(project):
    first = build_server(web_root(project), LOCALHOST, 0)
    try:
        with pytest.raises(ServeError, match="could not listen"):
            build_server(web_root(project), LOCALHOST, first.server_address[1])
    finally:
        first.server_close()


def test_the_default_port_is_stable():
    """It goes in a bookmark and, eventually, in a launchd plist."""
    assert DEFAULT_PORT == 8765


# --- the health endpoint ---


@pytest.fixture
def api(project):
    calls = {"health": 0, "refresh": 0}

    def health():
        calls["health"] += 1
        return {"ok": True, "n": calls["health"]}

    def refresh():
        calls["refresh"] += 1
        return True, "done"

    srv = build_server(web_root(project), LOCALHOST, 0, health=health, refresh=refresh)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://{LOCALHOST}:{srv.server_address[1]}", calls
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_health_is_built_per_request(api):
    """A health panel served from a snapshot would report "last run 3 minutes
    ago" out of a file written three hours ago."""
    base, _ = api
    first = httpx.get(f"{base}/api/health").json()
    second = httpx.get(f"{base}/api/health").json()
    assert first["n"] == 1
    assert second["n"] == 2


def test_health_is_never_cached(api):
    base, _ = api
    headers = httpx.get(f"{base}/api/health").headers
    assert "no-store" in headers["cache-control"]


def test_refresh_is_post_only(api):
    """A GET with a side effect can be fired by an <img> tag or a link
    preview, and this one reaches out to ESPN."""
    base, calls = api
    assert httpx.get(f"{base}/api/refresh").status_code == 404
    assert calls["refresh"] == 0


def test_refresh_runs_the_check(api):
    base, calls = api
    response = httpx.post(f"{base}/api/refresh")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls["refresh"] == 1


def test_a_second_refresh_is_refused_rather_than_silently_ignored(api):
    """A held-down button must not become a load generator, and a button that
    appears to work while doing nothing is worse than one that says "not yet"."""
    base, calls = api
    httpx.post(f"{base}/api/refresh")
    second = httpx.post(f"{base}/api/refresh")
    assert second.status_code == 429
    assert second.json()["retry_after_seconds"] > 0
    assert calls["refresh"] == 1


def test_an_unknown_api_path_is_a_json_404(api):
    base, _ = api
    assert httpx.post(f"{base}/api/nope").status_code == 404


def test_a_server_without_the_endpoints_says_so_rather_than_500ing(server):
    assert httpx.get(f"{server}/api/health").status_code == 503
    assert httpx.post(f"{server}/api/refresh").status_code == 503


def test_two_servers_do_not_share_endpoint_state(project):
    """The handlers are bound to a subclass, not the shared class."""
    a = build_server(web_root(project), LOCALHOST, 0, health=lambda: {"which": "a"})
    b = build_server(web_root(project), LOCALHOST, 0, health=lambda: {"which": "b"})
    threads = []
    for srv in (a, b):
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        threads.append(t)
    try:
        got_a = httpx.get(f"http://{LOCALHOST}:{a.server_address[1]}/api/health").json()
        got_b = httpx.get(f"http://{LOCALHOST}:{b.server_address[1]}/api/health").json()
        assert (got_a["which"], got_b["which"]) == ("a", "b")
    finally:
        for srv, t in zip((a, b), threads):
            srv.shutdown()
            srv.server_close()
            t.join(timeout=5)


# --- F2: the alert-control endpoints -------------------------------------
#
# The security property worth a test rather than a comment: this endpoint
# cannot reach the ntfy topic. That is structural -- the preferences live in
# their own file -- so the test asserts the structure, not the intention.


@pytest.fixture
def prefs_server(project):
    """A server wired the way `ffcoach serve` wires one, on localhost."""
    from ffcoach.cli import _serve_prefs, _serve_save_prefs

    class Args:
        alerts_config = project / "alerts.yaml"

    args = Args()
    srv = build_server(
        web_root(project), LOCALHOST, 0,
        prefs=lambda: _serve_prefs(args),
        save_prefs=lambda body: _serve_save_prefs(args, body),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://{LOCALHOST}:{srv.server_address[1]}", args.alerts_config
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_the_preferences_are_readable_before_the_file_exists(prefs_server):
    base, path = prefs_server
    body = httpx.get(f"{base}/api/alerts").json()
    assert body["exists"] is False
    assert body["writable"] is True
    assert all(kind["enabled"] for kind in body["kinds"])


def test_every_kind_arrives_with_a_sentence_a_human_can_read(prefs_server):
    base, _ = prefs_server
    for kind in httpx.get(f"{base}/api/alerts").json()["kinds"]:
        assert kind["label"] and kind["label"] != kind["name"]


def test_the_topic_is_not_in_the_payload(prefs_server):
    """`notify.yaml` in this project holds SECRETTOPIC. It must not appear
    here, and it cannot: this endpoint never opens that file."""
    base, _ = prefs_server
    assert "SECRETTOPIC" not in httpx.get(f"{base}/api/alerts").text


def test_a_save_writes_the_file_and_reads_back(prefs_server):
    base, path = prefs_server
    response = httpx.post(f"{base}/api/alerts", json={"kinds": {"bye_next_week": False}})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert path.exists()
    after = httpx.get(f"{base}/api/alerts").json()
    off = [k["name"] for k in after["kinds"] if not k["enabled"]]
    assert off == ["bye_next_week"]


def test_a_rejected_save_answers_400_and_names_the_field(prefs_server):
    base, path = prefs_server
    response = httpx.post(f"{base}/api/alerts", json={"kinds": {"nonsense": False}})
    assert response.status_code == 400
    assert "unknown alert kind" in response.json()["message"]
    assert not path.exists()


def test_a_save_cannot_touch_the_notify_config(prefs_server, project):
    """Belt and braces on the structural claim: even a payload that names the
    topic changes nothing about where alerts go."""
    base, _ = prefs_server
    httpx.post(f"{base}/api/alerts", json={"ntfy": {"topic": "attacker"}, "topic": "attacker"})
    assert "SECRETTOPIC" in (project / "notify.yaml").read_text()
    assert "attacker" not in (project / "notify.yaml").read_text()


def test_a_body_that_is_not_an_object_is_refused(prefs_server):
    base, _ = prefs_server
    response = httpx.post(f"{base}/api/alerts", content=b"[1,2,3]",
                          headers={"Content-Type": "application/json"})
    assert response.status_code == 400


def test_an_oversized_body_is_refused_without_being_read(prefs_server):
    base, _ = prefs_server
    response = httpx.post(f"{base}/api/alerts", content=b"x" * 20000,
                          headers={"Content-Type": "application/json"})
    assert response.status_code == 400


def test_serving_to_the_network_makes_the_preferences_read_only(project):
    """`/api/refresh` already lets a network peer spend an ESPN fetch. Letting
    one silence your alerts is a different order of bad, so `--lan` refuses --
    and it is derived from the bind address, not from a flag a caller can
    forget to pass alongside `--lan`."""
    from ffcoach.cli import _serve_prefs, _serve_save_prefs
    from ffcoach.serve import ALL_INTERFACES

    class Args:
        alerts_config = project / "alerts.yaml"

    args = Args()
    srv = build_server(
        web_root(project), ALL_INTERFACES, 0,
        prefs=lambda: _serve_prefs(args),
        save_prefs=lambda body: _serve_save_prefs(args, body),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://{LOCALHOST}:{srv.server_address[1]}"
    try:
        # Readable, and it says so before anything is edited -- the page needs
        # to disable its own form rather than discover this on save.
        assert httpx.get(f"{base}/api/alerts").json()["writable"] is False

        response = httpx.post(f"{base}/api/alerts", json={"kinds": {"out": False}})
        assert response.status_code == 403
        assert "--lan" in response.json()["error"]
        assert not args.alerts_config.exists()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
