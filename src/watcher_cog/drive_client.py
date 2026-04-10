"""Google Drive wrapper utilities."""

from __future__ import annotations

from datetime import datetime

from watcher_cog.logger import log

try:
    from mini_app_polis.google import GoogleAPI
    from mini_app_polis.google.types import DriveFile
except ImportError:  # pragma: no cover
    GoogleAPI = None  # type: ignore[assignment]
    DriveFile = object  # type: ignore[assignment,misc]


_google_api: GoogleAPI | None = None


def _parse_modified_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_google_api() -> GoogleAPI:
    global _google_api
    if _google_api is not None:
        return _google_api

    if GoogleAPI is None:
        raise RuntimeError("common-python-utils is required to use drive_client")

    try:
        _google_api = GoogleAPI.from_env()
    except Exception:
        _google_api = None
        raise
    return _google_api


def list_folder(folder_id: str) -> list[DriveFile]:
    """Return all files in a Drive folder."""
    g = _get_google_api()
    return g.drive.get_files_in_folder(folder_id)


def get_file_modified_time(file_id: str) -> datetime | None:
    """Return the modified time of a specific file, or None if not found."""
    g = _get_google_api()
    try:
        result = g.drive.service.files().get(fileId=file_id, fields="modifiedTime").execute()
    except Exception as exc:
        log.debug("failed to fetch modified time for %s: %s", file_id, exc)
        return None

    modified_time = result.get("modifiedTime")
    if not modified_time:
        return None

    return _parse_modified_time(modified_time)
