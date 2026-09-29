from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mini_app_polis.api import KaianoApiClient, KaianoApiError
from pydantic import ValidationError

from watcher_cog import api_trigger

#: Valid bodies for the two run endpoints.
DEEJAY = {"mode": "process-new-files"}
TRANSCRIPTION = {"mode": "wcs-transcripts", "drive_file_id": "f-1"}


def _answer(**data: object) -> dict[str, object]:
    """An acknowledgement, in the envelope every API answer comes in."""
    return {"data": data, "meta": {"count": 1, "total": 1, "version": "test"}}


def _client(monkeypatch: pytest.MonkeyPatch, **post: object) -> KaianoApiClient:
    """Patch the API client factory; return a real client with ``post`` faked.

    Only the HTTP call is replaced, so the typed methods build the body from
    the request model and validate the answer, as they do in production.
    """
    client = KaianoApiClient(base_url="https://example.test", api_key="k")
    client.post = MagicMock(**post)  # type: ignore[method-assign]
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(api_trigger.KaianoApiClient, "from_env", factory)
    client.factory = factory
    return client


def test_new_work_is_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        monkeypatch,
        return_value=_answer(accepted=True, message_id="m-1", mode=DEEJAY["mode"]),
    )

    fired = api_trigger.fire("/v1/deejay/runs", parameters=DEEJAY)

    assert fired == api_trigger.Fired(message_id="m-1")
    assert fired.queued
    client.factory.assert_called_once_with(machine_name="watcher-cog")
    client.post.assert_called_once_with("/v1/deejay/runs", DEEJAY)


def test_a_deduplicated_answer_is_not_new_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The steady state: every tick re-asks for a file still being processed."""
    _client(
        monkeypatch,
        return_value=_answer(
            message_id="m-0", deduplicated=True, mode=TRANSCRIPTION["mode"]
        ),
    )

    fired = api_trigger.fire("/v1/transcription/runs", parameters=TRANSCRIPTION)

    assert fired.deduplicated
    assert fired.message_id == "m-0"
    assert not fired.queued


def test_a_deduplicated_answer_may_lack_a_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Between another ask's claim and its enqueue there is no id yet."""
    _client(
        monkeypatch,
        return_value=_answer(deduplicated=True, mode=TRANSCRIPTION["mode"]),
    )

    fired = api_trigger.fire("/v1/transcription/runs", parameters=TRANSCRIPTION)

    assert fired.deduplicated
    assert not fired.queued


def test_a_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _client(
        monkeypatch,
        side_effect=KaianoApiError(502, "dispatch_failed", "/v1/deejay/runs"),
    )

    with pytest.raises(KaianoApiError):
        api_trigger.fire("/v1/deejay/runs", parameters=DEEJAY)


def test_new_work_without_a_message_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 2xx nobody can trace is not evidence the work was queued."""
    _client(monkeypatch, return_value=_answer(accepted=True, mode=DEEJAY["mode"]))

    with pytest.raises(KaianoApiError, match="message id"):
        api_trigger.fire("/v1/deejay/runs", parameters=DEEJAY)


def test_a_body_the_api_would_refuse_is_never_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wcs-transcripts ask names its file; without one it is a 422 unsent."""
    client = _client(monkeypatch)

    with pytest.raises(ValidationError):
        api_trigger.fire(
            "/v1/transcription/runs", parameters={"mode": "wcs-transcripts"}
        )

    client.post.assert_not_called()


def test_a_path_that_is_not_a_run_endpoint_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    with pytest.raises(ValueError, match="not a run endpoint"):
        api_trigger.fire("/v1/ingest", parameters={})

    client.factory.assert_not_called()


@pytest.mark.parametrize("environment", ["development", "local"])
def test_outside_production_nothing_is_called(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """A dev watcher polls production's folders; its trigger must not fire."""
    monkeypatch.setenv("ENVIRONMENT", environment)
    client = _client(
        monkeypatch, return_value=_answer(message_id="m-1", mode=DEEJAY["mode"])
    )

    fired = api_trigger.fire("/v1/deejay/runs", parameters=DEEJAY)

    assert fired.suppressed
    assert not fired.queued
    client.factory.assert_not_called()
