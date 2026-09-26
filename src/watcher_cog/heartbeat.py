"""Healthchecks heartbeat ping.

Gated by ``Effect.HEALTHCHECKS``. A Healthchecks.io check has no
environment of its own — one URL is one check — and the URL in the dev
environment is whatever was copied there. A dev process pinging the
production check holds it green while production is dead, which is the
one failure the check exists to catch, so outside production the ping is
not sent.

The gate is deliberately checked before the URL is read: in a
non-production process the production ping URL should not be reachable
even by accident.

This is what catches a watcher that has gone quiet rather than failed: a
disabled schedule, or a function that stopped being invoked, raises no
error anywhere. Healthchecks fires on absence.
"""

from __future__ import annotations

import os

import httpx
from mini_app_polis.environment import Effect, effect_enabled

from watcher_cog.logger import log


def ping() -> None:
    """Ping the healthcheck if enabled for this environment and configured."""
    if not effect_enabled(Effect.HEALTHCHECKS):
        log.debug("healthcheck ping suppressed (not production)")
        return

    url = os.getenv("HEALTHCHECKS_URL_WATCHER", "").strip()
    if not url:
        return

    # no-retry: the next tick is the retry, and a check that misses pings
    # is how Healthchecks reports an outage.
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
    except Exception as exc:
        log.error("healthcheck ping failed: %s", exc, exc_info=True)
