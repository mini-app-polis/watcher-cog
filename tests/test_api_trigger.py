from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mini_app_polis.api import KaianoApiError

from watcher_cog import api_trigger


def _client(monkeypatch: pytest.MonkeyPatch, **post: object) -> MagicMock:
    """Patch the API client factory; return the fake client."""
    client = MagicMock()
    for key, value in post.items():
        setattr(client.post, key, value)
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(api_trigger.KaianoApiClient, "from_env", factory)
    client.factory = factory
    return client


@pytest.mark.asyncio
async def test_fire_posts_the_parameters_as_watcher_cog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        monkeypatch,
        return_value={"data": {"accepted": True, "message_id": "m-1"}},
    )
    monkeypatch.setattr(api_trigger, "log", MagicMock())

    result = await api_trigger.fire(
        "/v1/deejay/runs", parameters={"mode": "process-new-files"}
    )

    assert result == "m-1"
    client.factory.assert_called_once_with(machine_name="watcher-cog")
    client.post.assert_called_once_with(
        "/v1/deejay/runs", {"mode": "process-new-files"}
    )


@pytest.mark.asyncio
async def test_a_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop retries only what raised; a swallowed 502 is a lost upload."""
    _client(
        monkeypatch,
        side_effect=KaianoApiError(502, "dispatch_failed", "/v1/deejay/runs"),
    )

    with pytest.raises(KaianoApiError):
        await api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})


@pytest.mark.asyncio
async def test_an_acknowledgement_without_a_message_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 2xx nobody can trace is not evidence the work was queued."""
    _client(monkeypatch, return_value={"data": {"accepted": True}})

    with pytest.raises(KaianoApiError, match="message id"):
        await api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "local"])
async def test_outside_production_nothing_is_called(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """A dev watcher polls production's folders; its trigger must not fire.

    The dev API once resolved itself as production and addressed
    deejay-jobs. Suppressing here does not depend on it getting that right.
    """
    monkeypatch.setenv("ENVIRONMENT", environment)
    client = _client(monkeypatch, return_value={"data": {"message_id": "m-1"}})
    monkeypatch.setattr(api_trigger, "log", MagicMock())

    result = await api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})

    assert result is None
    client.factory.assert_not_called()
