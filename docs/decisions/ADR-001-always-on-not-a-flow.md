# ADR-001: Always-on Railway process, not a Prefect flow

Date: 2026-03-15

## Status

Accepted

## Context

watcher-cog sits between Google Drive and Prefect Cloud. Its job is to
detect a file appearing in a watched folder and fire the corresponding
Prefect deployment. Two implementation shapes were available:

- **Prefect flow on a schedule.** A `@flow`-decorated function
  registered with `prefect.serve()` and scheduled every minute. This
  matches the ecosystem pattern for all other cogs.
- **Always-on Railway process.** A plain `asyncio` loop running
  `python -m watcher_cog.main` as its Railway start command, polling
  Drive and calling the Prefect deployment API directly.

Three forces pushed against the flow shape for this specific cog:

- **Prefect Cloud Hobby tier deployment slots.** The ecosystem is
  constrained to 5 deployments. Every slot watcher-cog consumes is a
  slot a pipeline-cog cannot use. The 1-minute cadence — required for
  responsive file detection — would cost one of those five slots
  permanently.
- **"Who watches the watcher."** If the trigger mechanism is itself a
  scheduled flow on Prefect Cloud, the same Prefect Cloud infrastructure
  that runs downstream work is also responsible for kicking off the
  detection that enqueues that work. A Prefect outage takes down both
  the trigger and the triggered — no independent signal that work is
  piling up upstream.
- **Observability clarity.** A trigger-cog's operational signal is
  different from a pipeline-cog's. Pipelines produce run histories
  scorable against idempotency, retry, and data-contract rules
  (PRIN-005 and friends). A trigger only needs liveness: "did I poll
  recently." Healthchecks.io handles that in one field.

## Decision

watcher-cog runs as an always-on Railway service. Its entry point is
`src/watcher_cog/main.py`, which `asyncio.gather`s one `run_watcher()`
task per configured folder. Each task is an infinite `while True` poll
loop.

Operational signals:

- **Liveness:** Healthchecks.io ping from `heartbeat.py` at the end of
  every poll cycle (wrapped in a `finally` so pings fire even on poll
  errors).
- **Errors:** Sentry via `sentry_sdk.init()` in `main.py`.
- **Structured logs:** shared logger from common-python-utils through
  `watcher_cog/logger.py`.

This is the "three-layer observability" standard (Healthchecks + logs +
Sentry), and it is what the PRIN-005 exemption in `evaluator.yaml`
refers to.

Downstream cogs, which watcher-cog triggers, remain Prefect flows
registered with `prefect.serve()`. This ADR covers only the trigger
layer.

## Consequences

- watcher-cog does not consume a Prefect deployment slot, leaving the
  Hobby tier's budget available for pipeline-cogs.
- A Prefect Cloud outage does not mask upstream detection failures.
  Healthchecks.io will flag a silent watcher regardless of whether
  Prefect is reachable.
- The cog runs as a normal Railway service and must be restarted like
  one. Railway's `restartPolicyType = "ON_FAILURE"` plus Healthchecks
  alerting is the full story — no Prefect retry semantics apply.
- ecosystem-standards checks that apply to pipeline-cogs (Prefect
  run-history signals, flow-level retry configuration) do not apply
  here. This is reflected in `type: trigger-cog` in `evaluator.yaml`
  and in the PRIN-005 exemption.
- Dependencies stay minimal: no Prefect SDK at runtime (see ADR-002
  for the related choice on how the Prefect API is actually called).
