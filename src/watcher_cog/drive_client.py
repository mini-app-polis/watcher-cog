"""Google Drive wrapper utilities."""

from __future__ import annotations

import socket

from mini_app_polis.deadline import run_deadline
from mini_app_polis.google import GoogleAPI
from mini_app_polis.google.types import DriveFile

#: Seconds one Drive request may wait on its socket. googleapiclient's
#: default is 60s, against a 50s function timeout: on 2026-11-15 a
#: ``files.list`` hung for 29s before answering 500, its retry took 6s more,
#: and the tick had passed its deadline for asks before making one. Same
#: bound as one ask to the API; the next tick, a minute later, is the retry.
DRIVE_TIMEOUT_SECONDS = 10.0

#: Seconds in which a listing may start a Drive attempt, retries and
#: backoff included. An attempt started inside it runs for at most
#: :data:`DRIVE_TIMEOUT_SECONDS`, so a listing ends within the sum — 25s —
#: and leaves the handler's ask deadline (the function's 50s less one ask
#: and room to report) time to make its asks. A Drive outage longer than
#: this fails the tick, and the next one lists again.
LIST_BUDGET_SECONDS = 15.0

_google_api: GoogleAPI | None = None


def _get_google_api() -> GoogleAPI:
    global _google_api
    if _google_api is not None:
        return _google_api

    # googleapiclient reads the process default socket timeout when it
    # builds the client's HTTP transport, and keeps it for every request
    # that client makes: set it for the build only, and put back whatever
    # was there, so no other socket in the process is affected.
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(DRIVE_TIMEOUT_SECONDS)
    try:
        _google_api = GoogleAPI.from_env()
    except Exception:
        _google_api = None
        raise
    finally:
        socket.setdefaulttimeout(previous)
    return _google_api


def list_folder(folder_id: str) -> list[DriveFile]:
    """Return the files — not the subfolders — in a Drive folder.

    ``get_files_in_folder`` defaults to ``include_folders=True`` and this
    was the only caller in the fleet not passing False. A subfolder's
    modifiedTime changes whenever anything is moved into or out of it,
    and the downstream cogs archive processed files into exactly these
    subfolders — so every completed file changed the parent listing, the
    poll below read it as a modified file, and the deployment fired
    again. One spurious run per archived file, on every watcher whose
    folder has a processed/ subfolder inside it.

    Bounded by :data:`LIST_BUDGET_SECONDS`: the library's retry loop starts
    no attempt and sleeps no backoff past it, and raises
    ``RunDeadlineReached`` (a ``TimeoutError``) instead.
    """
    g = _get_google_api()
    with run_deadline(LIST_BUDGET_SECONDS):
        return g.drive.get_files_in_folder(folder_id, include_folders=False)
