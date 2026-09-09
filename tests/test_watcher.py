from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import watcher_cog.watcher as watcher_module
from watcher_cog.config import WatcherConfig
from watcher_cog.watcher import _baseline_concern, run_watcher


class LoopExit(Exception):
    pass


def _file(file_id: str = "f", *, modified_time: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id, name=f"{file_id}.txt", mime_type=None, modified_time=modified_time
    )


def _cfg(**kwargs: object) -> WatcherConfig:
    return WatcherConfig(name="w", folder_id="folder", deployment_id="dep", **kwargs)  # type: ignore[arg-type]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


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
    # One ping, not two: the failed cycle did no work, and Healthchecks
    # fires on absence, so a ping from a cycle that raised would keep the
    # check green through an outage.
    assert ping.await_count == 1


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
        "drained_by_downstream",
        "baseline_recent_change_min",
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
    assert config.drained_by_downstream is True
    assert config.baseline_recent_change_min == 15
    assert config.parameters == {}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
#
# What this cog reports is deliberately narrow: the moment a trigger fires
# (work entering the pipeline, which nothing else outside Prefect records),
# and the moment polling breaks. Everything else is the steady state.


def _patch_report(
    monkeypatch: pytest.MonkeyPatch, *, lands: bool = True
) -> list[tuple]:
    """Capture (severity, text, notable) for every report the loop makes.

    The double returns a bool because the real ``_report`` does, and the
    loop's failure suppression turns on that value. A double returning
    ``None`` would put every test on the undelivered path by accident.
    Pass ``lands=False`` to exercise that path deliberately.
    """
    sent: list[tuple] = []

    async def _fake_report(config, severity, text, *, notable=False) -> bool:  # noqa: ANN001
        sent.append((severity, text, notable))
        return lands

    monkeypatch.setattr(watcher_module, "_report", _fake_report)
    return sent


@pytest.mark.asyncio
async def test_trigger_fired_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    # First cycle sees an empty folder so there is no baseline report to
    # separate from the one under test.
    folders = [[], [_file("b")]]
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
    """The steady state says nothing at all.

    Cycle 1 baselines the existing file and says so; cycle 2 is the quiet
    poll and must add nothing to that.
    """
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

    assert [s[0] for s in sent] == ["WARN"]
    assert "Baselined" in sent[0][1]


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

    # The third cycle is also the first that reached Drive, so it
    # baselines the folder before reporting the recovery.
    assert [s[0] for s in sent] == ["ERROR", "WARN", "SUCCESS"]
    assert "Baselined" in sent[1][1]
    assert "recovered after 2" in sent[2][1]


@pytest.mark.asyncio
async def test_trigger_failure_names_the_deployment_not_the_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that never started is not a poll that never read."""
    folders = [[], [_file("b")]]
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
            return []
        return [_file("b")]

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
async def test_heartbeat_is_not_pinged_on_a_failed_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cycle that raised did no work, and Healthchecks must not hear otherwise.

    The ping used to be in a `finally`, so it fired on every cycle
    including the ones that raised. Expired credentials could keep the
    check green indefinitely while the folder went unwatched — the
    absence detector reporting that the loop is spinning, not that it is
    working.
    """

    def _boom(_: str) -> list:
        raise RuntimeError("drive is down")

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _boom)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    ping = AsyncMock()
    monkeypatch.setattr(watcher_module.heartbeat, "ping", ping)
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(3, []))
    _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert ping.await_count == 0


