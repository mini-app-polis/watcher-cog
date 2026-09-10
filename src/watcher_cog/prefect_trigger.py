"""Prefect trigger client.

Uses the Prefect Python client (`prefect.get_client()`) to create flow
runs from deployments. Reads `PREFECT_API_KEY` and `PREFECT_API_URL`
from the environment — both are consumed automatically by the SDK and
must be set at process startup.

The SDK's default retry behavior handles transient API errors. No
application-level retry wrapper is needed; see ADR-002 for the history
of why this cog previously used raw httpx + tenacity.

Fires are gated by ``Effect.PREFECT_TRIGGER``. Prefect Cloud has one
workspace across both Railway environments, and the deployment IDs in
:mod:`watcher_cog.config` are production UUIDs — there is no dev
deployment for a dev watcher to fire, only the production one. Outside
production this module therefore logs the fire it would have made and
returns ``None``. If a dev Prefect workspace ever exists, this becomes a
routing decision rather than a suppression and the gate can go.
"""

from __future__ import annotations

from mini_app_polis.environment import Effect, effect_enabled
from prefect import get_client

from watcher_cog.logger import log


async def fire(
    deployment_id: str,
    parameters: dict[str, object] | None = None,
) -> str | None:
    """Trigger a Prefect deployment run.

    Creates a flow run for the given deployment and returns immediately
    — the run is enqueued in Prefect Cloud and executed by the target
    cog's serve() loop. This function does not wait for the run to
    complete.

    ``parameters``, if given, is forwarded to the deployment as
    flow-run parameters. Used by router-style deployments to override
    a cron-default mode (e.g. ``{"mode": "ingest"}`` on the
    voicenotes-cog router).

    Returns the new flow run's id, or ``None`` when the trigger was
    suppressed because this process is not in production. The return
    value is the only thing that distinguishes the two, so a caller that
    reports on the outcome must read it rather than assume — describing a
    suppressed fire as a trigger would put a claim in the dev logs and in
    the dev findings that no pipeline ever heard about.
    """
    if not effect_enabled(Effect.PREFECT_TRIGGER):
        log.info(
            "prefect trigger SUPPRESSED (not production) "
            "deployment_id=%s parameters=%s",
            deployment_id,
            parameters or {},
        )
        return None

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
        return str(flow_run.id)
