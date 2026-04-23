from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from watcher_cog import prefect_trigger


def _mock_get_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    create_side_effect: Exception | None = None,
) -> AsyncMock:
    """Patch prefect_trigger.get_client and return mocked create call."""
    flow_run = MagicMock()
    flow_run.id = "flow-run-abc"

    create = AsyncMock(return_value=flow_run)
    if create_side_effect is not None:
        create.side_effect = create_side_effect

    client = MagicMock()
    client.create_flow_run_from_deployment = create

    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)

    get_client_mock = MagicMock(return_value=context_manager)
    monkeypatch.setattr(prefect_trigger, "get_client", get_client_mock)
    return create


@pytest.mark.asyncio
async def test_fire_success_logs_flow_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    create = _mock_get_client(monkeypatch)

    logger = MagicMock()
    monkeypatch.setattr(prefect_trigger, "log", logger)

    await prefect_trigger.fire("dep-123")

    create.assert_awaited_once_with(deployment_id="dep-123")
    logger.info.assert_called_once()
    args = logger.info.call_args.args
    assert "dep-123" in args
    assert "flow-run-abc" in args


@pytest.mark.asyncio
async def test_fire_propagates_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_client(
        monkeypatch,
        create_side_effect=RuntimeError("prefect api unavailable"),
    )

    with pytest.raises(RuntimeError, match="prefect api unavailable"):
        await prefect_trigger.fire("dep-123")
