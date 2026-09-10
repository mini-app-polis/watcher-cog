"""Healthchecks heartbeat ping.

Gated by ``Effect.HEALTHCHECKS``. A Healthchecks.io check has no
environment of its own — one URL is one check — and the URL in the dev
environment is whatever was copied there. A dev container pinging the
production check holds it green while production is dead, which is the
one failure the check exists to catch, so outside production the ping is
not sent.

The gate is deliberately checked before the URL is read: in a
non-production process the production ping URL should not be reachable
even by accident.
"""

from __future__ import annotations

import os

import httpx
from mini_app_polis.environment import Effect, effect_enabled

from watcher_cog.logger import log


async def ping() -> None:
    """Ping healthchecks endpoint if enabled for this environment and configured."""
    if not effect_enabled(Effect.HEALTHCHECKS):
        log.debug("healthcheck ping suppressed (not production)")
        return

    url = os.getenv("HEALTHCHECKS_URL_WATCHER", "").strip()
    if not url:
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception as exc:
        log.error("healthcheck ping failed: %s", exc, exc_info=True)
