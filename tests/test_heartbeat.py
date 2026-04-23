from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from watcher_cog import heartbeat


@pytest.mark.asyncio
async def test_ping_calls_get_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCHECKS_URL_WATCHER", "https://hc-ping.com/abc")

    response = MagicMock()
    response.raise_for_status.return_value = None
    get = AsyncMock(return_value=response)
    client = MagicMock()
    client.get = get
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        heartbeat.httpx, "AsyncClient", MagicMock(return_value=context_manager)
    )

    await heartbeat.ping()

    get.assert_awaited_once_with("https://hc-ping.com/abc")


@pytest.mark.asyncio
async def test_ping_no_url_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCHECKS_URL_WATCHER", raising=False)
    async_client = MagicMock()
    monkeypatch.setattr(heartbeat.httpx, "AsyncClient", async_client)

    await heartbeat.ping()

    async_client.assert_not_called()


@pytest.mark.asyncio
async def test_ping_exception_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEALTHCHECKS_URL_WATCHER", "https://hc-ping.com/abc")

    get = AsyncMock(side_effect=RuntimeError("network error"))
    client = MagicMock()
    client.get = get
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        heartbeat.httpx, "AsyncClient", MagicMock(return_value=context_manager)
    )

    logger = MagicMock()
    monkeypatch.setattr(heartbeat, "log", logger)

    await heartbeat.ping()

    logger.error.assert_called_once()
