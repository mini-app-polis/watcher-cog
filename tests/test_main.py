"""Tests for application entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import watcher_cog.main as main_module
from watcher_cog.config import WatcherConfig
from watcher_cog.main import main


@pytest.mark.asyncio
async def test_main_no_watchers_exits_early(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "get_watchers", lambda: [])
    monkeypatch.setattr("watcher_cog.main.load_dotenv", lambda: None)
    monkeypatch.setattr("watcher_cog.main.sentry_sdk.init", lambda **kwargs: None)
    logger = MagicMock()
    monkeypatch.setattr(main_module, "log", logger)

    await main()

    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_main_logs_error_when_watcher_crashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = WatcherConfig(name="bad-watcher", folder_id="f", deployment_id="d")
    monkeypatch.setattr(main_module, "get_watchers", lambda: [config])
    monkeypatch.setattr("watcher_cog.main.load_dotenv", lambda: None)
    monkeypatch.setattr("watcher_cog.main.sentry_sdk.init", lambda **kwargs: None)

    async def _crashing_watcher(_: WatcherConfig) -> None:
        raise RuntimeError("fatal watcher error")

    monkeypatch.setattr(main_module, "run_watcher", _crashing_watcher)
    logger = MagicMock()
    monkeypatch.setattr(main_module, "log", logger)

    await main()

    logger.error.assert_called_once()
    call_args = logger.error.call_args[0]
    assert "bad-watcher" in call_args[1]


@pytest.mark.asyncio
async def test_a_dying_watcher_reports_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_supervise reports before re-raising, not when gather finally returns.

    ``asyncio.gather`` only hands back an exception once every task has
    finished, and these are infinite loops — so without this wrapper a
    crashed watcher is reported when the last one stops, which in
    practice is never. The process stays up, siblings keep polling, and
    one folder silently stops being watched.
    """
    import watcher_cog.watcher as watcher_module

    config = WatcherConfig(name="w1", folder_id="folder-1", deployment_id="dep")
    sent: list[tuple] = []

    async def _fake_report(cfg, severity, text, *, notable=False) -> bool:  # noqa: ANN001
        sent.append((severity, text, notable))
        return True

    async def _crashing_watcher(_: WatcherConfig) -> None:
        raise RuntimeError("credentials expired")

    monkeypatch.setattr(watcher_module, "_report", _fake_report)
    monkeypatch.setattr(main_module, "run_watcher", _crashing_watcher)

    # Reported on the way out, and the exception still propagates so
    # main()'s gather still logs it.
    with pytest.raises(RuntimeError, match="credentials expired"):
        await main_module._supervise(config)

    assert len(sent) == 1
    severity, text, notable = sent[0]
    assert severity == "CRITICAL"
    assert notable is True
    assert "folder-1" in text
    assert "credentials expired" in text
    assert "no longer" in text


@pytest.mark.asyncio
async def test_main_runs_watchers_through_the_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper is only worth having if main() actually uses it.

    Asserted through main() rather than by calling _supervise directly,
    because the defect this guards against is the wiring being dropped —
    which a direct call would not notice.
    """
    import watcher_cog.watcher as watcher_module

    config = WatcherConfig(name="w1", folder_id="folder-1", deployment_id="dep")
    monkeypatch.setattr(main_module, "get_watchers", lambda: [config])
    monkeypatch.setattr("watcher_cog.main.load_dotenv", lambda: None)
    monkeypatch.setattr("watcher_cog.main.sentry_sdk.init", lambda **kwargs: None)
    monkeypatch.setattr(main_module, "log", MagicMock())

    sent: list[tuple] = []

    async def _fake_report(cfg, severity, text, *, notable=False) -> bool:  # noqa: ANN001
        sent.append((severity, text, notable))
        return True

    async def _crashing_watcher(_: WatcherConfig) -> None:
        raise RuntimeError("credentials expired")

    monkeypatch.setattr(watcher_module, "_report", _fake_report)
    monkeypatch.setattr(main_module, "run_watcher", _crashing_watcher)

    await main()

    assert len(sent) == 1
    assert sent[0][0] == "CRITICAL"
    assert "folder-1" in sent[0][1]


@pytest.mark.asyncio
async def test_a_failing_report_does_not_swallow_the_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper must not turn a crash into a different crash."""
    import watcher_cog.watcher as watcher_module

    config = WatcherConfig(name="w1", folder_id="folder-1", deployment_id="dep")

    async def _exploding_report(*args, **kwargs) -> bool:  # noqa: ANN002, ANN003
        raise RuntimeError("notify exploded")

    async def _crashing_watcher(_: WatcherConfig) -> None:
        raise RuntimeError("credentials expired")

    monkeypatch.setattr(watcher_module, "_report", _exploding_report)
    monkeypatch.setattr(main_module, "run_watcher", _crashing_watcher)

    with pytest.raises(RuntimeError, match="credentials expired"):
        await main_module._supervise(config)


@pytest.mark.asyncio
async def test_cancellation_is_not_reported_as_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl-C must not post CRITICAL, and must not block on an HTTP call."""
    import asyncio

    import watcher_cog.watcher as watcher_module

    config = WatcherConfig(name="w1", folder_id="folder-1", deployment_id="dep")
    sent: list[tuple] = []

    async def _fake_report(cfg, severity, text, *, notable=False) -> bool:  # noqa: ANN001
        sent.append((severity, text, notable))
        return True

    async def _cancelled_watcher(_: WatcherConfig) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(watcher_module, "_report", _fake_report)
    monkeypatch.setattr(main_module, "run_watcher", _cancelled_watcher)

    with pytest.raises(asyncio.CancelledError):
        await main_module._supervise(config)

    assert sent == []


@pytest.mark.asyncio
async def test_main_crash_in_one_watcher_does_not_stop_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEST-003: a crash in one watcher does not prevent sibling
    watchers from running to completion. This is the asyncio.gather
    (return_exceptions=True) resilience contract in main()."""
    bad = WatcherConfig(name="bad-watcher", folder_id="f-bad", deployment_id="d-bad")
    good = WatcherConfig(
        name="good-watcher", folder_id="f-good", deployment_id="d-good"
    )
    monkeypatch.setattr(main_module, "get_watchers", lambda: [bad, good])
    monkeypatch.setattr("watcher_cog.main.load_dotenv", lambda: None)
    monkeypatch.setattr("watcher_cog.main.sentry_sdk.init", lambda **kwargs: None)

    good_watcher_ran_to_completion = False

    async def _watcher(config: WatcherConfig) -> None:
        nonlocal good_watcher_ran_to_completion
        if config.name == "bad-watcher":
            raise RuntimeError("fatal watcher error")
        # The "good" watcher does a tiny amount of work and returns
        # cleanly — proving it was not killed by its sibling's crash.
        good_watcher_ran_to_completion = True

    monkeypatch.setattr(main_module, "run_watcher", _watcher)
    logger = MagicMock()
    monkeypatch.setattr(main_module, "log", logger)

    await main()

    # The crash was logged with the bad watcher's name.
    assert logger.error.call_count == 1
    error_call_args = logger.error.call_args[0]
    assert "bad-watcher" in error_call_args[1]

    # And — this is the resilience contract — the good watcher ran.
    assert good_watcher_ran_to_completion is True
