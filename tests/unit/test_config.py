from __future__ import annotations

import pytest

from watcher_cog.config import WatcherConfig, get_watchers

FOLDERS = {
    "CSV_SOURCE_FOLDER_ID": "csv-folder",
    "LIVE_HISTORY_FOLDER_ID": "live-history-folder",
    "NOTES_INPUT_FOLDER_ID": "notes-folder",
    "GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID": "voice-folder",
}


@pytest.fixture
def folders(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in FOLDERS.items():
        monkeypatch.setenv(name, value)


def test_every_watched_folder_comes_from_configuration(folders: None) -> None:
    by_name = {w.name: w.folder_id for w in get_watchers()}
    assert by_name == {
        "dj-sets": "csv-folder",
        "live-history": "live-history-folder",
        "wcs-notes": "notes-folder",
        "voice-notes": "voice-folder",
    }


def test_a_missing_live_history_folder_fails_at_startup(
    folders: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LIVE_HISTORY_FOLDER_ID")
    with pytest.raises(RuntimeError, match="LIVE_HISTORY_FOLDER_ID"):
        get_watchers()


def test_a_watcher_without_an_api_path_is_refused() -> None:
    with pytest.raises(ValueError, match="dj-sets"):
        WatcherConfig(name="dj-sets", folder_id="csv-folder", api_path="")
