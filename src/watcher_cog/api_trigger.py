"""API trigger client.

Asks api-kaianolevine-com to start a cog's work, for cogs that have moved
off Prefect onto their own queue. The API is the fleet's only producer:
it enqueues onto the cog's queue and answers 202 with the message id.

Authenticates as ``watcher-cog`` with ``WATCHER_COG_API_KEY`` — the same
key the run reports already use — and posts to the base URL for this
environment (``KAIANO_API_BASE_URL``, or ``_DEV`` outside production).

**Gated to production, like the Prefect trigger.** A development watcher
polls the same Drive folders production does, so anything it fires is a
second trigger for production's uploads. This was first left ungated on the
reasoning that a dev watcher reaches the dev API, which enqueues onto a
``-dev-jobs`` queue. That held only while the dev API knew it was
development: on 2026-09-21 the dev API resolved itself as production and
addressed ``deejay-jobs``, and only a missing credential kept the dev
watcher from starting production runs. Whether a trigger fires is decided
here, where the folders are production's, not downstream.

A non-2xx answer raises. The watcher loop only advances its view of the
folder after a trigger returns, so raising is what makes the next cycle
try the same files again instead of losing them.
"""

from __future__ import annotations

import asyncio

from mini_app_polis.api import KaianoApiClient, KaianoApiError
from mini_app_polis.environment import Environment, current_environment

from watcher_cog.logger import log

#: The machine this cog authenticates as. Same name the run reports use.
MACHINE_NAME = "watcher-cog"


async def fire(path: str, parameters: dict[str, object] | None = None) -> str | None:
    """POST ``parameters`` to ``path`` and return the queue message id.

    Returns ``None`` without calling anything outside production, which the
    watcher loop already reports as "Would trigger" — the same contract as
    :func:`watcher_cog.prefect_trigger.fire`.

    ``KaianoApiClient`` is synchronous and does network I/O, so the call
    goes to a thread; every watcher shares this event loop.

    Raises :class:`KaianoApiError` when the API refuses the request or
    cannot be reached, and when it acknowledges without a message id — an
    acknowledgement nobody can trace is not evidence the work was queued.
    """
    if current_environment() is not Environment.PRODUCTION:
        log.info(
            "api trigger SUPPRESSED (not production) path=%s parameters=%s",
            path,
            parameters or {},
        )
        return None

    client = KaianoApiClient.from_env(machine_name=MACHINE_NAME)
    response = await asyncio.to_thread(client.post, path, parameters or {})

    data = response.get("data") if isinstance(response, dict) else None
    message_id = str((data or {}).get("message_id") or "")
    if not message_id:
        raise KaianoApiError(
            status_code=0,
            message=f"accepted without a message id: {response!r}",
            path=path,
        )

    log.info(
        "api trigger fired path=%s message_id=%s parameters=%s",
        path,
        message_id,
        parameters or {},
    )
    return message_id
