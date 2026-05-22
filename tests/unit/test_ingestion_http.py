"""Unit tests for the shared HTTP helper.

Mocks the wire with pytest-httpx so we test retry behaviour in isolation
without hitting the real Carbon Intensity API.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from gridpulse.ingestion.http import (
    TransientHttpError,
    http_client,
    http_retry,
    raise_for_transient_status,
)


def test_raise_for_transient_status_500_raises_transient(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://x.test/", status_code=503)
    with http_client(base_url="https://x.test") as client:
        r = client.get("/")
        with pytest.raises(TransientHttpError):
            raise_for_transient_status(r)


def test_raise_for_transient_status_429_raises_transient(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://x.test/", status_code=429)
    with http_client(base_url="https://x.test") as client:
        r = client.get("/")
        with pytest.raises(TransientHttpError):
            raise_for_transient_status(r)


def test_raise_for_transient_status_404_raises_httpx_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://x.test/", status_code=404)
    with http_client(base_url="https://x.test") as client:
        r = client.get("/")
        with pytest.raises(httpx.HTTPStatusError):
            raise_for_transient_status(r)


def test_raise_for_transient_status_200_no_op(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://x.test/", status_code=200, json={})
    with http_client(base_url="https://x.test") as client:
        r = client.get("/")
        raise_for_transient_status(r)  # no exception


def test_retry_recovers_from_two_500s(httpx_mock: HTTPXMock) -> None:
    # First two attempts: 503. Third: 200.
    httpx_mock.add_response(url="https://x.test/", status_code=503)
    httpx_mock.add_response(url="https://x.test/", status_code=503)
    httpx_mock.add_response(url="https://x.test/", status_code=200, json={"ok": True})

    with http_client(base_url="https://x.test") as client:
        attempts = 0
        for attempt in http_retry(max_attempts=3):
            with attempt:
                attempts += 1
                r = client.get("/")
                raise_for_transient_status(r)
                result = r.json()

    assert attempts == 3
    assert result == {"ok": True}


def test_retry_gives_up_after_max_attempts(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(url="https://x.test/", status_code=503)

    with http_client(base_url="https://x.test") as client, pytest.raises(TransientHttpError):
        for attempt in http_retry(max_attempts=3):
            with attempt:
                r = client.get("/")
                raise_for_transient_status(r)


def test_retry_does_not_retry_on_4xx(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://x.test/", status_code=404)

    with http_client(base_url="https://x.test") as client, pytest.raises(httpx.HTTPStatusError):
        for attempt in http_retry(max_attempts=3):
            with attempt:
                r = client.get("/")
                raise_for_transient_status(r)


def test_user_agent_header_is_set(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://x.test/", status_code=200, json={})
    with http_client(base_url="https://x.test") as client:
        client.get("/")
    sent = httpx_mock.get_request()
    assert sent is not None
    assert sent.headers["User-Agent"].startswith("gridpulse/")
