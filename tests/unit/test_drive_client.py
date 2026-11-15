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


def test_google_api_built_with_bounded_socket_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client's transport gets the Drive timeout; the process keeps its own."""
    import socket

    seen: dict[str, object] = {}

    class RecordingGoogleAPI:
        @classmethod
        def from_env(cls) -> RecordingGoogleAPI:
            seen["timeout"] = socket.getdefaulttimeout()
            return cls()

    monkeypatch.setattr(drive_client, "_google_api", None)
    monkeypatch.setattr(drive_client, "GoogleAPI", RecordingGoogleAPI)
    socket.setdefaulttimeout(None)

    drive_client._get_google_api()

    assert seen["timeout"] == drive_client.DRIVE_TIMEOUT_SECONDS
    assert socket.getdefaulttimeout() is None


def test_socket_timeout_restored_when_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    class BrokenGoogleAPI:
        @classmethod
        def from_env(cls) -> BrokenGoogleAPI:
            raise RuntimeError("bad credentials")

    monkeypatch.setattr(drive_client, "_google_api", None)
    monkeypatch.setattr(drive_client, "GoogleAPI", BrokenGoogleAPI)
    socket.setdefaulttimeout(3.0)
    try:
        with pytest.raises(RuntimeError):
            drive_client._get_google_api()
        assert socket.getdefaulttimeout() == 3.0
    finally:
        socket.setdefaulttimeout(None)


def test_list_folder_runs_under_listing_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive retries inside a listing see a run deadline of the listing budget."""
    from mini_app_polis.deadline import remaining_seconds

    seen: dict[str, float | None] = {}

    def get_files_in_folder(folder_id: str, include_folders: bool = True) -> list:
        seen["remaining"] = remaining_seconds()
        return []

    google = SimpleNamespace(
        drive=SimpleNamespace(get_files_in_folder=get_files_in_folder)
    )
    monkeypatch.setattr(drive_client, "_google_api", google)

    drive_client.list_folder("folder-1")

    remaining = seen["remaining"]
    assert remaining is not None
    assert 0 < remaining <= drive_client.LIST_BUDGET_SECONDS
    assert remaining_seconds() is None


def test_listing_fits_inside_the_ask_deadline() -> None:
    """A listing at its worst still ends before the handler stops making asks.

    The function timeout is 50s (mini-app-polis/infra); asks stop starting
    at the timeout less ``DEADLINE_MARGIN_SECONDS``. A listing ends at most
    one request timeout after its budget.
    """
    from watcher_cog import handler

    function_timeout = 50.0
    ask_deadline = function_timeout - handler.DEADLINE_MARGIN_SECONDS
    worst_listing = (
        drive_client.LIST_BUDGET_SECONDS + drive_client.DRIVE_TIMEOUT_SECONDS
    )
    assert worst_listing < ask_deadline
