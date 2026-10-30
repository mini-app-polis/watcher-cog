from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mini_app_polis.api import ApiUnavailable, KaianoApiError

from watcher_cog import watcher
from watcher_cog.api_trigger import Fired
from watcher_cog.config import WatcherConfig


def _file(file_id: str, modified_time: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id, name=f"{file_id}.txt", modified_time=modified_time
    )


def _cfg(**kwargs: object) -> WatcherConfig:
    kwargs.setdefault("parameters", {"mode": "m"})
    return WatcherConfig(name="w", folder_id="folder", api_path="/v1/x/runs", **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A folder, the API, and the run-report channel, all fake."""
    state = SimpleNamespace(
        files=[],
        fire=MagicMock(return_value=Fired(message_id="m-1")),
        report=MagicMock(),
    )
    monkeypatch.setattr(watcher.drive_client, "list_folder", lambda _: state.files)
    monkeypatch.setattr(watcher.api_trigger, "fire", state.fire)
    monkeypatch.setattr(watcher, "post_run_finding", state.report)
    return state


# ── what is asked for ────────────────────────────────────────────────────


def test_an_empty_folder_asks_for_nothing(world: SimpleNamespace) -> None:
    result = watcher.check(_cfg())

    assert result == watcher.Check(watcher="w")
    world.fire.assert_not_called()
    world.report.assert_not_called()


def test_a_sweep_watcher_names_every_file_in_one_ask(world: SimpleNamespace) -> None:
    world.files = [_file("a"), _file("b")]

    watcher.check(_cfg())

    world.fire.assert_called_once_with(
        "/v1/x/runs",
        parameters={"mode": "m", "drive_files": [{"id": "a"}, {"id": "b"}]},
    )


def test_an_in_place_folder_claims_each_version(world: SimpleNamespace) -> None:
    """live-history: the sheet's modifiedTime is what makes it new work."""
    world.files = [_file("s1", "2026-09-26T10:00:00Z")]

    watcher.check(_cfg(drained_by_downstream=False))

    body = world.fire.call_args.kwargs["parameters"]
    assert body["drive_files"] == [{"id": "s1", "revision": "2026-09-26T10:00:00Z"}]


def test_an_in_place_file_without_a_version_is_refused(world: SimpleNamespace) -> None:
    """Sent without one, it would be claimed by presence and re-run forever."""
    world.files = [_file("s1")]

    with pytest.raises(watcher.CheckFailed, match="modifiedTime"):
        watcher.check(_cfg(drained_by_downstream=False))
    world.fire.assert_not_called()


class _RewritingCog:
    """The API's per-version claims, and a cog that tags files in place.

    A new claim runs the job straight away. The job writes every file whose
    tags differ from what it would write, which gives that file a new
    modifiedTime; with ``rewrites_matching`` it writes every file every run.
    """

    def __init__(
        self, files: list[SimpleNamespace], *, rewrites_matching: bool
    ) -> None:
        self.files = files
        self.rewrites_matching = rewrites_matching
        self.claims: set[tuple[str, str]] = set()
        self.tagged: set[str] = set()
        self.jobs = 0
        self.clock = 0

    def fire(self, path: str, parameters: dict[str, object]) -> Fired:
        refs = parameters["drive_files"]
        assert isinstance(refs, list)
        new = {(r["id"], r["revision"]) for r in refs} - self.claims
        if not new:
            return Fired(message_id=f"m-{self.jobs}", deduplicated=True)
        self.claims |= new
        self.jobs += 1
        for f in self.files:
            if self.rewrites_matching or f.id not in self.tagged:
                self.tagged.add(f.id)
                self.clock += 1
                f.modified_time = f"2026-10-30T12:00:{self.clock:02d}Z"
        return Fired(message_id=f"m-{self.jobs}")


def _queued_per_tick(world: SimpleNamespace, cog: _RewritingCog) -> list[int]:
    world.files = cog.files
    world.fire.side_effect = cog.fire
    cfg = _cfg(drained_by_downstream=False, parameters={"mode": "retag-music"})
    return [len(watcher.check(cfg).queued) for _ in range(5)]


def test_a_run_that_rewrites_its_files_settles(world: SimpleNamespace) -> None:
    """music-uploads: the write is one more version, then nothing changes."""
    files = [_file("a", "2026-10-30T11:00:00Z"), _file("b", "2026-10-30T11:00:00Z")]
    cog = _RewritingCog(files, rewrites_matching=False)

    assert _queued_per_tick(world, cog) == [1, 1, 0, 0, 0]
    assert cog.jobs == 2


def test_a_run_that_always_rewrites_would_never_settle(
    world: SimpleNamespace,
) -> None:
    """Per-version claims alone do not end it: the cog must skip a file whose
    tags already match."""
    files = [_file("a", "2026-10-30T11:00:00Z")]
    cog = _RewritingCog(files, rewrites_matching=True)

    assert _queued_per_tick(world, cog) == [1, 1, 1, 1, 1]


def test_a_per_file_watcher_asks_once_per_file(world: SimpleNamespace) -> None:
    world.files = [_file("a"), _file("b")]

    watcher.check(_cfg(per_file=True))

    assert [c.kwargs["parameters"] for c in world.fire.call_args_list] == [
        {"mode": "m", "drive_file_id": "a"},
        {"mode": "m", "drive_file_id": "b"},
    ]


def test_a_large_folder_is_split_to_the_apis_limit(world: SimpleNamespace) -> None:
    world.files = [_file(str(i)) for i in range(watcher.MAX_FILES_PER_REQUEST + 1)]

    watcher.check(_cfg())

    sizes = [
        len(c.kwargs["parameters"]["drive_files"]) for c in world.fire.call_args_list
    ]
    assert sizes == [watcher.MAX_FILES_PER_REQUEST, 1]


def test_per_file_needs_a_drained_folder() -> None:
    with pytest.raises(ValueError, match="drained"):
        _cfg(per_file=True, drained_by_downstream=False)


# ── what is said ─────────────────────────────────────────────────────────


def test_new_work_is_reported_under_its_message_id(world: SimpleNamespace) -> None:
    world.files = [_file("a")]

    result = watcher.check(_cfg(per_file=True))

    assert result.queued == ["m-1"]
    world.report.assert_called_once()
    assert world.report.call_args.args[1] == "SUCCESS"
    assert world.report.call_args.kwargs["run_id"] == "m-1"
    assert world.report.call_args.kwargs["notable"] is True


def test_several_jobs_are_named_in_the_text(world: SimpleNamespace) -> None:
    world.files = [_file("a"), _file("b")]
    world.fire.side_effect = [Fired(message_id="m-1"), Fired(message_id="m-2")]

    watcher.check(_cfg(per_file=True))

    assert world.report.call_args.kwargs["run_id"] is None
    assert "m-1, m-2" in world.report.call_args.args[2]


def test_files_already_claimed_are_silent(world: SimpleNamespace) -> None:
    """The steady state while a file is processed: a repeat every minute."""
    world.files = [_file("a")]
    world.fire.return_value = Fired(message_id="m-0", deduplicated=True)

    result = watcher.check(_cfg(per_file=True))

    assert result.deduplicated == 1
    assert result.queued == []
    world.report.assert_not_called()


def test_suppressed_asks_are_silent(world: SimpleNamespace) -> None:
    """A development tick would otherwise report every file, every minute."""
    world.files = [_file("a")]
    world.fire.return_value = Fired(suppressed=True)

    result = watcher.check(_cfg(per_file=True))

    assert result.suppressed == 1
    world.report.assert_not_called()


def test_a_report_that_fails_does_not_fail_the_check(world: SimpleNamespace) -> None:
    world.files = [_file("a")]
    world.report.side_effect = RuntimeError("discord down")

    assert watcher.check(_cfg(per_file=True)).queued == ["m-1"]


# ── failure ──────────────────────────────────────────────────────────────


def test_one_refused_file_does_not_hold_back_the_rest(world: SimpleNamespace) -> None:
    world.files = [_file("a"), _file("b")]
    world.fire.side_effect = [RuntimeError("502"), Fired(message_id="m-2")]

    with pytest.raises(watcher.CheckFailed, match="1 ask"):
        watcher.check(_cfg(per_file=True))

    assert world.fire.call_count == 2
    world.report.assert_called_once()


def test_a_drive_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: str) -> list:
        raise RuntimeError("drive down")

    monkeypatch.setattr(watcher.drive_client, "list_folder", broken)

    with pytest.raises(RuntimeError, match="drive down"):
        watcher.check(_cfg())


