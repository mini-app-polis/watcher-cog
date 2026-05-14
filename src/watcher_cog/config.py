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
    pin the dispatch mode for trigger fires. Examples: ``dj-sets``
    pins ``{"mode": "process-new-files"}`` against deejay-cog's
    router; ``wcs-notes`` pins ``{"mode": "wcs-transcripts"}`` and
    ``voice-notes`` pins ``{"mode": "voicenotes"}`` against
    transcription-cog's router. The transcription-cog router has no
    cron-default mode — every trigger must specify one.
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

#: transcription-cog (originally notes-ingest-cog — renamed May 2026, see
#: ADR-004) now serves a single router deployment that hosts both the
#: WCS-transcripts pipeline AND the voicenotes pipeline (which was
#: merged in from the legacy `voicenotes-cog` repo at the same time).
#: The Prefect deployment name was kept as `notes-ingest-cog/notes-ingest-cog`
#: through the rename to avoid an unnecessary deployment-UUID rotation
#: and a second watcher reconfiguration — only the local repo + Python
#: package were renamed. The deployment-name string is therefore a
#: historical artifact, not a live identifier of the repo.
#: Both `wcs-notes` and `voice-notes` watchers point at this same
#: deployment UUID and differ only by the `mode` parameter they pass in.
#: Replaces the legacy `process-transcript/notes-ingest-cog` deployment
#: (`c3a48fd5-…`) and the standalone `voicenotes-router/voicenotes`
#: deployment (`020a34b4-…`).
_TRANSCRIPTION_ROUTER_DEPLOYMENT_ID = "a0bd7094-e90c-43d3-aed9-8e1fd7923687"


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
            deployment_id=_TRANSCRIPTION_ROUTER_DEPLOYMENT_ID,
            interval_min=1,
            # Required: the transcription-cog router has no
            # default mode — every trigger must specify which
            # sub-pipeline to run, and the router raises ValueError
            # otherwise.
            parameters={"mode": "wcs-transcripts"},
        ),
        WatcherConfig(
            name="voice-notes",
            # Same env var the voicenotes sub-pipeline reads, so the
            # Doppler config holds one folder-ID value, not two.
            folder_id=_require("GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID"),
            deployment_id=_TRANSCRIPTION_ROUTER_DEPLOYMENT_ID,
            interval_min=1,
            # The voicenotes ingest flow runs cleanup inline at the
            # end of every cycle, so this single mode covers both
            # ingest and routine retention sweeping. The separate
            # `voicenotes-cleanup` mode is reachable from the Prefect
            # UI for manual operator sweeps but is not watcher-driven.
            parameters={"mode": "voicenotes"},
        ),
    ]


# generate-summaries and update-dj-set-collection are triggered
# manually or via Prefect schedules, not by Drive file drops
# Add them here if you want Drive-triggered runs for those too
# Deployment 'update-dj-set-collection/update-deejay-set-collection'
# id 'cad08633-d2c8-4873-b2ab-d34714b042e9'.
# Deployment 'generate-summaries/generate-summaries'
# id 'b532f160-1731-43c9-a1f6-9c7eca474a92'.
