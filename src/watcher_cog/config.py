"""Watcher configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WatcherConfig:
    """Static mapping from one Drive folder to one Prefect deployment."""

    name: str
    folder_id: str
    deployment_id: str
    interval_min: int = 1
    idle_interval_min: int = 1
    activity_signal: str = "none"
    activity_file_id: str | None = None
    activity_threshold_min: int = 10


WATCHERS: list[WatcherConfig] = [
    WatcherConfig(
        name="dj-sets",
        folder_id="1t4d_8lMC3ZJfSyainbpwInoDta7n69hC",
        deployment_id="7334f113-3efc-43ec-8ada-2431b1ff1583",
        interval_min=1,
    ),
    WatcherConfig(
        name="live-history",
        folder_id="1HGxEr5ocY9JLtXcJqDRIOD95rXU6QLUW",
        deployment_id="ae8a1dcd-42cc-4cae-8c54-b67895e64cca",
        interval_min=1,
    ),
    # generate-summaries and update-dj-set-collection are triggered
    # manually or via Prefect schedules, not by Drive file drops
    # Add them here if you want Drive-triggered runs for those too
    # Deployment 'update-dj-set-collection/update-deejay-set-collection'
    # id 'cad08633-d2c8-4873-b2ab-d34714b042e9'.
    # Deployment 'generate-summaries/generate-summaries'
    # id 'b532f160-1731-43c9-a1f6-9c7eca474a92'.
]