@pytest.mark.asyncio
async def test_baselining_a_non_empty_folder_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart that swallows pending files says so.

    Files present on the first poll are the baseline and will never fire
    a trigger. On a first-ever start that is correct; on a restart it
    means anything that landed during the redeploy is invisible, and
    downstream archives files out of this folder, so invisible means
    unprocessed.
    """
    monkeypatch.setattr(
        watcher_module.drive_client, "list_folder", lambda _: [_file("a"), _file("b")]
    )
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(1, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert len(sent) == 1
    severity, text, notable = sent[0]
    assert severity == "WARN"
    assert notable is True
    assert "Baselined 2 pending file(s)" in text
    assert "folder" in text


@pytest.mark.asyncio
async def test_an_empty_folder_on_start_is_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was swallowed, so there is nothing to say."""
    monkeypatch.setattr(watcher_module.drive_client, "list_folder", lambda _: [])
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(1, []))
    sent = _patch_report(monkeypatch)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert sent == []


def test_drained_folder_warns_about_any_pending_file() -> None:
    concern = _baseline_concern(_cfg(drained_by_downstream=True), [_file()], _now())
    assert concern is not None


def test_undrained_folder_is_silent_about_old_files() -> None:
    """live-history's nineteen sheets are the steady state, not a backlog."""
    old = _file(modified_time="2026-01-01T00:00:00Z")
    assert _baseline_concern(_cfg(drained_by_downstream=False), [old], _now()) is None


def test_undrained_folder_warns_about_a_recent_change() -> None:
    """A sheet edited during the redeploy is a change that will not fire."""
    recent = _file(modified_time=_iso(_now() - timedelta(minutes=2)))
    assert _baseline_concern(_cfg(drained_by_downstream=False), [recent], _now())


def test_empty_folder_is_always_silent() -> None:
    assert _baseline_concern(_cfg(), [], _now()) is None


@pytest.mark.asyncio
async def test_undelivered_error_does_not_consume_the_suppression_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_report returning False leaves error_kind unset, so the next cycle retries.

    An outage that takes down Drive and the API together used to be
    completely silent: cycle 1's ERROR was swallowed by _report while the
    streak advanced anyway, so every later cycle suppressed itself as a
    repeat of a message nobody ever saw.
    """

    def _boom(_: str) -> list:
        raise RuntimeError("drive is down")

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _boom)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(3, []))
    sent = _patch_report(monkeypatch, lands=False)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    # Three cycles, three attempts — none of them landed, so none of them
    # earned the right to silence the next one.
    assert len(sent) == 3
    assert all(s[0] == "ERROR" for s in sent)


@pytest.mark.asyncio
async def test_a_delivered_error_does_consume_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: a message that landed still suppresses its repeats."""

    def _boom(_: str) -> list:
        raise RuntimeError("drive is down")

    monkeypatch.setattr(watcher_module.drive_client, "list_folder", _boom)
    monkeypatch.setattr(watcher_module.prefect_trigger, "fire", AsyncMock())
    monkeypatch.setattr(watcher_module.heartbeat, "ping", AsyncMock())
    monkeypatch.setattr(watcher_module.asyncio, "sleep", _make_sleep(3, []))
    sent = _patch_report(monkeypatch, lands=True)

    config = WatcherConfig(
        name="w1", folder_id="folder", deployment_id="dep", interval_min=1
    )
    with pytest.raises(LoopExit):
        await run_watcher(config)

    assert len(sent) == 1


@pytest.mark.asyncio
async def test_report_returns_whether_the_message_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop's suppression is only as good as this return value."""
    from mini_app_polis.pipeline_status import DeliveryReport

    config = WatcherConfig(name="w1", folder_id="f", deployment_id="d")

    for result, expected in (
        (DeliveryReport(sent=1), True),
        (DeliveryReport(suppressed=1), True),
        (DeliveryReport(failed=1), False),
        (DeliveryReport(skipped=1), False),
    ):
        monkeypatch.setattr(
            watcher_module, "post_run_finding", lambda *a, _r=result, **k: _r
        )
        assert await watcher_module._report(config, "ERROR", "x") is expected

    def _explode(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("notify exploded")

    monkeypatch.setattr(watcher_module, "post_run_finding", _explode)
    assert await watcher_module._report(config, "ERROR", "x") is False


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
