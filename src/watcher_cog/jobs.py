"""Scheduled jobs: asks the API makes on a schedule, with no folder to watch.

A watcher asks for work because files are in its folder. A job asks
because it is time: its own EventBridge schedule (declared in
mini-app-polis/infra) invokes this function with ``{"job": "<name>"}`` and
the job is asked for once, unconditionally, as an operator's run would be.

A ``run`` job asks for a cog's run, which the API puts on that cog's queue;
what the run does, and whether it writes anything, is the receiving cog's to
decide. A ``check`` job asks the API to do a piece of work itself, and the
API answers what it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mini_app_polis import logger as logger_mod

from watcher_cog import api_trigger

log = logger_mod.get_logger()


@dataclass(frozen=True)
class Job:
    """One scheduled ask: the API route and the body it is sent."""

    name: str
    api_path: str
    parameters: dict[str, object] = field(default_factory=dict)
    #: ``run`` enqueues a cog's run; ``check`` is done by the API itself.
    kind: Literal["run", "check"] = "run"


#: Every job a schedule may name.
JOBS: dict[str, Job] = {
    # deejay-cog's library backfill: retags the next chunk of the music
    # library each night. Whether it writes anything is deejay-cog's own
    # setting (LIBRARY_BACKFILL_MODE, off unless set).
    "library-backfill": Job(
        name="library-backfill",
        api_path="/v1/deejay/runs",
        parameters={"mode": "library-backfill"},
    ),
    # deejay-cog's library reconcile, on its own schedule rather than as a
    # step of the backfill's run, so it has a whole run's time to write in.
    # Whether it reads or writes is deejay-cog's setting
    # (LIBRARY_RECONCILE_MODE, off unless set).
    "library-reconcile": Job(
        name="library-reconcile",
        api_path="/v1/deejay/runs",
        parameters={"mode": "library-reconcile"},
    ),
    # The API's quiet sweep of its own faults: a 502, 503 or 504 Issue whose
    # route has gone SIGNAL_FAULT_QUIET_HOURS (the API's setting) without
    # the fault is commented and closed. A 500's Issue is never closed here.
    "api-fault-quiet-sweep": Job(
        name="api-fault-quiet-sweep",
        api_path="/v1/signals/api-faults/quiet-sweep",
        kind="check",
    ),
}


def run_job(name: str) -> dict[str, object]:
    """Ask for one job and return what it came to, for the invocation log.

    A run job returns its queue message id (``message_id``); a check job
    returns the API's answer (``result``). An unknown name raises
    ``ValueError``, so a schedule that drifts from this table fails loudly
    instead of asking for nothing. A failed ask raises, so the invocation is
    an error the function's alarm counts.
    """
    job = JOBS.get(name)
    if job is None:
        known = ", ".join(sorted(JOBS))
        raise ValueError(f"no job named {name!r} (known: {known})")
    if job.kind == "check":
        result = api_trigger.check(job.api_path, parameters=dict(job.parameters))
        log.info("[%s] checked: %s", name, result or "-")
        return {"result": result}
    fired = api_trigger.fire(job.api_path, parameters=dict(job.parameters))
    log.info(
        "[%s] asked: message %s%s",
        name,
        fired.message_id or "-",
        " (deduplicated)" if fired.deduplicated else "",
    )
    return {"message_id": fired.message_id}
