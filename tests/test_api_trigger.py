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


def test_new_work_is_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        monkeypatch, return_value={"data": {"accepted": True, "message_id": "m-1"}}
    )

    fired = api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})

    assert fired == api_trigger.Fired(message_id="m-1")
    assert fired.queued
    client.factory.assert_called_once_with(machine_name="watcher-cog")
    client.post.assert_called_once_with("/v1/deejay/runs", {"mode": "x"})


def test_a_deduplicated_answer_is_not_new_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The steady state: every tick re-asks for a file still being processed."""
    _client(
        monkeypatch,
        return_value={"data": {"message_id": "m-0", "deduplicated": True}},
    )

    fired = api_trigger.fire("/v1/transcription/runs", parameters={"mode": "x"})

    assert fired.deduplicated
    assert fired.message_id == "m-0"
    assert not fired.queued


def test_a_deduplicated_answer_may_lack_a_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Between another ask's claim and its enqueue there is no id yet."""
    _client(monkeypatch, return_value={"data": {"deduplicated": True}})

    fired = api_trigger.fire("/v1/transcription/runs", parameters={"mode": "x"})

    assert fired.deduplicated
    assert not fired.queued


def test_a_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _client(
        monkeypatch,
        side_effect=KaianoApiError(502, "dispatch_failed", "/v1/deejay/runs"),
    )

    with pytest.raises(KaianoApiError):
        api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})


def test_new_work_without_a_message_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 2xx nobody can trace is not evidence the work was queued."""
    _client(monkeypatch, return_value={"data": {"accepted": True}})

    with pytest.raises(KaianoApiError, match="message id"):
        api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})


@pytest.mark.parametrize("environment", ["development", "local"])
def test_outside_production_nothing_is_called(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """A dev watcher polls production's folders; its trigger must not fire."""
    monkeypatch.setenv("ENVIRONMENT", environment)
    client = _client(monkeypatch, return_value={"data": {"message_id": "m-1"}})

    fired = api_trigger.fire("/v1/deejay/runs", parameters={"mode": "x"})

    assert fired.suppressed
    assert not fired.queued
    client.factory.assert_not_called()
