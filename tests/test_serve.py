"""F0: the local web server.

The load-bearing tests here are the two about what is *not* served.
`espn.yaml` and `notify.yaml` sit one directory above the pages, and a server
rooted a level too high would publish session cookies that authenticate as the
user and an ntfy topic anyone can publish to.
"""

import threading

import httpx
import pytest

from ffcoach.serve import DEFAULT_PORT, LOCALHOST, ServeError, build_server, web_root


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
