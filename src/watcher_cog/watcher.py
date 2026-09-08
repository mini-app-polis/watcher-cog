"""Core watcher loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from mini_app_polis.pipeline_status import post_run_finding

from watcher_cog import drive_client, heartbeat, prefect_trigger
from watcher_cog.config import WatcherConfig
from watcher_cog.logger import log

#: Reported as the machine name, so the API attributes these to this cog
#: and looks for WATCHER_COG_API_KEY.
REPO = "watcher-cog"

#: Marks these as coming from the watcher loop rather than a flow run.
#: This cog has no Prefect flow of its own — it is a plain asyncio loop —
#: so neither "flow_inline" nor "flow_hook" would be true.
SOURCE = "watcher_loop"


async def _report(
    config: WatcherConfig,
    severity: str,
    text: str,
    *,
    notable: bool = False,
) -> None:
    """Report one watcher event. Never raises, never blocks the loop.

    ``post_run_finding`` is synchronous and does network I/O. Called
    directly it would stall every other watcher sharing this event loop
    for the duration of the request, so it goes to a thread — a watcher
    that polls every minute cannot afford to spend ten seconds of that
    inside a notification.
    """
    try:
        await asyncio.to_thread(
            post_run_finding,
            config.name,
            severity,  # type: ignore[arg-type]
            text,
            repo=REPO,
            source=SOURCE,
            notable=notable,
        )
    except Exception as exc:  # noqa: BLE001 - reporting must never break polling
        log.error("[%s] report failed: %s", config.name, exc)


async def run_watcher(config: WatcherConfig) -> None:
    """Run a single folder watcher loop forever."""
    # Track file_id -> modified_time string so we detect both new files
    # and modifications to existing files.
    seen: dict[str, str | None] = {}
    initialized = False
    # Length of the current run of consecutive poll failures. Used to
    # report the first failure and the recovery, and nothing in between:
    # a Drive outage on a one-minute poll would otherwise post sixty
    # identical messages an hour, which is how a channel gets muted right
    # before it matters.
    error_streak = 0

    while True:
        current_interval = config.interval_min
        try:
            if config.activity_signal == "file_mod_time" and config.activity_file_id:
                mod_time = drive_client.get_file_modified_time(config.activity_file_id)
                if mod_time is not None:
                    age_min = (datetime.now(UTC) - mod_time).total_seconds() / 60
                    if age_min > config.activity_threshold_min:
                        current_interval = config.idle_interval_min

            files = drive_client.list_folder(config.folder_id)
            current: dict[str, str | None] = {
                file.id: file.modified_time for file in files
            }

            if not initialized:
                seen = current
                initialized = True
                log.info("[%s] initialised with %s file(s)", config.name, len(seen))
            else:
                new_files = [fid for fid in current if fid not in seen]
                modified_files = [
                    fid
                    for fid, mtime in current.items()
                    if fid in seen and mtime != seen[fid]
                ]

                if new_files or modified_files:
                    await prefect_trigger.fire(
                        config.deployment_id,
                        parameters=config.parameters,
                    )
                    seen = current
                    log.info(
                        "[%s] %s new, %s modified — trigger fired",
                        config.name,
                        len(new_files),
                        len(modified_files),
                    )
                    # The event worth hearing about. A poll that changes
                    # nothing is the steady state and stays silent; a
                    # poll that fires a downstream deployment is the
                    # moment work entered the pipeline, and it is the
                    # only record of that moment outside Prefect.
                    await _report(
                        config,
                        "SUCCESS",
                        (
                            f"Triggered {config.deployment_id}: "
                            f"{len(new_files)} new, "
                            f"{len(modified_files)} modified"
                        ),
                        notable=True,
                    )
                else:
                    seen = current
                    log.debug("[%s] no changes", config.name)

            if error_streak:
                recovered_after = error_streak
                error_streak = 0
                await _report(
                    config,
                    "SUCCESS",
                    f"Polling recovered after {recovered_after} failed cycle(s)",
                    notable=True,
                )

        except Exception as exc:
            log.error("[%s] poll error: %s", config.name, exc, exc_info=True)
            error_streak += 1
            if error_streak == 1:
                await _report(
                    config,
                    "ERROR",
                    (
                        f"Poll failed for folder {config.folder_id}: "
                        f"{type(exc).__name__}: {exc}. "
                        "Further failures are logged but not repeated here "
                        "until it recovers."
                    ),
                )
        finally:
            await heartbeat.ping()

        await asyncio.sleep(current_interval * 60)
