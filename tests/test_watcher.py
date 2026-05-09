from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import watcher_cog.watcher as watcher_module
from watcher_cog.config import WatcherConfig
from watcher_cog.watcher import run_watcher


class LoopExit(Exception):
    pass


def _file(file_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id, name=f"{file_id}.txt", mime_type=None, modified_time=None
    )


def _make_sleep(
    stop_after_calls: int,
    calls: list[float],
) -> Callable[[float], Awaitable[None]]:
    async def _sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= stop_after_calls:
            raise LoopExit()

    return _sleep


@pytest.mark.asyncio
async def test_first_run_initializes_without_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def list_folder(_: str) -> list:
        return [_file("a"), _file("b")]

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", list_folder)
    fire = AsyncMock()
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", fire)
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(1, sleep_calls))

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=2
    )

    with pytest.raises(LoopExit):
        await run_watcher(config)

    fire.assert_not_awaited()
    assert sleep_calls == [120]


@pytest.mark.asyncio
async def test_second_run_no_new_files_no_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders = [[_file("a"), _file("b")], [_file("a"), _file("b")]]
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: folders.pop(0)
    )
    fire = AsyncMock()
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", fire)
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, sleep_calls))

    config = WatcherConfig(name="w1", folder_id="folder", deployment_id="dep")

    with pytest.raises(LoopExit):
        await run_watcher(config)

    fire.assert_not_awaited()
    assert sleep_calls == [60, 60]


@pytest.mark.asyncio
async def test_second_run_with_new_files_fires_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders = [[_file("a"), _file("b")], [_file("a"), _file("b"), _file("c")]]
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: folders.pop(0)
    )
    fire = AsyncMock()
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", fire)
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, sleep_calls))

    config = WatcherConfig(name="w1", folder_id="folder", deployment_id="dep")

    with pytest.raises(LoopExit):
        await run_watcher(config)

    # Default WatcherConfig has parameters={}; the trigger forwards it.
    fire.assert_awaited_once_with("dep", parameters={})
    assert sleep_calls == [60, 60]


@pytest.mark.asyncio
async def test_poll_error_caught_and_loop_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _list_folder(_: str) -> list:
        if _list_folder.calls == 0:
            _list_folder.calls += 1
            raise RuntimeError("boom")
        _list_folder.calls += 1
        return [_file("a")]

    _list_folder.calls = 0

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _list_folder)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    ping = AsyncMock()
    monkeypatch.setattr(watcher_module.heartbeat, "ping", ping)
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, sleep_calls))
    logger = MagicMock()
    monkeypatch.setattr(watcher_module, "log", logger)

    config = WatcherConfig(name="w1", folder_id="folder", deployment_id="dep")

    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert _list_folder.calls == 2
    logger.error.assert_called_once()
    assert ping.await_count == 2


@pytest.mark.asyncio
async def test_activity_signal_recent_file_uses_active_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: [_file("a")]
    )
    monkeypatch.setattr(
        watcher_module.drive_client,
        "get_file_modified_time",
        lambda _: datetime.now(UTC) - timedelta(minutes=1),
    )
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(1, sleep_calls))

    config = WatcherConfig(
        name="w1",
        folder_id="folder",
        deployment_id="dep",
        interval_min=2,
        idle_interval_min=10,
        activity_signal="file_mod_time",
        activity_file_id="signal-file",
        activity_threshold_min=10,
    )

    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert sleep_calls == [120]


@pytest.mark.asyncio
async def test_activity_signal_old_file_uses_idle_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: [_file("a")]
    )
    monkeypatch.setattr(
        watcher_module.drive_client,
        "get_file_modified_time",
        lambda _: datetime.now(UTC) - timedelta(minutes=30),
    )
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(1, sleep_calls))

    config = WatcherConfig(
        name="w1",
        folder_id="folder",
        deployment_id="dep",
        interval_min=2,
        idle_interval_min=10,
        activity_signal="file_mod_time",
        activity_file_id="signal-file",
        activity_threshold_min=10,
    )

    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert sleep_calls == [600]


def test_watcher_config_dataclass_field_set() -> None:
    """TEST-004: assert WatcherConfig exposes exactly the expected
    field set. A silent add/remove of a config field would pass the
    constructor-call tests without this check."""
    fields = {f.name for f in dataclasses.fields(WatcherConfig)}
    assert fields == {
        "name",
        "folder_id",
        "deployment_id",
        "interval_min",
        "idle_interval_min",
        "activity_signal",
        "activity_file_id",
        "activity_threshold_min",
        "parameters",
    }


def test_watcher_config_default_values() -> None:
    """Shape-adjacent: defaults are stable across the optional fields.
    Catches a change like flipping a default that would silently alter
    the trigger cadence for existing watchers."""
    config = WatcherConfig(name="w", folder_id="f", deployment_id="d")

    assert config.interval_min == 1
    assert config.idle_interval_min == 1
    assert config.activity_signal == "none"
    assert config.activity_file_id is None
    assert config.activity_threshold_min == 10
    assert config.parameters == {}
