"""Watcher configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WatcherConfig:
    """Static mapping from one Drive folder to the thing that processes it.

    The target is an API route. The API enqueues onto the owning cog's
    queue; nothing here talks to a queue or to Prefect.
    """

    name: str
    folder_id: str
    #: API route that enqueues this watcher's work, e.g. ``/v1/deejay/runs``.
    #: ``parameters`` is the request body.
    api_path: str
    #: Ask once per changed file, adding ``drive_file_id`` to the body,
    #: rather than once for the folder. For a cog whose job is one file
    #: because a sweep of the folder would not fit in one Lambda
    #: invocation — transcription-cog. A per-file watcher on a drained
    #: folder also asks for the files it finds at startup, instead of
    #: baselining them into silence: it can name them, and asking twice
    #: for a file is harmless because the cog skips one that has left its
    #: inbox.
    per_file: bool = False
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
    """The request body posted to ``api_path``.

    Pins the mode of a cog that runs several: ``dj-sets`` sends
    ``{"mode": "process-new-files"}`` to deejay-cog, ``wcs-notes`` sends
    ``{"mode": "wcs-transcripts"}`` and ``voice-notes`` sends
    ``{"mode": "voicenotes"}`` to transcription-cog. Neither cog has a
    default mode. A ``per_file`` watcher adds ``drive_file_id`` to it.
    """

    def __post_init__(self) -> None:
        if not self.api_path:
            raise ValueError(f"watcher {self.name!r} needs an api_path")

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
#: differ only by the mode they pass. This replaced the Prefect router
#: deployment `deejay-cog/deejay-cog`; the UUID is gone with it, so there
#: is no second path that could fire the same work.
_DEEJAY_RUNS_PATH = "/v1/deejay/runs"

#: transcription-cog runs on Lambda behind its own queue, one file per job:
#: a sweep of the folder does not fit in one invocation. Both wcs-notes and
#: voice-notes post here, once per changed file, and differ only by mode.
#: This replaced the Prefect router deployment
#: `notes-ingest-cog/notes-ingest-cog`; its UUID is gone with it, so there
#: is no second path that could fire the same work.
_TRANSCRIPTION_RUNS_PATH = "/v1/transcription/runs"


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
            api_path=_TRANSCRIPTION_RUNS_PATH,
            per_file=True,
            interval_min=1,
            parameters={"mode": "wcs-transcripts"},
        ),
        WatcherConfig(
            name="voice-notes",
            # Same env var the voicenotes sub-pipeline reads, so the
            # Doppler config holds one folder-ID value, not two.
            folder_id=_require("GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID"),
            api_path=_TRANSCRIPTION_RUNS_PATH,
            per_file=True,
            interval_min=1,
            # Each voice-note run ends with the retention sweep, so this one
            # mode covers ingest and routine cleanup. `voicenotes-cleanup`
            # stays reachable through the API for an operator's manual
            # sweep but is not watcher-driven.
            parameters={"mode": "voicenotes"},
        ),
    ]
