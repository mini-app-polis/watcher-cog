from __future__ import annotations

from types import SimpleNamespace

import pytest

from watcher_cog import drive_client


def test_list_folder_returns_files(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    google = SimpleNamespace(
        drive=SimpleNamespace(
            get_files_in_folder=lambda folder_id, include_folders=True: expected
        )
    )
    monkeypatch.setattr(drive_client, "_google_api", google)

    result = drive_client.list_folder("folder-1")

    assert result == expected


def test_list_folder_excludes_subfolders(monkeypatch: pytest.MonkeyPatch) -> None:
    """A processed/ subfolder is not a pending file and its mtime is not news."""
    captured: dict[str, object] = {}

    def get_files_in_folder(folder_id: str, include_folders: bool = True) -> list:
        captured["folder_id"] = folder_id
        captured["include_folders"] = include_folders
        return []

    google = SimpleNamespace(
        drive=SimpleNamespace(get_files_in_folder=get_files_in_folder)
    )
    monkeypatch.setattr(drive_client, "_google_api", google)

    drive_client.list_folder("folder-1")

    assert captured["folder_id"] == "folder-1"
    assert captured["include_folders"] is False


def test_get_google_api_resets_singleton_on_init_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(drive_client, "_google_api", None)

    class BrokenGoogleAPI:
        @classmethod
        def from_env(cls) -> BrokenGoogleAPI:
            raise RuntimeError("bad credentials")

    monkeypatch.setattr(drive_client, "GoogleAPI", BrokenGoogleAPI)

    with pytest.raises(RuntimeError, match="bad credentials"):
        drive_client._get_google_api()

    assert drive_client._google_api is None
