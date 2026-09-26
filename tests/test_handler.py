from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from watcher_cog import handler, watcher
from watcher_cog.config import WatcherConfig


def _cfg(name: str) -> WatcherConfig:
    return WatcherConfig(name=name, folder_id=name, api_path="/v1/x/runs")


@pytest.fixture
def ping(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    ping = MagicMock()
    monkeypatch.setattr(handler.heartbeat, "ping", ping)
    monkeypatch.setattr(handler, "get_watchers", lambda: [_cfg("a"), _cfg("b")])
    return ping


def test_a_clean_tick_checks_every_folder_and_pings(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    checked: list[str] = []

    def check(config: WatcherConfig) -> watcher.Check:
        checked.append(config.name)
        return watcher.Check(watcher=config.name, files=1, queued=["m"])

    monkeypatch.setattr(handler.watcher, "check", check)

    result = handler.lambda_handler({}, None)

    assert checked == ["a", "b"]
    assert result == {"queued": 2, "deduplicated": 0, "files": 2}
    ping.assert_called_once()


def test_a_failed_folder_fails_the_tick_after_the_rest(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    """The error alarm counts failed invocations; the heartbeat stays quiet."""
    checked: list[str] = []

    def check(config: WatcherConfig) -> watcher.Check:
        checked.append(config.name)
        if config.name == "a":
            raise RuntimeError("drive down")
        return watcher.Check(watcher=config.name)

    monkeypatch.setattr(handler.watcher, "check", check)
    capture = MagicMock()
    monkeypatch.setattr(handler.sentry_sdk, "capture_exception", capture)

    with pytest.raises(handler.TickFailed, match="a: RuntimeError: drive down"):
        handler.lambda_handler({}, None)

    assert checked == ["a", "b"]
    capture.assert_called_once()
    ping.assert_not_called()
