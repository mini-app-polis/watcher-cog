"""Healthchecks heartbeat ping."""

from __future__ import annotations

import os

import httpx

from watcher_cog.logger import log


async def ping() -> None:
    """Ping healthchecks endpoint if configured."""
    url = os.getenv("HEALTHCHECKS_URL_WATCHER", "").strip()
    if not url:
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception as exc:
        log.error("healthcheck ping failed: %s", exc, exc_info=True)
