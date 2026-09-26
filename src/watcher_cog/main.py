"""Run the watcher outside Lambda: once, or every minute.

``python -m watcher_cog.main --once`` runs a single tick, which is how to
exercise it locally under ``doppler run``. Without ``--once`` it ticks every
minute forever — the Railway service's start command, kept so the old
deployment keeps watching until the Lambda schedule is switched on and the
service is deleted. The two can overlap safely: the API's dispatch claims
make a second asker a no-op.
"""

from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

#: Seconds between ticks. The Lambda schedule is ``rate(1 minute)``.
INTERVAL_SECONDS = 60


def main(argv: list[str] | None = None) -> None:
    """Run one tick, or tick forever."""
    parser = argparse.ArgumentParser(prog="watcher_cog")
    parser.add_argument("--once", action="store_true", help="run a single tick")
    args = parser.parse_args(argv)

    # Before the handler is imported: it initialises Sentry from the
    # environment at import.
    load_dotenv()
    from mini_app_polis.environment import summary

    from watcher_cog.handler import run_once
    from watcher_cog.logger import log

    # The environment, both gates and the resolved API base URL, in one
    # line — read after a deploy instead of assuming.
    log.info(summary())

    if args.once:
        run_once()
        return

    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001 - logged in run_once; keep ticking
            log.error("tick failed; next tick in %ss", INTERVAL_SECONDS)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
