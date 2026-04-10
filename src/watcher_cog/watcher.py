"""Core watcher loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from watcher_cog import drive_client, heartbeat, prefect_trigger
from watcher_cog.config import WatcherConfig
from watcher_cog.logger import log


async def run_watcher(config: WatcherConfig) -> None:
    """Run a single folder watcher loop forever."""
    seen_file_ids: set[str] = set()
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
            all_ids = {file.id for file in files}

            if not initialized:
                seen_file_ids = all_ids
                initialized = True
                log.info("[%s] initialised with %s file(s)", config.name, len(all_ids))
            else:
                new_files = [file for file in files if file.id not in seen_file_ids]
                if new_files:
                    await prefect_trigger.fire(config.deployment_id)
                    seen_file_ids = all_ids
                    log.info(
                        "[%s] %s new file(s) - trigger fired",
                        config.name,
                        len(new_files),
                    )
                else:
                    seen_file_ids = all_ids
                    log.debug("[%s] no new files", config.name)

        except Exception as exc:
            log.error("[%s] poll error: %s", config.name, exc, exc_info=True)
        finally:
            await heartbeat.ping()

        await asyncio.sleep(current_interval * 60)
