"""API trigger client.

Asks api-kaianolevine-com to start a cog's work. This is watcher's only
trigger: the API is the fleet's only producer. It claims each file it is
told about, enqueues onto the cog's queue when a claim is new, and answers
with the queue message id — the new job's, or, when every file is already
claimed, the earlier job's with ``deduplicated`` set.

Authenticates as ``watcher-cog`` with ``WATCHER_COG_API_KEY`` and posts to
the base URL for this environment (``KAIANO_API_BASE_URL``, or ``_DEV``
outside production).

**Gated to production.** A development watcher polls the same Drive
folders production does, so anything it fires is a second trigger for
production's uploads. On 2026-09-21 the dev API resolved itself as
production and addressed ``deejay-jobs``, and only a missing credential
kept the dev watcher from starting production runs. Whether a trigger
fires is decided here, where the folders are production's, not downstream.

A non-2xx answer raises. The next tick asks again anyway — nothing here
remembers — so raising is only about the failure being seen.

Requests and answers are the API's own models, from the shared contract
(``mini_app_polis.api.contract``): a body the API would refuse fails here,
before it is sent, and an answer in any other shape fails as it is read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mini_app_polis.api import KaianoApiClient, KaianoApiError
from mini_app_polis.api.contract import DeejayRunRequest, TranscriptionRunRequest
from mini_app_polis.environment import Environment, current_environment

from watcher_cog.logger import log

#: The machine this cog authenticates as. Same name the run reports use.
MACHINE_NAME = "watcher-cog"

#: The run endpoints a watcher can ask, by path: the request model the API
#: validates the body against, and the typed client method that sends it.
_RUN_ENDPOINTS: dict[str, tuple[type[Any], Callable[[KaianoApiClient, Any], Any]]] = {
    "/v1/deejay/runs": (DeejayRunRequest, KaianoApiClient.request_deejay_run),
    "/v1/transcription/runs": (
        TranscriptionRunRequest,
        KaianoApiClient.request_transcription_run,
    ),
}


@dataclass(frozen=True)
class Fired:
    """What one ask came to."""

    #: The queue message that has the work: this ask's, or an earlier one's
    #: when ``deduplicated``. Empty only when ``suppressed``.
    message_id: str = ""
    #: The API already had every file named; nothing new was enqueued.
    deduplicated: bool = False
    #: Not production, so nothing was called.
    suppressed: bool = False

    @property
    def queued(self) -> bool:
        """Whether this ask put new work on a queue."""
        return bool(self.message_id) and not self.deduplicated


def fire(path: str, parameters: dict[str, object] | None = None) -> Fired:
    """POST ``parameters`` to ``path``, one of the run endpoints.

    Raises ``ValueError`` for a path that is not a run endpoint or a body
    that is not a valid request for it — pydantic's ``ValidationError`` is
    one. Raises :class:`KaianoApiError` when the API refuses the request or
    cannot be reached, and when it acknowledges new work without a message
    id — an acknowledgement nobody can trace is not evidence the work was
    queued. A deduplicated answer may lack one, in the moment between
    another request's claim and its enqueue, and that is not a failure:
    the work is someone else's to report.
    """
    body = parameters or {}
    if current_environment() is not Environment.PRODUCTION:
        log.info("api trigger SUPPRESSED (not production) path=%s body=%s", path, body)
        return Fired(suppressed=True)

    if path not in _RUN_ENDPOINTS:
        raise ValueError(f"{path} is not a run endpoint")
    request_model, send = _RUN_ENDPOINTS[path]
    request = request_model.model_validate(body)

    client = KaianoApiClient.from_env(machine_name=MACHINE_NAME)
    accepted = send(client, request)

    message_id = accepted.message_id
    deduplicated = accepted.deduplicated
    if not message_id and not deduplicated:
        raise KaianoApiError(
            status_code=0,
            message=f"accepted without a message id: {accepted!r}",
            path=path,
        )

    if deduplicated:
        log.debug("api trigger deduplicated path=%s message_id=%s", path, message_id)
    else:
        log.info("api trigger fired path=%s message_id=%s", path, message_id)
    return Fired(message_id=message_id, deduplicated=deduplicated)