def test_an_unreachable_api_is_its_own_failure(world: SimpleNamespace) -> None:
    world.files = [_file("a")]
    world.fire.side_effect = ApiUnavailable(404, "Application not found", "/v1/x/runs")

    with pytest.raises(watcher.ApiUnreachable):
        watcher.check(_cfg(per_file=True))


def test_a_refusal_alongside_an_outage_is_a_plain_failure(
    world: SimpleNamespace,
) -> None:
    world.files = [_file("a"), _file("b")]
    world.fire.side_effect = [
        ApiUnavailable(503, "unavailable", "/v1/x/runs"),
        KaianoApiError(404, "no route", "/v1/x/runs"),
    ]

    with pytest.raises(watcher.CheckFailed) as excinfo:
        watcher.check(_cfg(per_file=True))
    assert not isinstance(excinfo.value, watcher.ApiUnreachable)


# ── the deadline ─────────────────────────────────────────────────────────


def test_no_ask_starts_after_the_deadline(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asks not made are a failure: the next tick makes them, but it shows."""
    world.files = [_file("a"), _file("b"), _file("c")]
    clock = iter([0.0, 5.0, 11.0])
    monkeypatch.setattr(watcher.time, "monotonic", lambda: next(clock))

    with pytest.raises(watcher.CheckFailed, match="out of time: 1 of 3 ask"):
        watcher.check(_cfg(per_file=True), deadline=10.0)

    assert [
        c.kwargs["parameters"]["drive_file_id"] for c in world.fire.call_args_list
    ] == [
        "a",
        "b",
    ]


def test_without_a_deadline_every_ask_is_made(world: SimpleNamespace) -> None:
    world.files = [_file("a"), _file("b")]

    watcher.check(_cfg(per_file=True))

    assert world.fire.call_count == 2
