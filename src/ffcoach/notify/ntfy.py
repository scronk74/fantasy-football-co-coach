"""ntfy delivery: one HTTP POST, no account, no carrier, no credentials.

Chosen as the first channel (D-042) because it has the shortest path from
"nothing" to "a real alert on a real phone": publish to a topic URL, subscribe
in the app, done. No SMTP, no app password, no OAuth, no carrier gateway.

**The topic name is the credential.** A public ntfy topic has no auth at all --
anyone who knows the name can read your alerts and publish to them. So it must
be unguessable, it lives in a gitignored file, and nothing in this codebase
prints it. `doctor` reports that a topic is configured, never which.

Follows the source-module template's ownership dance for the same reason the
sources do: an injected client is the test seam, and a client we opened is a
client we must close.
"""

from __future__ import annotations

import httpx

from ffcoach.notify.base import DeliveryError, Notification

DEFAULT_SERVER = "https://ntfy.sh"
TIMEOUT_SECONDS = 10.0

# ntfy's own 1-5 scale. 4 is "high": it bypasses a phone's normal grouping and
# vibrates. 5 exists and is deliberately unused -- it overrides Do Not Disturb,
# which is not a thing a fantasy football tool gets to do.
_PRIORITY = {"interrupt": 4, "digest": 3}


class NtfyNotifier:
    """Publishes to one ntfy topic."""

    name = "ntfy"

    def __init__(
        self,
        topic: str,
        server: str = DEFAULT_SERVER,
        client: httpx.Client | None = None,
    ) -> None:
        if not topic:
            raise DeliveryError("ntfy topic is empty; nothing would be delivered")
        self._topic = topic
        self._server = server.rstrip("/")
        self._client = client
        self._owns_client = client is None

    @property
    def url(self) -> str:
        """ntfy's JSON publishing endpoint: the server root, topic in the body.

        Not `{server}/{topic}` with a `Title:` header, which is the obvious
        shape and is broken. **HTTP headers are ASCII**, and the titles this
        tool generates contain an em dash -- "1 lineup fix - week 5" -- so the
        header form raises `UnicodeEncodeError` before anything is sent. Caught
        by a test rather than by the first real alert of the season.
        """
        return self._server

    def send(self, notification: Notification) -> None:
        client = self._client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            response = client.post(
                self.url,
                json={
                    "topic": self._topic,
                    "title": notification.title,
                    "message": notification.body,
                    "priority": _PRIORITY.get(notification.tier, 3),
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # The topic is deliberately absent from this message: a delivery
            # error is the most likely thing to end up pasted into an issue.
            raise DeliveryError(f"ntfy delivery failed ({self._server}): {exc}") from exc
        finally:
            if self._owns_client:
                client.close()


class ConsoleNotifier:
    """Prints instead of sending. What `--dry-run` uses.

    A real implementation of the interface rather than a branch inside the
    caller, so the dry run exercises the same code path as a real send and
    cannot drift from it.
    """

    name = "console"

    def __init__(self, stream=None) -> None:
        self._stream = stream

    def send(self, notification: Notification) -> None:
        import sys

        stream = self._stream or sys.stdout
        print(f"[{notification.tier}] {notification.title}", file=stream)
        print(notification.body, file=stream)
