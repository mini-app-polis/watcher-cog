"""The Lambda entry point: one tick over every watched folder.

An EventBridge schedule invokes this once a minute. Each tick checks every
watcher; a folder that fails does not stop the others. When any failed, the
tick raises after trying them all, so the invocation is an error: that is
what the function's error alarm counts, what Sentry groups into one issue,
and why the heartbeat is not pinged.

What this replaced reported the first failure of each outage to Discord and
then stayed quiet, which needed memory across polls. A scheduled function
has none, and reporting from here would post once a minute for the length
of an outage. The alarm is the once-per-outage signal now: it notifies on
the change of state, not on every failed tick.

The heartbeat is pinged only after a tick in which every folder was read
and asked for. Healthchecks fires on absence, so it also catches the failure
nothing else can see: a schedule that stopped invoking this at all.
"""

from __future__ import annotations

import os
from typing import Any

import sentry_sdk
from mini_app_polis.environment import current_environment

from watcher_cog import heartbeat, watcher
from watcher_cog.config import get_watchers
from watcher_cog.logger import log

# At import, not per invocation: a Lambda container is reused across
# invocations, so this runs once per cold start. Labeled, not gated.
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=current_environment().value,
)


class TickFailed(RuntimeError):
    """At least one folder could not be checked this tick."""


def run_once() -> list[watcher.Check]:
    """Check every watched folder once. Raises TickFailed if any failed."""
    results: list[watcher.Check] = []
    failures: list[str] = []

    for config in get_watchers():
        try:
            results.append(watcher.check(config))
        except Exception as exc:  # noqa: BLE001 - one folder must not stop the rest
            log.error("[%s] check failed: %s", config.name, exc, exc_info=True)
            sentry_sdk.capture_exception(exc)
            failures.append(f"{config.name}: {type(exc).__name__}: {exc}")

    if failures:
        raise TickFailed("; ".join(failures))

    # Deliberately after the check. A ping that also meant "this tick
    # raised and did nothing" would let expired credentials keep the check
    # green while every folder went unwatched.
    heartbeat.ping()
    return results


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ANN401
    """Run one tick. The return value is only for the invocation log."""
    results = run_once()
    return {
        "queued": sum(len(r.queued) for r in results),
        "deduplicated": sum(r.deduplicated for r in results),
        "files": sum(r.files for r in results),
    }
