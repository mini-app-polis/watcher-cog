# ADR-002: Raw httpx for Prefect deployment API

Date: 2026-03-15

## Status

Accepted. Revisit when next touching this repo — see `docs/BACKLOG.md`.

## Context

To fire a Prefect deployment, `watcher_cog/prefect_trigger.py::fire()`
needs to call Prefect Cloud's orchestration API. Two options:

- **`prefect.client.orchestration.PrefectClient`.** The SDK's typed
  client. Handles auth header construction, schema evolution, and
  returns structured responses. Call:
  `await client.create_flow_run_from_deployment(deployment_id)`.
- **Raw `httpx.AsyncClient` POST to `/deployments/{id}/create_flow_run`.**
  Hand-built bearer-token header, JSON body, direct HTTP.

The Prefect SDK route is cleaner code and would resolve ecosystem rule
PIPE-001 (which expects trigger cogs to reference `run_deployment` or
equivalent Prefect Python client APIs). But pulling `prefect` into
watcher-cog's runtime dependency tree has non-trivial cost — the SDK
brings its own transitive graph, and watcher-cog's whole reason for
being a trigger-cog rather than a flow (see ADR-001) is to stay
minimal and independent of Prefect's surface area.

The raw-httpx path is a small, well-bounded footprint: one endpoint,
one header, one retry policy via `tenacity` (3 attempts, exponential
backoff 2-10 seconds).

## Decision

Use raw `httpx.AsyncClient` for the Prefect deployment trigger. Wrap
the call in `tenacity.retry` for transient error resilience. Keep the
deployment API endpoint, auth header, and request body hand-built in
`prefect_trigger.py`.

This decision is explicitly revisitable. `docs/BACKLOG.md` documents
the migration path to `PrefectClient.create_flow_run_from_deployment()`
and will be actioned when next convenient. The PIPE-001 finding stays
open as an INFO-level indicator that this backlog item exists.

## Consequences

- watcher-cog's runtime dependencies stay small — no Prefect SDK.
- If Prefect changes its orchestration API shape or auth scheme,
  this cog breaks in a predictable way (the POST fails) rather than
  inheriting SDK compatibility issues.
- Trigger events appear in Prefect Cloud as generic API calls, not as
  SDK-initiated client events. This has some observability cost but
  no functional impact.
- PIPE-001 stays flagged until the BACKLOG migration lands. The
  finding is accurate — the rule wants `run_deployment` and this cog
  does not use it. The finding is not a bug to suppress; it is the
  rule correctly surfacing the trade-off made here. When the migration
  ships, this ADR transitions to "Superseded."
- The hand-rolled bearer-token auth in `prefect_trigger.py` is a
  second thing to maintain. Tenacity retry logic is the other. Both
  would go away with PrefectClient.
