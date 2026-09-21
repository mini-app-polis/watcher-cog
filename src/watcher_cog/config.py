"""Watcher configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WatcherConfig:
    """Static mapping from one Drive folder to the thing that processes it.

    Exactly one target: ``api_path`` for a cog that has moved to its own
    queue — the API enqueues onto it — or ``deployment_id`` for a cog still
    served by Prefect. Both is two triggers for one change; neither is a
    watcher that detects work and starts nothing.
    """

    name: str
    folder_id: str
    deployment_id: str | None = None
    #: API route that enqueues this watcher's work, e.g. ``/v1/deejay/runs``.
    #: ``parameters`` is the request body.
    api_path: str | None = None
    interval_min: int = 1
    idle_interval_min: int = 1
    activity_signal: str = "none"
    activity_file_id: str | None = None
    activity_threshold_min: int = 10
    #: Whether downstream empties this folder. True for an input folder
    #: whose files are archived away once processed — anything sitting in
    #: it at startup is pending work that the baseline will swallow, so
    #: it is worth saying so. False for a folder that simply holds files
    #: and always will: live-history watches a folder of nineteen sheets
    #: that are modified in place and never removed, where "there are
    #: files here at startup" is the steady state and a warning about it
    #: is only training you to ignore warnings.
    #:
    #: Defaults True because every watcher but one is a drained inbox,
    #: and a new watcher that is wrong in this direction is merely noisy
    #: rather than silent.
    drained_by_downstream: bool = True
    #: For a folder that is *not* drained, "non-empty" says nothing. What
    #: does say something is a file modified shortly before this process
    #: started — plausibly during the downtime, and therefore plausibly a
    #: change that will never fire. Minutes.
    baseline_recent_change_min: int = 15
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

    For an ``api_path`` target this is the request body unchanged, which
    is why the API's schema is the same ``{"mode": ...}``.
    """

    def __post_init__(self) -> None:
        if bool(self.deployment_id) == bool(self.api_path):
            raise ValueError(
                f"watcher {self.name!r} needs exactly one of deployment_id or api_path"
            )

    @property
    def target(self) -> str:
        """What this watcher triggers, as it should read in a message."""
        if self.api_path:
            return f"POST {self.api_path}"
        return f"deployment {self.deployment_id}"


def _require(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


#: deejay-cog runs on Lambda behind its own queue, and the API is the only
#: thing that enqueues onto it. Both dj-sets and live-history post here and
#: differ only by the mode they pass. This replaced the Prefect router
#: deployment `deejay-cog/deejay-cog`; the UUID is gone with it, so there
#: is no second path that could fire the same work.
_DEEJAY_RUNS_PATH = "/v1/deejay/runs"

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
            api_path=_DEEJAY_RUNS_PATH,
            interval_min=1,
            parameters={"mode": "process-new-files"},
        ),
        WatcherConfig(
            name="live-history",
            folder_id="1HGxEr5ocY9JLtXcJqDRIOD95rXU6QLUW",
            api_path=_DEEJAY_RUNS_PATH,
            interval_min=1,
            # This folder holds the live-history sheets themselves. They
            # are modified in place and nothing removes them, so it is
            # never empty and a plain "N files present" baseline warning
            # would fire on every single restart forever.
            drained_by_downstream=False,
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
