from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from watcher_cog import api_trigger, handler, jobs


@pytest.fixture
def fire(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fire = MagicMock(return_value=api_trigger.Fired(message_id="m-1"))
    monkeypatch.setattr(jobs.api_trigger, "fire", fire)
    return fire


def test_the_library_backfill_job_asks_deejay_for_a_backfill_run(
    fire: MagicMock,
) -> None:
    assert jobs.run_job("library-backfill") == "m-1"
    fire.assert_called_once_with(
        "/v1/deejay/runs", parameters={"mode": "library-backfill"}
    )


def test_a_job_sends_no_drive_files(fire: MagicMock) -> None:
    jobs.run_job("library-backfill")
    assert "drive_files" not in fire.call_args.kwargs["parameters"]


def test_an_unknown_job_fails_loudly_and_asks_nothing(fire: MagicMock) -> None:
    with pytest.raises(ValueError, match="no job named 'nope'"):
        jobs.run_job("nope")
    fire.assert_not_called()


def test_a_failed_ask_fails_the_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jobs.api_trigger, "fire", MagicMock(side_effect=RuntimeError("api down"))
    )
    with pytest.raises(RuntimeError):
        jobs.run_job("library-backfill")


def test_an_event_naming_a_job_runs_it_and_checks_no_folder(
    monkeypatch: pytest.MonkeyPatch, fire: MagicMock
) -> None:
    monkeypatch.setattr(handler, "load_secrets", MagicMock())
    check = MagicMock()
    ping = MagicMock()
    monkeypatch.setattr(handler.watcher, "check", check)
    monkeypatch.setattr(handler.heartbeat, "ping", ping)

    result = handler.lambda_handler({"job": "library-backfill"}, None)

    assert result == {"job": "library-backfill", "message_id": "m-1"}
    check.assert_not_called()
    ping.assert_not_called()
