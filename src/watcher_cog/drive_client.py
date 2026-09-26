"""Google Drive wrapper utilities."""

from __future__ import annotations

from mini_app_polis.google import GoogleAPI
from mini_app_polis.google.types import DriveFile

_google_api: GoogleAPI | None = None


def _get_google_api() -> GoogleAPI:
    global _google_api
    if _google_api is not None:
        return _google_api

    try:
        _google_api = GoogleAPI.from_env()
    except Exception:
        _google_api = None
        raise
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
    """
    g = _get_google_api()
    return g.drive.get_files_in_folder(folder_id, include_folders=False)
