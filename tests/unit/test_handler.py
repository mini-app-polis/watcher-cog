from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from watcher_cog import handler, watcher
from watcher_cog.config import WatcherConfig


def _cfg(name: str) -> WatcherConfig:
    return WatcherConfig(name=name, folder_id=name, api_path="/v1/x/runs")


@pytest.fixture(autouse=True)
def refresh(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    refresh = MagicMock()
    monkeypatch.setattr(handler, "load_secrets", refresh)
    return refresh


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

    def check(config: WatcherConfig, deadline: float | None = None) -> watcher.Check:
        checked.append(config.name)
        return watcher.Check(watcher=config.name, files=1, queued=["m"])

    monkeypatch.setattr(handler.watcher, "check", check)

    result = handler.lambda_handler({}, None)

    assert checked == ["a", "b"]
    assert result == {"watcher": "all", "queued": 2, "deduplicated": 0, "files": 2}
    ping.assert_called_once()


def test_a_tick_does_not_report_settings_again(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    """The report is once per cold start, at import; a warm tick is quiet."""
    report = MagicMock()
    monkeypatch.setattr(handler, "log_settings", report)
    monkeypatch.setattr(
        handler.watcher,
        "check",
        lambda config, deadline=None: watcher.Check(watcher=config.name),
    )

    handler.lambda_handler({}, None)

    report.assert_not_called()


def test_a_failed_folder_fails_the_tick_after_the_rest(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    """The error alarm counts failed invocations; the heartbeat stays quiet."""
    checked: list[str] = []

    def check(config: WatcherConfig, deadline: float | None = None) -> watcher.Check:
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


def test_an_unreachable_api_fails_the_tick_without_a_sentry_issue(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    """The alarm's window decides whether it lasted long enough to matter."""

    def check(config: WatcherConfig, deadline: float | None = None) -> watcher.Check:
        raise watcher.ApiUnreachable(f"{config.name}: 1 ask(s) failed")

    monkeypatch.setattr(handler.watcher, "check", check)
    capture = MagicMock()
    monkeypatch.setattr(handler.sentry_sdk, "capture_exception", capture)

    with pytest.raises(handler.TickFailed, match="ApiUnreachable"):
        handler.lambda_handler({}, None)

    capture.assert_not_called()
    ping.assert_not_called()


def test_each_tick_reloads_settings_and_applies_the_logging_level(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock, refresh: MagicMock
) -> None:
    monkeypatch.setattr(
        handler.watcher,
        "check",
        lambda c, deadline=None: watcher.Check(watcher=c.name, files=0),
    )
    monkeypatch.setenv("LOGGING_LEVEL", "DEBUG")

    handler.lambda_handler({}, None)

    refresh.assert_called_once_with(refresh=True)
    assert handler.log.level == logging.DEBUG


def test_a_settings_reload_that_fails_fails_the_tick(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock, refresh: MagicMock
) -> None:
    refresh.side_effect = RuntimeError("parameter gone")
    check = MagicMock()
    monkeypatch.setattr(handler.watcher, "check", check)

    with pytest.raises(RuntimeError, match="parameter gone"):
        handler.lambda_handler({}, None)

    check.assert_not_called()
    ping.assert_not_called()


def test_an_event_naming_a_folder_checks_only_that_folder(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    """One schedule target per folder: each invocation is one folder's tick."""
    checked: list[str] = []

    def check(config: WatcherConfig, deadline: float | None = None) -> watcher.Check:
        checked.append(config.name)
        return watcher.Check(watcher=config.name, files=3)

    monkeypatch.setattr(handler.watcher, "check", check)

    result = handler.lambda_handler({"watcher": "b"}, None)

    assert checked == ["b"]
    assert result == {"watcher": "b", "queued": 0, "deduplicated": 0, "files": 3}
    ping.assert_called_once()


def test_a_failing_folder_does_not_fail_another_folders_tick(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    def check(config: WatcherConfig, deadline: float | None = None) -> watcher.Check:
        if config.name == "a":
            raise RuntimeError("drive down")
        return watcher.Check(watcher=config.name)

    monkeypatch.setattr(handler.watcher, "check", check)
    monkeypatch.setattr(handler.sentry_sdk, "capture_exception", MagicMock())

    with pytest.raises(handler.TickFailed, match="a: RuntimeError"):
        handler.lambda_handler({"watcher": "a"}, None)
    handler.lambda_handler({"watcher": "b"}, None)

    ping.assert_called_once()


def test_an_unknown_folder_name_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    """A schedule target that drifts from the config must not watch nothing."""
    check = MagicMock()
    monkeypatch.setattr(handler.watcher, "check", check)

    with pytest.raises(ValueError, match="no watcher named 'c'"):
        handler.lambda_handler({"watcher": "c"}, None)

    check.assert_not_called()
    ping.assert_not_called()


def test_the_deadline_leaves_room_for_one_ask_inside_the_timeout(
    monkeypatch: pytest.MonkeyPatch, ping: MagicMock
) -> None:
    deadlines: list[float | None] = []

    def check(config: WatcherConfig, deadline: float | None = None) -> watcher.Check:
        deadlines.append(deadline)
        return watcher.Check(watcher=config.name)

    monkeypatch.setattr(handler.watcher, "check", check)
    monkeypatch.setattr(handler.time, "monotonic", lambda: 100.0)
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 50_000

    handler.lambda_handler({"watcher": "a"}, context)

    assert deadlines == [100.0 + 50 - handler.DEADLINE_MARGIN_SECONDS]
