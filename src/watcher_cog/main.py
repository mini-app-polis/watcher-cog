"""Application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import sentry_sdk
from dotenv import load_dotenv

from watcher_cog.config import get_watchers
from watcher_cog.logger import log
from watcher_cog.watcher import run_watcher


async def _supervise(config) -> None:  # noqa: ANN001 - WatcherConfig, kept loose to avoid a cycle
    """Run one watcher and report the moment it dies.

    ``asyncio.gather`` only hands back an exception once every task has
    finished, and these tasks are infinite loops — so a watcher that
    crashed would have been reported when the *last* one stopped, which
    in practice is never. The process stays up, the other folders keep
    polling, and one folder silently stops being watched.

    Reporting here costs one wrapper and turns that into a message.
    """
    from watcher_cog.watcher import _report

    try:
        await run_watcher(config)
    except BaseException as exc:
        with contextlib.suppress(Exception):
            await _report(
                config,
                "CRITICAL",
                (
                    f"Watcher for {config.folder_id} exited: "
                    f"{type(exc).__name__}: {exc}. This folder is no longer "
                    "being polled and the process is still running."
                ),
                notable=True,
            )
        raise


async def main() -> None:
    """Run all configured watcher tasks."""
    load_dotenv()
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), environment="production")

    watchers = get_watchers()

    if not watchers:
        log.warning("no watchers configured - exiting")
        return

    watcher_names = ", ".join(w.name for w in watchers)
    log.info("starting %s watcher(s): %s", len(watchers), watcher_names)

    tasks = [_supervise(w) for w in watchers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for watcher, result in zip(watchers, results, strict=True):
        if isinstance(result, BaseException):
            log.error(
                "[%s] watcher exited with error: %s",
                watcher.name,
                result,
                exc_info=result,
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
