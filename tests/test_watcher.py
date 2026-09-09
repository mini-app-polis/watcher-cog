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


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
#
# What this cog reports is deliberately narrow: the moment a trigger fires
# (work entering the pipeline, which nothing else outside Prefect records),
# and the moment polling breaks. Everything else is the steady state.


def _patch_report(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Capture (severity, text, notable) for every report the loop makes."""
    sent: list[tuple] = []

    async def _fake_report(config, severity, text, *, notable=False) -> None:  # noqa: ANN001
        sent.append((severity, text, notable))

    monkeypatch.setattr(watcher_module, "_report", _fake_report)
    return sent


@pytest.mark.asyncio
async def test_trigger_fired_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    folders = [[_file("a")], [_file("a"), _file("b")]]
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: folders.pop(0)
    )
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert len(sent) == 1
    severity, text, notable = sent[0]
    assert severity == "SUCCESS"
    assert notable is True
    assert "1 new" in text


@pytest.mark.asyncio
async def test_quiet_poll_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The steady state says nothing at all."""
    folders = [[_file("a")], [_file("a")]]
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: folders.pop(0)
    )
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert sent == []


@pytest.mark.asyncio
async def test_only_the_first_failure_of_a_streak_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Drive outage is one message, not one per minute.

    This is the property that decides whether the channel is still worth
    reading during an incident. Suppression is per cause, so this covers
    repeats of a poll failure specifically.
    """

    def _boom(_: str) -> list:
        raise RuntimeError("drive is down")

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _boom)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(4, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert len(sent) == 1
    assert sent[0][0] == "ERROR"
    assert "drive is down" in sent[0][1]


@pytest.mark.asyncio
async def test_recovery_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the streak: you are told when it comes back."""
    calls = {"n": 0}

    def _flaky(_: str) -> list:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("drive is down")
        return [_file("a")]

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _flaky)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(3, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert [s[0] for s in sent] == ["ERROR", "SUCCESS"]
    assert "recovered after 2" in sent[1][1]


@pytest.mark.asyncio
async def test_trigger_failure_names_the_deployment_not_the_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that never started is not a poll that never read."""
    folders = [[_file("a")], [_file("a"), _file("b")]]
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: folders.pop(0)
    )

    async def _boom(deployment_id, parameters=None) -> None:  # noqa: ANN001
        raise RuntimeError("prefect unreachable")

    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", _boom)
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert len(sent) == 1
    severity, text, _notable = sent[0]
    assert severity == "ERROR"
    assert "Trigger failed" in text
    assert "dep" in text
    assert "prefect unreachable" in text
    assert "Poll failed" not in text


@pytest.mark.asyncio
async def test_a_new_cause_breaks_through_the_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Drive outage already reported must not silence a trigger failure."""
    calls = {"n": 0}

    def _list_folder(_: str) -> list:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("drive is down")
        if calls["n"] == 1:
            return [_file("a")]
        return [_file("a"), _file("b")]

    async def _boom(deployment_id, parameters=None) -> None:  # noqa: ANN001
        raise RuntimeError("prefect unreachable")

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _list_folder)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", _boom)
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(3, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    texts = [text for _sev, text, _notable in sent]
    assert any("Poll failed" in t for t in texts)
    assert any("Trigger failed" in t for t in texts)


@pytest.mark.asyncio
async def test_repeats_of_the_same_cause_stay_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three failing triggers in a row are still one message.

    The poll side of this is covered above; this is the same property on
    the branch that did not exist before. It also pins the retry: ``seen``
    is not advanced on a failed trigger, so every cycle sees the same new
    file and tries to fire again.
    """
    calls = {"n": 0}
    fired = {"n": 0}

    def _list_folder(_: str) -> list:
        calls["n"] += 1
        if calls["n"] == 1:
            return [_file("a")]
        return [_file("a"), _file("b")]

    async def _boom(deployment_id, parameters=None) -> None:  # noqa: ANN001
        fired["n"] += 1
        raise RuntimeError("prefect unreachable")

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _list_folder)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", _boom)
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(4, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert fired["n"] == 3
    assert sum(1 for _sev, t, _notable in sent if "Trigger failed" in t) == 1


@pytest.mark.asyncio
async def test_report_never_breaks_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reporting is the least important thing this cog does."""
    folders = [[_file("a")], [_file("a"), _file("b")]]
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: folders.pop(0)
    )
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    sleep_calls: list[float] = []
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(2, sleep_calls))

    def _explode(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("notify exploded")

    monkeypatch.setattr(watcher_module, "post_run_finding", _explode)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    # The loop completed both cycles despite reporting blowing up.
    assert len(sleep_calls) == 2
