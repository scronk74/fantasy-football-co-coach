"""The off-host half of E3, against a mocked transport."""

import httpx

from ffcoach.notify.heartbeat import Heartbeat

URL = "https://hc-ping.com/abc-123-secret"


def client_capturing(seen, status=200):
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, text="OK")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_successful_run_pings_the_url():
    seen = []
    assert Heartbeat(URL, client=client_capturing(seen)).ping() is None
    assert seen == [URL]


def test_a_failed_run_pings_the_separate_fail_url():
    seen = []
    Heartbeat(URL, fail_url=URL + "/fail", client=client_capturing(seen)).ping(ok=False)
    assert seen == [URL + "/fail"]


def test_a_fail_url_is_never_guessed_from_the_success_url():
    """Appending `/fail` is one vendor's convention and wrong for the others.

    With no fail_url configured, a failed run simply does not ping -- and the
    absence is the signal, which is the whole point.
    """
    seen = []
    Heartbeat(URL, client=client_capturing(seen)).ping(ok=False)
    assert seen == []


def test_an_unconfigured_heartbeat_does_nothing_quietly():
    seen = []
    assert Heartbeat("", client=client_capturing(seen)).ping() is None
    assert seen == []


def test_a_failed_ping_returns_an_error_rather_than_raising():
    """A heartbeat that cannot be sent must not take down the run it reports on.

    A missed ping degrades into exactly the alert the service exists to make.
    """
    err = Heartbeat(URL, client=client_capturing([], status=500)).ping()
    assert err and "heartbeat ping failed" in err


def test_a_ping_error_never_leaks_the_url():
    """Whoever has the URL can forge a heartbeat, which makes a dead machine
    look alive -- strictly worse than no monitoring."""
    err = Heartbeat(URL, client=client_capturing([], status=500)).ping()
    assert "abc-123-secret" not in err


def test_a_network_error_is_caught_too():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert "heartbeat ping failed" in Heartbeat(URL, client=client).ping()
