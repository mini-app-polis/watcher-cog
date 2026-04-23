from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from watcher_cog import prefect_trigger


@pytest.mark.asyncio
async def test_fire_success_logs_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREFECT_API_KEY", "key")
    monkeypatch.setenv(
        "PREFECT_API_URL", "https://api.prefect.cloud/api/accounts/a/workspaces/w"
    )

    response = MagicMock(status_code=201)
    response.raise_for_status.return_value = None
    post = AsyncMock(return_value=response)
    client = MagicMock()
    client.post = post
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls = MagicMock(return_value=context_manager)
    monkeypatch.setattr(prefect_trigger.httpx, "AsyncClient", mock_client_cls)

    logger = MagicMock()
    monkeypatch.setattr(prefect_trigger, "log", logger)

    await prefect_trigger.fire("dep-123")

    post.assert_awaited_once()
    logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_fire_raises_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREFECT_API_KEY", "key")
    monkeypatch.setenv(
        "PREFECT_API_URL", "https://api.prefect.cloud/api/accounts/a/workspaces/w"
    )

    response = MagicMock(status_code=500)
    response.raise_for_status.side_effect = RuntimeError("server error")
    post = AsyncMock(return_value=response)
    client = MagicMock()
    client.post = post
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls = MagicMock(return_value=context_manager)
    monkeypatch.setattr(prefect_trigger.httpx, "AsyncClient", mock_client_cls)

    with pytest.raises(RuntimeError, match="server error"):
        await prefect_trigger.fire("dep-123")
