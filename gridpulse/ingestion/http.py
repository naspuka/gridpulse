"""Shared HTTP client + retry policy for all ingestion sources.

Why centralise:
- One user-agent + timeout policy everywhere — sources see consistent client
  behaviour and we can change it in one place.
- One retry policy that's "right" for talk-to-flaky-public-API: retry on
  network errors and 5xx, give up on 4xx (those need code changes, not retries).
- One place to wire structured logging when we add it.

Architecture note: per CLAUDE.md, retries are layered. tenacity here handles
transient HTTP failures (one ingestion call). Dagster handles asset-level
retries (transient bugs). Dagster's daemon handles schedule-level recovery
(the next tick fires regardless). Each layer absorbs a different failure mode.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

USER_AGENT = "gridpulse/0.1 (+https://gridpulse.uk)"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
DEFAULT_MAX_ATTEMPTS = 3


class TransientHttpError(Exception):
    """Raised by `raise_for_transient_status()` for 5xx / 429.

    Tenacity retries on this; on 4xx we let httpx.HTTPStatusError propagate
    (those are not transient — schema change, auth issue, etc.).
    """


def raise_for_transient_status(response: httpx.Response) -> None:
    """Mark 5xx and 429 as transient (retryable); leave 4xx as fatal."""
    if response.status_code >= 500 or response.status_code == 429:
        raise TransientHttpError(f"transient {response.status_code} from {response.request.url}")
    response.raise_for_status()


@contextmanager
def http_client(
    *,
    base_url: str = "",
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
) -> Iterator[httpx.Client]:
    """Yield a configured httpx.Client. Use as a context manager.

    Example:
        with http_client(base_url="https://api.carbonintensity.org.uk") as client:
            r = client.get("/intensity")
            raise_for_transient_status(r)
            return r.json()
    """
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers |= headers
    with httpx.Client(
        base_url=base_url,
        headers=merged_headers,
        timeout=timeout or DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        yield client


def http_retry(max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> Retrying:
    """Standard retry policy: 3 attempts, exponential backoff 1s → 4s → 16s.

    Retries on transient HTTP failures and network errors. Does NOT retry
    on httpx.HTTPStatusError (4xx) — those are caller bugs.

    Usage:
        for attempt in http_retry():
            with attempt:
                r = client.get("/foo")
                raise_for_transient_status(r)
                return r.json()
    """
    return Retrying(
        retry=retry_if_exception_type((TransientHttpError, httpx.TransportError)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        reraise=True,
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
