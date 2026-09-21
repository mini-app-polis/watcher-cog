"""API trigger client.

Asks api-kaianolevine-com to start a cog's work, for cogs that have moved
off Prefect onto their own queue. The API is the fleet's only producer:
it enqueues onto the cog's queue and answers 202 with the message id.

Authenticates as ``watcher-cog`` with ``WATCHER_COG_API_KEY`` — the same
key the run reports already use — and posts to the base URL for this
environment (``KAIANO_API_BASE_URL``, or ``_DEV`` outside production).

**Not gated by environment, unlike the Prefect trigger.** That gate exists
because Prefect Cloud has one workspace and the deployment ids are
production's, so a dev watcher could only ever fire production work. The
API has an environment split: a dev watcher reaches the dev API, and what
that enqueues onto is the dev API's own configuration. Gating it here as
well would make a dev end-to-end test impossible without an override.

A non-2xx answer raises. The watcher loop only advances its view of the
folder after a trigger returns, so raising is what makes the next cycle
try the same files again instead of losing them.
"""

from __future__ import annotations

import asyncio

from mini_app_polis.api import KaianoApiClient, KaianoApiError

from watcher_cog.logger import log

#: The machine this cog authenticates as. Same name the run reports use.
MACHINE_NAME = "watcher-cog"


async def fire(path: str, parameters: dict[str, object] | None = None) -> str:
    """POST ``parameters`` to ``path`` and return the queue message id.

    ``KaianoApiClient`` is synchronous and does network I/O, so the call
    goes to a thread; every watcher shares this event loop.

    Raises :class:`KaianoApiError` when the API refuses the request or
    cannot be reached, and when it acknowledges without a message id — an
    acknowledgement nobody can trace is not evidence the work was queued.
    """
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
