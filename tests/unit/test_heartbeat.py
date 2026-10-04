from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from watcher_cog import heartbeat


def test_ping_calls_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCHECKS_URL_WATCHER", "https://hc-ping.com/abc")
    get = MagicMock()
    monkeypatch.setattr(heartbeat.httpx, "get", get)

    heartbeat.ping()

    get.assert_called_once_with("https://hc-ping.com/abc", timeout=10)


def test_no_url_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCHECKS_URL_WATCHER", raising=False)
    get = MagicMock()
    monkeypatch.setattr(heartbeat.httpx, "get", get)

    heartbeat.ping()

    get.assert_not_called()


def test_a_failed_ping_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """The next tick is the retry; a tick must not fail over its ping."""
    monkeypatch.setenv("HEALTHCHECKS_URL_WATCHER", "https://hc-ping.com/abc")
    monkeypatch.setattr(
        heartbeat.httpx, "get", MagicMock(side_effect=RuntimeError("down"))
    )

    heartbeat.ping()


@pytest.mark.parametrize("environment", ["development", "local"])
def test_outside_production_the_url_is_not_read(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """A dev process pinging production's check would hold it green."""
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("HEALTHCHECKS_URL_WATCHER", "https://hc-ping.com/abc")
    get = MagicMock()
    monkeypatch.setattr(heartbeat.httpx, "get", get)

    heartbeat.ping()

    get.assert_not_called()
