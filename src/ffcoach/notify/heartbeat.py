"""The off-host half of the dead-man's switch.

`watchdog.py` notices that the *check* has stopped working. It cannot notice
that the *machine* has stopped working, because it runs on that machine. No
amount of care on one host fixes this: a process on a dead computer reports
nothing about the computer being dead.

The only construction that survives its own host dying is one where **absence
is the signal.** This pings an external service after every successful run;
that service alerts you when the pings stop. The failure it catches is the one
R-3 is about -- the iMac asleep, unplugged, off the network, or with launchd
quietly unloaded.

Deliberately a **bare URL**, not an integration. healthchecks.io, Cronitor,
Better Stack, Uptime Kuma's push endpoint and a self-hosted script all accept
"GET this URL to say I am alive", so a URL costs nothing and locks in nothing.
`fail_url` is separate and optional rather than guessed by appending `/fail`,
which is one vendor's convention and silently wrong for the others.

The ping URL is a credential: whoever has it can forge a heartbeat, which is
worse than useless -- it makes a dead machine look alive.
"""

from __future__ import annotations

import httpx

TIMEOUT_SECONDS = 10.0


class Heartbeat:
    def __init__(self, url: str, fail_url: str = "", client: httpx.Client | None = None):
        self._url = url
        self._fail_url = fail_url
        self._client = client
        self._owns_client = client is None

    def ping(self, ok: bool = True) -> str | None:
        """Say we are alive, or explicitly that we are not.

        Returns an error string rather than raising. A heartbeat that cannot be
        sent must never take down the run it was reporting on -- the check
        completing is the thing that mattered, and a missed ping degrades into
        exactly the alert the service exists to produce.
        """
        url = self._url if ok else self._fail_url
        if not url:
            return None
        client = self._client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            client.get(url).raise_for_status()
            return None
        except httpx.HTTPError as exc:
            # The URL is omitted: it is a credential, and this string is logged.
            return f"heartbeat ping failed: {type(exc).__name__}"
        finally:
            if self._owns_client:
                client.close()
