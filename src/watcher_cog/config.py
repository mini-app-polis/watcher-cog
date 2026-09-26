"""Watcher configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WatcherConfig:
    """Static mapping from one Drive folder to the thing that processes it.

    The target is an API route. The API claims each file it is told about
    and enqueues onto the owning cog's queue; nothing here talks to a queue,
    and nothing here remembers anything between ticks.
    """

    name: str
    folder_id: str
    #: API route that enqueues this watcher's work, e.g. ``/v1/deejay/runs``.
    #: ``parameters`` is the request body.
    api_path: str
    #: Ask once per file, adding ``drive_file_id`` to the body, rather than
    #: once for the folder. For a cog whose job is one file because a sweep
    #: of the folder would not fit in one Lambda invocation —
    #: transcription-cog.
    per_file: bool = False
    #: Whether downstream empties this folder. True for an inbox whose files
    #: are archived away once processed: a file being there *is* the work,
    #: and the API claims it by id. False for a folder that simply holds
    #: files and always will — live-history's sheets, modified in place and
    #: never removed — where only a new version is work, so each file is
    #: claimed by id *and* modifiedTime.
    drained_by_downstream: bool = True
    parameters: dict[str, object] = field(default_factory=dict)
    """The request body posted to ``api_path``.

    Pins the mode of a cog that runs several: ``dj-sets`` sends
    ``{"mode": "process-new-files"}`` to deejay-cog, ``wcs-notes`` sends
    ``{"mode": "wcs-transcripts"}`` and ``voice-notes`` sends
    ``{"mode": "voicenotes"}`` to transcription-cog. Neither cog has a
    default mode. A ``per_file`` watcher adds ``drive_file_id``; a sweep
    watcher adds ``drive_files``.
    """

    def __post_init__(self) -> None:
        if not self.api_path:
            raise ValueError(f"watcher {self.name!r} needs an api_path")
        if self.per_file and not self.drained_by_downstream:
            # A per-file request carries no revision, so a folder whose
            # files never leave would be one job per file, ever.
            raise ValueError(f"watcher {self.name!r}: per_file needs a drained folder")

    @property
    def target(self) -> str:
        """What this watcher triggers, as it should read in a message."""
        return f"POST {self.api_path}"


def _require(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


#: deejay-cog runs on Lambda behind its own queue, and the API is the only
#: thing that enqueues onto it. Both dj-sets and live-history post here and
#: differ only by the mode they pass.
_DEEJAY_RUNS_PATH = "/v1/deejay/runs"

#: transcription-cog runs on Lambda behind its own queue, one file per job:
#: a sweep of the folder does not fit in one invocation. Both wcs-notes and
#: voice-notes post here, once per file, and differ only by mode.
_TRANSCRIPTION_RUNS_PATH = "/v1/transcription/runs"


def get_watchers() -> list[WatcherConfig]:
    """Build watcher config from environment."""
    return [
        WatcherConfig(
            name="dj-sets",
            folder_id=_require("CSV_SOURCE_FOLDER_ID"),
            api_path=_DEEJAY_RUNS_PATH,
            parameters={"mode": "process-new-files"},
        ),
        WatcherConfig(
            name="live-history",
            folder_id="1HGxEr5ocY9JLtXcJqDRIOD95rXU6QLUW",
            api_path=_DEEJAY_RUNS_PATH,
            # This folder holds the live-history sheets themselves. They
            # are modified in place and nothing removes them, so a sheet's
            # new modifiedTime is the work, not its presence.
            drained_by_downstream=False,
            parameters={"mode": "ingest-live-history"},
        ),
        WatcherConfig(
            name="wcs-notes",
            folder_id=_require("NOTES_INPUT_FOLDER_ID"),
            api_path=_TRANSCRIPTION_RUNS_PATH,
            per_file=True,
            parameters={"mode": "wcs-transcripts"},
        ),
        WatcherConfig(
            name="voice-notes",
            # Same env var the voicenotes sub-pipeline reads, so the
            # Doppler config holds one folder-ID value, not two.
            folder_id=_require("GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID"),
            api_path=_TRANSCRIPTION_RUNS_PATH,
            per_file=True,
            # Each voice-note run ends with the retention sweep, so this one
            # mode covers ingest and routine cleanup. `voicenotes-cleanup`
            # stays reachable through the API for an operator's manual
            # sweep but is not watcher-driven.
            parameters={"mode": "voicenotes"},
        ),
    ]
