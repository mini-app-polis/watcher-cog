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
async def test_main_logs_error_when_watcher_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
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
