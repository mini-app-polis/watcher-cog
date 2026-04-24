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
