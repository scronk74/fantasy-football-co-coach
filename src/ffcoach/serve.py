"""A small local web server for the pages. Python stdlib only (D-040).

Two things forced this over "just use Live Server". Requiring a VS Code
extension is real friction for a tool checked weekly, and **notification
control (F2) is impossible as static HTML** -- a page cannot write your config
file. It matters more now than when D-040 was written: once the iMac runs the
scheduler, it is the machine holding fresh `web/data/*.json`, and the laptop
needs some way to read them.

**The security-relevant part.** `espn.yaml` and `notify.yaml` live in the repo
root, one directory above the pages. A server rooted at the repo would publish
session cookies that authenticate as the user and an ntfy topic anyone can
publish to. So the root is `web/` explicitly, it is resolved and checked before
the socket is opened, and `SimpleHTTPRequestHandler` normalises `..` away
before mapping a path.

**And the correctness-relevant part.** `check.json` is rewritten every time the
scheduler runs. Served with default headers a browser will happily re-use a
cached copy, so the page would show last hour's findings with this hour's
confidence -- the same lie `SourceResult` exists to prevent, arriving through
the HTTP layer instead.
"""

from __future__ import annotations

import socket
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

DEFAULT_PORT = 8765
LOCALHOST = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"


class ServeError(Exception):
    """The server cannot start, which is better than serving the wrong tree."""


class NoStoreHandler(SimpleHTTPRequestHandler):
    """Serves the pages, and refuses to let a browser cache the data."""

    def end_headers(self) -> None:
        if self.path.endswith(".json"):
            # A cached check.json shows last hour's findings with this hour's
            # confidence. Everything else may cache normally.
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        # One line per request would bury the "serving at" line the user needs,
        # and the run log is where anything durable belongs.
        return


def web_root(start: Path | None = None) -> Path:
    """The `web/` directory to serve, or refuse to guess.

    Refusing matters: a plausible fallback here is the repo root, which is
    where the credentials live.
    """
    base = Path(start) if start else Path.cwd()
    candidate = base if base.name == "web" else base / "web"
    candidate = candidate.resolve()
    if not (candidate / "index.html").is_file():
        raise ServeError(
            f"no pages found at {candidate} (expected index.html). "
            "Run this from the project directory."
        )
    return candidate


def lan_address() -> str | None:
    """This machine's LAN address, or None if it cannot be determined.

    Uses a UDP socket to a routable address, which picks the interface the OS
    would actually route through without sending a packet. `gethostbyname` on
    macOS frequently answers 127.0.0.1, which would print a URL that works only
    on the machine already running the server.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: reserved, never routed
        address = probe.getsockname()[0]
        return address if not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        probe.close()


def build_server(root: Path, host: str, port: int) -> HTTPServer:
    handler = partial(NoStoreHandler, directory=str(root))
    try:
        return HTTPServer((host, port), handler)
    except OSError as exc:
        raise ServeError(
            f"could not listen on {host}:{port} ({exc}). "
            "Another copy may already be running; try --port."
        ) from exc
