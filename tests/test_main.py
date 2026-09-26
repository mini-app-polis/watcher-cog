from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from watcher_cog import handler, main


def test_once_runs_a_single_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    run_once = MagicMock()
    monkeypatch.setattr(handler, "run_once", run_once)

    main.main(["--once"])

    run_once.assert_called_once()


class _Stop(Exception):
    pass


def test_the_loop_keeps_ticking_through_a_failed_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Railway runner until cutover: a bad tick must not end the process."""
    run_once = MagicMock(side_effect=[RuntimeError("drive down"), None])
    monkeypatch.setattr(handler, "run_once", run_once)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise _Stop

    monkeypatch.setattr(main.time, "sleep", sleep)

    with pytest.raises(_Stop):
        main.main([])

    assert run_once.call_count == 2
    assert sleeps == [main.INTERVAL_SECONDS, main.INTERVAL_SECONDS]
