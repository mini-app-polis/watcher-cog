from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from watcher_cog import drive_client


def test_list_folder_returns_files(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    google = SimpleNamespace(
        drive=SimpleNamespace(get_files_in_folder=lambda folder_id: expected)
    )
    monkeypatch.setattr(drive_client, "_google_api", google)

    result = drive_client.list_folder("folder-1")

    assert result == expected


def test_get_file_modified_time_parses_iso(monkeypatch: pytest.MonkeyPatch) -> None:
    response = {"modifiedTime": "2026-03-24T17:55:00.000Z"}

    class FilesAPI:
        def get(self, **kwargs) -> dict:  # noqa: ANN003
            assert kwargs["fileId"] == "file-1"
            assert kwargs["fields"] == "modifiedTime"
            return self  # type: ignore[return-value]

        def execute(self) -> dict[str, str]:
            return response

    google = SimpleNamespace(
        drive=SimpleNamespace(service=SimpleNamespace(files=lambda: FilesAPI()))
    )
    monkeypatch.setattr(drive_client, "_google_api", google)

    result = drive_client.get_file_modified_time("file-1")

    assert result == datetime(2026, 3, 24, 17, 55, tzinfo=UTC)


def test_get_file_modified_time_returns_none_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FilesAPI:
        def get(self, **kwargs) -> dict:  # noqa: ANN003
            return self  # type: ignore[return-value]

        def execute(self) -> dict[str, str]:
            raise RuntimeError("404 not found")

    google = SimpleNamespace(
        drive=SimpleNamespace(service=SimpleNamespace(files=lambda: FilesAPI()))
    )
    monkeypatch.setattr(drive_client, "_google_api", google)

    assert drive_client.get_file_modified_time("missing") is None


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
