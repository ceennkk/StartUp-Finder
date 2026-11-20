from __future__ import annotations

import httpx
import pytest

from app.http.client import HttpFetchError, PoliteHttpClient, RobotsDisallowed, parse_retry_after


def make(handler, sleeps: list[float] | None = None, **kw) -> PoliteHttpClient:
    sleeps = sleeps if sleeps is not None else []
    return PoliteHttpClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        max_retries=2,
        **kw,
    )


def test_retries_429_and_honors_retry_after() -> None:
    calls, sleeps = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    assert make(handler, sleeps).get_json("https://api.test/x") == {"ok": True}
    assert len(calls) == 3
    assert sleeps.count(7.0) == 2


def test_gives_up_after_max_retries() -> None:
    client = make(lambda r: httpx.Response(503))
    with pytest.raises(HttpFetchError) as err:
        client.get("https://api.test/x")
    assert err.value.status_code == 503


def test_client_errors_are_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(HttpFetchError) as err:
        make(handler).get("https://api.test/x")
    assert err.value.status_code == 404 and len(calls) == 1


def test_ok_statuses_allows_304() -> None:
    assert make(lambda r: httpx.Response(304)).get("https://api.test/x", ok_statuses={304}).status_code == 304


def test_transport_errors_are_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text="fine")

    assert make(handler).get("https://api.test/x").text == "fine"


def test_per_host_spacing() -> None:
    sleeps, clock = [], [0.0]
    client = make(lambda r: httpx.Response(200), sleeps, min_interval=3.0, monotonic=lambda: clock[0])
    client.get("https://a.test/1")
    clock[0] = 1.0
    client.get("https://a.test/2")
    assert sleeps == [2.0]


def test_robots_txt_is_respected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\nCrawl-delay: 30\n")
        return httpx.Response(200, text="page")

    client = make(handler)
    assert client.get("https://site.test/public", respect_robots=True).text == "page"
    with pytest.raises(RobotsDisallowed):
        client.get("https://site.test/private/x", respect_robots=True)
    assert client.crawl_delay("https://site.test/public") == 30.0


def test_missing_robots_means_allowed() -> None:
    client = make(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(200, text="ok"))
    assert client.get("https://site.test/a", respect_robots=True).text == "ok"


def test_parse_retry_after() -> None:
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
