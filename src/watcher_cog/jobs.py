"""Scheduled jobs: asks the API makes on a schedule, with no folder to watch.

A watcher asks for work because files are in its folder. A job asks
because it is time: its own EventBridge schedule (declared in
mini-app-polis/infra) invokes this function with ``{"job": "<name>"}`` and
the job is asked for once, unconditionally, as an operator's run would be.
What the job then does, and whether it writes anything, is the receiving
cog's to decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mini_app_polis import logger as logger_mod

from watcher_cog import api_trigger

log = logger_mod.get_logger()


@dataclass(frozen=True)
class Job:
    """One scheduled ask: the API route and the body it is sent."""

    name: str
    api_path: str
    parameters: dict[str, object] = field(default_factory=dict)


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
}


def run_job(name: str) -> str:
    """Ask for one job and return the queue message id.

    An unknown name raises ``ValueError``, so a schedule that drifts from
    this table fails loudly instead of asking for nothing. A failed ask
    raises, so the invocation is an error the function's alarm counts.
    """
    job = JOBS.get(name)
    if job is None:
        known = ", ".join(sorted(JOBS))
        raise ValueError(f"no job named {name!r} (known: {known})")
    fired = api_trigger.fire(job.api_path, parameters=dict(job.parameters))
    log.info(
        "[%s] asked: message %s%s",
        name,
        fired.message_id or "-",
        " (deduplicated)" if fired.deduplicated else "",
    )
    return fired.message_id
