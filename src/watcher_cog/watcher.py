"""Core watcher loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from watcher_cog import drive_client, heartbeat, prefect_trigger
from watcher_cog.config import WatcherConfig
from watcher_cog.logger import log


async def run_watcher(config: WatcherConfig) -> None:
    """Run a single folder watcher loop forever."""
    # Track file_id -> modified_time string so we detect both new files
    # and modifications to existing files.
    seen: dict[str, str | None] = {}
    initialized = False

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
            current: dict[str, str | None] = {file.id: file.modified_time for file in files}

            if not initialized:
                seen = current
                initialized = True
                log.info("[%s] initialised with %s file(s)", config.name, len(seen))
            else:
                new_files = [fid for fid in current if fid not in seen]
                modified_files = [
                    fid for fid, mtime in current.items() if fid in seen and mtime != seen[fid]
                ]

                if new_files or modified_files:
                    await prefect_trigger.fire(config.deployment_id)
                    seen = current
                    log.info(
                        "[%s] %s new, %s modified — trigger fired",
                        config.name,
                        len(new_files),
                        len(modified_files),
                    )
                else:
                    seen = current
                    log.debug("[%s] no changes", config.name)

        except Exception as exc:
            log.error("[%s] poll error: %s", config.name, exc, exc_info=True)
        finally:
            await heartbeat.ping()

        await asyncio.sleep(current_interval * 60)
