"""One look at one folder: list it, and ask for what is there.

Stateless by design. The Railway loop this replaced remembered what it had
seen, and every restart had to decide whether a folder's contents were a
backlog or a baseline — from inside the process the two were identical.
Now nothing is remembered here: every tick asks for every file present,
and the API's dispatch claims turn the repeats into one job per file (or
one per version, for a folder whose files never leave). A missed tick is
caught by the next one, and a restart is not an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mini_app_polis.google.types import DriveFile
from mini_app_polis.pipeline_status import post_run_finding

from watcher_cog import api_trigger, drive_client
from watcher_cog.config import WatcherConfig
from watcher_cog.logger import log

#: Reported as the machine name, so the API attributes these to this cog.
REPO = "watcher-cog"

#: Marks these as coming from the watcher rather than a flow run.
SOURCE = "watcher_loop"

#: The API's ceiling on ``drive_files`` in one request.
MAX_FILES_PER_REQUEST = 500


@dataclass
class Check:
    """What one look at one folder came to."""

    watcher: str
    files: int = 0
    #: Message ids of work this check put on a queue.
    queued: list[str] = field(default_factory=list)
    #: Asks the API already had.
    deduplicated: int = 0
    #: Asks not sent because this is not production.
    suppressed: int = 0


class CheckFailed(Exception):
    """At least one ask for this folder failed; the rest were still made."""


def _file_ref(config: WatcherConfig, file: DriveFile) -> dict[str, str]:
    if config.drained_by_downstream:
        return {"id": file.id}
    # Only a new version of an in-place file is work, and the version is
    # the claim. Without one the API would claim the file by presence and
    # re-run it every window, so refuse rather than send that.
    if not file.modified_time:
        raise CheckFailed(f"{config.name}: file {file.id} has no modifiedTime")
    return {"id": file.id, "revision": str(file.modified_time)}


def requests_for(
    config: WatcherConfig, files: list[DriveFile]
) -> list[dict[str, object]]:
    """The request bodies one look at this folder produces."""
    if not files:
        return []
    if config.per_file:
        return [{**config.parameters, "drive_file_id": f.id} for f in files]
    refs = [_file_ref(config, f) for f in files]
    return [
        {**config.parameters, "drive_files": refs[i : i + MAX_FILES_PER_REQUEST]}
        for i in range(0, len(refs), MAX_FILES_PER_REQUEST)
    ]


def check(config: WatcherConfig) -> Check:
    """List the folder and ask for what is in it.

    A failed ask does not stop the others: one file the API refuses must
    not hold back the rest of the folder. Raises :class:`CheckFailed` after
    trying everything, so the tick is still marked as failed.
    """
    files = drive_client.list_folder(config.folder_id)
    result = Check(watcher=config.name, files=len(files))
    errors: list[str] = []

    for body in requests_for(config, files):
        try:
            fired = api_trigger.fire(config.api_path, parameters=body)
        except Exception as exc:  # noqa: BLE001 - reported below, after the rest
            log.error("[%s] trigger failed: %s", config.name, exc, exc_info=True)
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if fired.suppressed:
            result.suppressed += 1
        elif fired.deduplicated:
            result.deduplicated += 1
        else:
            result.queued.append(fired.message_id)

    if result.queued:
        _report_queued(config, result)
    log.info(
        "[%s] %s file(s): %s queued, %s already claimed%s",
        config.name,
        result.files,
        len(result.queued),
        result.deduplicated,
        f", {result.suppressed} suppressed (not production)"
        if result.suppressed
        else "",
    )
    if errors:
        raise CheckFailed(f"{config.name}: {len(errors)} ask(s) failed: {errors[0]}")
    return result


def _report_queued(config: WatcherConfig, result: Check) -> None:
    """Say that work entered the pipeline. Never raises.

    The one event worth hearing about. A tick that finds nothing, or finds
    only files already claimed, is the steady state and stays silent — at
    one tick a minute, anything else would bury the runs channel.

    ``run_id`` is the queue message when there is exactly one, so this line
    and the run it started carry the same id; several are named in the text.
    """
    queued = result.queued
    names = f" — messages {', '.join(queued)}" if len(queued) > 1 else ""
    try:
        post_run_finding(
            config.name,
            "SUCCESS",
            f"Triggered {config.target} ({len(queued)} job(s), "
            f"{result.files} file(s) in folder){names}",
            repo=REPO,
            source=SOURCE,
            notable=True,
            run_id=queued[0] if len(queued) == 1 else None,
        )
    except Exception as exc:  # noqa: BLE001 - reporting must never fail a tick
        log.error("[%s] report failed: %s", config.name, exc)
