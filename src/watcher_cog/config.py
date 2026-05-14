"""Watcher configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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
    parameters: dict[str, object] = field(default_factory=dict)
    """Optional flow-run parameters merged into the deployment trigger.

    Watchers that target a router-style deployment (one that
    dispatches multiple modes via a ``mode`` parameter) use this to
    pin the dispatch mode for trigger fires. Example: voicenotes-cog
    uses ``parameters={"mode": "ingest"}`` so the watcher trigger
    doesn't fall into the deployment's cron-default mode.
    """


def _require(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


#: deejay-cog now serves a single router deployment
#: (`deejay-cog/deejay-cog`) that dispatches via a `mode` parameter.
#: Both dj-sets and live-history watchers point at the same deployment
#: UUID and differ only by the mode they pass in.
_DEEJAY_ROUTER_DEPLOYMENT_ID = "f717735e-5a04-4aeb-ab98-cf60e8d1be0f"


def get_watchers() -> list[WatcherConfig]:
    """Build watcher config from environment. Call after load_dotenv()."""
    return [
        WatcherConfig(
            name="dj-sets",
            folder_id=_require("CSV_SOURCE_FOLDER_ID"),
            deployment_id=_DEEJAY_ROUTER_DEPLOYMENT_ID,
            interval_min=1,
            parameters={"mode": "process-new-files"},
        ),
        WatcherConfig(
            name="live-history",
            folder_id="1HGxEr5ocY9JLtXcJqDRIOD95rXU6QLUW",
            deployment_id=_DEEJAY_ROUTER_DEPLOYMENT_ID,
            interval_min=1,
            parameters={"mode": "ingest-live-history"},
        ),
        WatcherConfig(
            name="wcs-notes",
            folder_id=_require("NOTES_INPUT_FOLDER_ID"),
            deployment_id="c3a48fd5-261b-4011-b468-db94347c7ae6",
            interval_min=1,
        ),
        WatcherConfig(
            name="voice-notes",
            # Same env var voicenotes-cog reads, so the Doppler
            # config holds one folder-ID value, not two.
            folder_id=_require("GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID"),
            # voicenotes-cog's single deployment is the router flow
            # (voicenotes-router/voicenotes).
            deployment_id="020a34b4-2b22-42f4-841b-8634211d113b",
            interval_min=1,
            # Required: the deployment's cron-default mode is
            # "cleanup". The watcher fires it as ingest.
            parameters={"mode": "ingest"},
        ),
    ]


# generate-summaries and update-dj-set-collection are triggered
# manually or via Prefect schedules, not by Drive file drops
# Add them here if you want Drive-triggered runs for those too
# Deployment 'update-dj-set-collection/update-deejay-set-collection'
# id 'cad08633-d2c8-4873-b2ab-d34714b042e9'.
# Deployment 'generate-summaries/generate-summaries'
# id 'b532f160-1731-43c9-a1f6-9c7eca474a92'.
