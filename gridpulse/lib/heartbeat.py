"""Healthchecks.io heartbeat decorator for Dagster assets (and anything else).

Design:
- One env var, `HEALTHCHECKS_PING_KEY`, holds the project's ping key.
  Each asset's URL is `https://hc-ping.com/<key>/<slug>`. Healthchecks.io
  auto-creates the check on the first ping.
- The decorator wraps a callable and fires three kinds of ping:
  - `/start` immediately before the function runs (gives a duration metric)
  - `/<slug>`        on success
  - `/<slug>/fail`   on exception (then re-raises)
- **Fail-open**: if Healthchecks is unreachable or `HEALTHCHECKS_PING_KEY`
  is unset, the asset still runs successfully. Heartbeats are observability,
  not correctness — they should NEVER make the pipeline less reliable.
- Short HTTP timeouts (3s) so a slow healthchecks.io can't slow down ingest.

Usage:

    @asset(...)
    @with_heartbeat("carbon_intensity_national")
    def carbon_intensity_national(context):
        ...

Decoration order matters: `@with_heartbeat` is innermost so it wraps the
actual function before Dagster's `@asset` does.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

log = logging.getLogger(__name__)

# Short and cheap — fail-open if healthchecks is slow.
_PING_TIMEOUT_SECONDS = 3.0
_HC_PING_BASE = "https://hc-ping.com"

F = TypeVar("F", bound=Callable[..., Any])


def _ping(slug: str, suffix: str = "") -> None:
    """Fire a single ping. Swallow all errors — observability never breaks the run."""
    key = os.environ.get("HEALTHCHECKS_PING_KEY", "").strip()
    if not key:
        return
    url = f"{_HC_PING_BASE}/{key}/{slug}{suffix}"
    try:
        httpx.get(url, timeout=_PING_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        log.warning("healthchecks ping failed (slug=%s, suffix=%s): %s", slug, suffix, exc)


def with_heartbeat(slug: str) -> Callable[[F], F]:
    """Return a decorator that emits start/success/fail pings around the wrapped call.

    The slug identifies the check in Healthchecks.io. Same slug across
    re-runs reuses the same check entry; new slugs auto-create new checks.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _ping(slug, suffix="/start")
            try:
                result = func(*args, **kwargs)
            except Exception:
                _ping(slug, suffix="/fail")
                raise
            _ping(slug)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
