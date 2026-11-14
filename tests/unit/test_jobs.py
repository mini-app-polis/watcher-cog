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
    assert jobs.run_job("library-backfill") == {"message_id": "m-1"}
    fire.assert_called_once_with(
        "/v1/deejay/runs", parameters={"mode": "library-backfill"}
    )


def test_the_library_reconcile_job_asks_deejay_for_a_reconcile_run(
    fire: MagicMock,
) -> None:
    assert jobs.run_job("library-reconcile") == {"message_id": "m-1"}
    fire.assert_called_once_with(
        "/v1/deejay/runs", parameters={"mode": "library-reconcile"}
    )


def test_the_new_music_sweep_asks_deejay_for_an_intake_run_naming_no_file(
    fire: MagicMock,
) -> None:
    assert jobs.run_job("new-music-sweep") == {"message_id": "m-1"}
    fire.assert_called_once_with("/v1/deejay/runs", parameters={"mode": "new-music"})


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


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    check = MagicMock(return_value={"quiet": 2, "closed": 2})
    monkeypatch.setattr(jobs.api_trigger, "check", check)
    return check


def test_the_quiet_sweep_job_asks_the_api_to_close_quiet_faults(
    check: MagicMock, fire: MagicMock
) -> None:
    assert jobs.run_job("api-fault-quiet-sweep") == {
        "result": {"quiet": 2, "closed": 2}
    }
    check.assert_called_once_with("/v1/signals/api-faults/quiet-sweep", parameters={})
    fire.assert_not_called()


def test_an_event_naming_a_check_job_returns_what_it_did(
    monkeypatch: pytest.MonkeyPatch, check: MagicMock
) -> None:
    monkeypatch.setattr(handler, "load_secrets", MagicMock())
    result = handler.lambda_handler({"job": "api-fault-quiet-sweep"}, None)
    assert result == {
        "job": "api-fault-quiet-sweep",
        "result": {"quiet": 2, "closed": 2},
    }


def test_every_check_job_names_a_check_endpoint() -> None:
    for job in jobs.JOBS.values():
        if job.kind == "check":
            assert job.api_path in api_trigger.CHECK_ENDPOINTS


def test_a_check_outside_production_calls_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_trigger, "current_environment", lambda: api_trigger.Environment.DEVELOPMENT
    )
    from_env = MagicMock()
    monkeypatch.setattr(api_trigger.KaianoApiClient, "from_env", from_env)
    assert api_trigger.check("/v1/signals/api-faults/quiet-sweep") == {}
    from_env.assert_not_called()


def test_a_check_returns_the_apis_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_trigger, "current_environment", lambda: api_trigger.Environment.PRODUCTION
    )
    client = MagicMock()
    client.post.return_value = {"data": {"quiet": 1, "closed": 1}, "meta": {}}
    monkeypatch.setattr(
        api_trigger.KaianoApiClient, "from_env", MagicMock(return_value=client)
    )
    assert api_trigger.check("/v1/signals/api-faults/quiet-sweep") == {
        "quiet": 1,
        "closed": 1,
    }
    client.post.assert_called_once_with("/v1/signals/api-faults/quiet-sweep", {})


def test_an_unknown_check_path_is_refused() -> None:
    with pytest.raises(ValueError, match="not a check endpoint"):
        api_trigger.check("/v1/deejay/runs")
