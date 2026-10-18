"""The Lambda entry point: one tick over one watched folder.

An EventBridge rule fires once a minute with one target per folder, each
passing ``{"watcher": "<name>"}``, so every folder is checked every minute
in its own invocation. A folder that is slow or failing cannot spend the
others' time or fail their tick: each has the whole function timeout to
itself, and each failure is its own error invocation. An event that names
no folder checks all of them in turn — a hand invocation, or `main.py`.

When a check fails, the tick raises after trying everything it was given,
so the invocation is an error: that is what the function's error alarm
counts, what Sentry groups into one issue, and why the heartbeat is not
pinged.

What this replaced reported the first failure of each outage to Discord and
then stayed quiet, which needed memory across polls. A scheduled function
has none, and reporting from here would post once a minute for the length
of an outage. The alarm is the once-per-outage signal now: it notifies on
the change of state, not on every failed tick.

The heartbeat is pinged after every tick in which its folders were read and
asked for. Every folder's tick pings the one check, so it does not say
which folder is healthy — the error alarm does that. What it catches is the
failure nothing else can see: a schedule that stopped invoking this at all.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import sentry_sdk
from mini_app_polis import load_secrets
from mini_app_polis.sentry import init_sentry

from watcher_cog import api_trigger, heartbeat, watcher
from watcher_cog.config import get_watchers
from watcher_cog.logger import log

# At import, not per invocation: a Lambda container is reused across
# invocations, so this runs once per cold start. Labeled, not gated.
# An empty DSN in production logs an ERROR rather than passing silently
# (CD-038); the service tag tells this cog's events apart in the shared project.
init_sentry("watcher-cog")


class TickFailed(RuntimeError):
    """At least one folder could not be checked this tick."""


#: Seconds kept back from the function's remaining time when setting the
#: deadline for new asks: one ask's whole timeout, plus room to report.
DEADLINE_MARGIN_SECONDS = api_trigger.API_TIMEOUT_SECONDS + 5


def run_once(
    only: str | None = None, deadline: float | None = None
) -> list[watcher.Check]:
    """Check one watched folder, or every one. Raises TickFailed if any failed.

    ``only`` is a watcher name; an unknown one raises ``ValueError`` rather
    than checking nothing, so a schedule target that drifts from the config
    fails loudly instead of leaving its folder unwatched.
    """
    configs = get_watchers()
    if only is not None:
        configs = [c for c in configs if c.name == only]
        if not configs:
            known = ", ".join(c.name for c in get_watchers())
            raise ValueError(f"no watcher named {only!r} (known: {known})")

    results: list[watcher.Check] = []
    failures: list[str] = []

    for config in configs:
        try:
            results.append(watcher.check(config, deadline=deadline))
        except watcher.ApiUnreachable as exc:
            # Logged by the check; not a Sentry issue. Still fails the tick.
            failures.append(f"{config.name}: {type(exc).__name__}: {exc}")
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


def _deadline(context: Any) -> float | None:  # noqa: ANN401
    """The monotonic time after which no new ask should start, or None."""
    remaining = getattr(context, "get_remaining_time_in_millis", None)
    if remaining is None:
        return None
    return time.monotonic() + remaining() / 1000 - DEADLINE_MARGIN_SECONDS


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ANN401
    """Run one tick. The return value is only for the invocation log."""
    # Settings as Doppler holds them now, not as they were at cold start, as
    # the queue workers do: a warm container otherwise ticks on stale folder
    # ids, keys and LOGGING_LEVEL until the next deploy. One GetParameters
    # call; a failed read keeps the values already loaded, and a required
    # parameter that has gone missing fails the tick, which the alarm sees.
    load_secrets(refresh=True)
    log.setLevel(
        getattr(logging, os.getenv("LOGGING_LEVEL", "INFO").upper(), logging.INFO)
    )
    only = (event or {}).get("watcher")
    results = run_once(only=only, deadline=_deadline(context))
    return {
        "watcher": only or "all",
        "queued": sum(len(r.queued) for r in results),
        "deduplicated": sum(r.deduplicated for r in results),
        "files": sum(r.files for r in results),
    }
