"""Sentry SDK init — call once per process at startup.

Reads config from env:
- `SENTRY_DSN`           : DSN; if absent, init is a no-op (local dev friendly).
- `ENVIRONMENT`          : tag attached to every event (local, production, ci, …).
- `GIT_SHA`              : release version; tied to git commit so tracebacks
                           link to the right code.
- `SENTRY_TRACES_RATE`   : float 0.0-1.0 sampling rate for performance traces.
                           Default 0.0 (errors-only) to stay inside the free
                           plan's event budget.
"""

from __future__ import annotations

import logging
import os

import sentry_sdk

log = logging.getLogger(__name__)


def init_sentry(component: str) -> None:
    """Initialise Sentry for the given component (e.g. 'api', 'dagster').

    No-op if SENTRY_DSN is unset — keeps `make up` working without a Sentry account.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("SENTRY_DSN not set; Sentry disabled (component=%s)", component)
        return

    environment = os.environ.get("ENVIRONMENT", "local")
    release = os.environ.get("GIT_SHA", "dev")
    traces_rate = float(os.environ.get("SENTRY_TRACES_RATE", "0.0"))

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_rate,
        # Capture INFO+ as breadcrumbs, send WARNING+ events. Sensible default
        # to keep noise low without losing context on a real error.
        # Tag the component so we can filter "api errors" vs "dagster errors".
        # (sentry_sdk auto-tags `server_name` as host; component is ours.)
        send_default_pii=False,
    )
    sentry_sdk.set_tag("component", component)
    log.info(
        "Sentry initialised: component=%s, environment=%s, release=%s",
        component,
        environment,
        release,
    )
