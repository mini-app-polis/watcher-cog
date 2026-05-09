"""Prefect trigger client.

Uses the Prefect Python client (`prefect.get_client()`) to create flow
runs from deployments. Reads `PREFECT_API_KEY` and `PREFECT_API_URL`
from the environment — both are consumed automatically by the SDK and
must be set at process startup.

The SDK's default retry behavior handles transient API errors. No
application-level retry wrapper is needed; see ADR-002 for the history
of why this cog previously used raw httpx + tenacity.
"""

from __future__ import annotations

from prefect import get_client

from watcher_cog.logger import log


async def fire(
    deployment_id: str,
    parameters: dict[str, object] | None = None,
) -> None:
    """Trigger a Prefect deployment run.

    Creates a flow run for the given deployment and returns immediately
    — the run is enqueued in Prefect Cloud and executed by the target
    cog's serve() loop. This function does not wait for the run to
    complete.

    ``parameters``, if given, is forwarded to the deployment as
    flow-run parameters. Used by router-style deployments to override
    a cron-default mode (e.g. ``{"mode": "ingest"}`` on the
    voicenotes-cog router).
    """
    async with get_client() as client:
        flow_run = await client.create_flow_run_from_deployment(
            deployment_id=deployment_id,
            parameters=parameters or {},
        )
        log.info(
            "prefect trigger fired deployment_id=%s flow_run_id=%s parameters=%s",
            deployment_id,
            flow_run.id,
            parameters or {},
        )
