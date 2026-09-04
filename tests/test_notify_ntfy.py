"""ntfy delivery, against a mocked transport. Offline like every other test."""

import json

import httpx
import pytest

from ffcoach.notify.base import DeliveryError, Notification, Notifier
from ffcoach.notify.ntfy import ConsoleNotifier, NtfyNotifier

NOTE = Notification(title="1 lineup fix — week 5", body="OUT Hurt Guy", tier="interrupt")


def client_capturing(requests, status=200):
    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="{}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_both_channels_satisfy_the_interface():
    assert isinstance(NtfyNotifier("t", client=client_capturing([])), Notifier)
    assert isinstance(ConsoleNotifier(), Notifier)


def published(seen):
    return json.loads(seen[0].content)


def test_the_message_is_published_to_the_named_topic():
    seen = []
    NtfyNotifier("secret-topic", client=client_capturing(seen)).send(NOTE)
    assert len(seen) == 1
    assert str(seen[0].url) == "https://ntfy.sh"
    assert published(seen)["topic"] == "secret-topic"
    assert published(seen)["message"] == "OUT Hurt Guy"


def test_a_non_ascii_title_survives_the_trip():
    """The regression this file exists for.

    The obvious shape -- POST to `{server}/{topic}` with a `Title:` header --
    raises UnicodeEncodeError on the em dash every generated title contains,
    because HTTP headers are ASCII. JSON publishing is UTF-8.
    """
    seen = []
    NtfyNotifier("t", client=client_capturing(seen)).send(NOTE)
    assert published(seen)["title"] == "1 lineup fix — week 5"


def test_an_interrupt_is_sent_at_a_higher_priority_than_a_digest():
    seen = []
    n = NtfyNotifier("t", client=client_capturing(seen))
    n.send(NOTE)
    n.send(Notification(title="t", body="b", tier="digest"))
    a, b = (json.loads(r.content)["priority"] for r in seen)
    assert a > b


def test_priority_never_reaches_5():
    """5 overrides Do Not Disturb. A fantasy tool does not get to do that."""
    seen = []
    NtfyNotifier("t", client=client_capturing(seen)).send(NOTE)
    assert published(seen)["priority"] < 5


def test_a_self_hosted_server_is_honoured():
    seen = []
    NtfyNotifier("t", server="https://ntfy.example.com/", client=client_capturing(seen)).send(NOTE)
    assert str(seen[0].url) == "https://ntfy.example.com"


def test_a_failed_delivery_raises_rather_than_passing_silently():
    """D-024: a message you never got must not look like a quiet week."""
    with pytest.raises(DeliveryError, match="delivery failed"):
        NtfyNotifier("t", client=client_capturing([], status=500)).send(NOTE)


def test_a_delivery_error_never_leaks_the_topic():
    """The topic is the credential, and an error is what gets pasted into an issue."""
    with pytest.raises(DeliveryError) as exc:
        NtfyNotifier("my-secret-topic", client=client_capturing([], status=500)).send(NOTE)
    assert "my-secret-topic" not in str(exc.value)


def test_an_empty_topic_is_refused_at_construction():
    """Posting to https://ntfy.sh/ would 404 forever and look like an outage."""
    with pytest.raises(DeliveryError, match="topic is empty"):
        NtfyNotifier("")


def test_the_console_channel_prints_the_whole_notification():
    import io

    out = io.StringIO()
    ConsoleNotifier(out).send(NOTE)
    printed = out.getvalue()
    assert "1 lineup fix" in printed
    assert "OUT Hurt Guy" in printed
    assert "interrupt" in printed
