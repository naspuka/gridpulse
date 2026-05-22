"""Tests for the healthchecks.io heartbeat decorator.

Three invariants to lock in:
1. Pings are made to the right URLs (start, success, fail).
2. The decorator is fail-open: if Healthchecks is unreachable, the wrapped
   call still succeeds and the exception in the ping is swallowed.
3. With no PING_KEY env var, the decorator is a complete no-op.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from gridpulse.lib.heartbeat import with_heartbeat


def test_success_pings_start_and_then_slug(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setenv("HEALTHCHECKS_PING_KEY", "TESTKEY")
    httpx_mock.add_response(url="https://hc-ping.com/TESTKEY/foo/start")
    httpx_mock.add_response(url="https://hc-ping.com/TESTKEY/foo")

    @with_heartbeat("foo")
    def work() -> int:
        return 42

    assert work() == 42
    # 2 pings: /start then /<slug>
    assert len(httpx_mock.get_requests()) == 2


def test_failure_pings_start_and_then_fail_and_reraises(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setenv("HEALTHCHECKS_PING_KEY", "TESTKEY")
    httpx_mock.add_response(url="https://hc-ping.com/TESTKEY/foo/start")
    httpx_mock.add_response(url="https://hc-ping.com/TESTKEY/foo/fail")

    @with_heartbeat("foo")
    def boom() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        boom()
    assert len(httpx_mock.get_requests()) == 2


def test_no_ping_key_is_a_no_op(monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock) -> None:
    # Explicitly unset. With pytest-httpx, no response added means any HTTP
    # call would error — proving we made zero calls.
    monkeypatch.delenv("HEALTHCHECKS_PING_KEY", raising=False)

    @with_heartbeat("foo")
    def work() -> str:
        return "ok"

    assert work() == "ok"
    assert httpx_mock.get_requests() == []


def test_fail_open_when_healthchecks_unreachable(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    """If Healthchecks errors, the wrapped function STILL completes successfully."""
    monkeypatch.setenv("HEALTHCHECKS_PING_KEY", "TESTKEY")
    # Both pings raise — but the wrapped call must still return its value.
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    httpx_mock.add_exception(httpx.ConnectError("boom"))

    @with_heartbeat("foo")
    def work() -> str:
        return "still ok"

    assert work() == "still ok"


def test_empty_string_ping_key_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    # A blank value (e.g. unfilled .env.example) must also be a no-op.
    monkeypatch.setenv("HEALTHCHECKS_PING_KEY", "")

    @with_heartbeat("foo")
    def work() -> int:
        return 1

    assert work() == 1
    assert httpx_mock.get_requests() == []
