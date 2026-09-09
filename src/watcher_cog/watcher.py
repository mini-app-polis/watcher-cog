"""Core watcher loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from mini_app_polis.pipeline_status import post_run_finding

from watcher_cog import drive_client, heartbeat, prefect_trigger
from watcher_cog.config import WatcherConfig
from watcher_cog.logger import log

#: Reported as the machine name, so the API attributes these to this cog
#: and looks for WATCHER_COG_API_KEY.
REPO = "watcher-cog"

#: Marks these as coming from the watcher loop rather than a flow run.
#: This cog has no Prefect flow of its own — it is a plain asyncio loop —
#: so neither "flow_inline" nor "flow_hook" would be true.
SOURCE = "watcher_loop"


class _TriggerFailed(Exception):
    """Drive answered; Prefect would not take the work.

    Raised only to carry that distinction out to the one handler at the
    bottom of the loop, which otherwise cannot tell a Drive fault from a
    Prefect one and calls both a failed poll. The two need different
    messages because they need different fixes, and because a trigger
    that did not fire means files arrived and no run started — the one
    outcome this cog exists to prevent.
    """


async def _report(
    config: WatcherConfig,
    severity: str,
    text: str,
    *,
    notable: bool = False,
) -> bool:
    """Report one watcher event. Never raises, never blocks the loop.

    Returns whether the message actually landed. The caller needs that:
    an ERROR that was never delivered must not consume the one report
    this cog allows itself per failure cause, or an outage that takes
    down both Drive and the API is completely silent.

    ``post_run_finding`` is synchronous and does network I/O. Called
    directly it would stall every other watcher sharing this event loop
    for the duration of the request, so it goes to a thread — a watcher
    that polls every minute cannot afford to spend ten seconds of that
    inside a notification.
    """
    try:
        result = await asyncio.to_thread(
            post_run_finding,
            config.name,
            severity,  # type: ignore[arg-type]
            text,
            repo=REPO,
            source=SOURCE,
            notable=notable,
        )
    except Exception as exc:  # noqa: BLE001 - reporting must never break polling
        log.error("[%s] report failed: %s", config.name, exc)
        return False
    # sent is the only value that means a human can see this. suppressed
    # (a SUCCESS below the notify threshold) is a decision, not a failure,
    # and counts as landed so it does not hold a suppression slot open.
    return bool(result.sent or result.suppressed)


def _baseline_concern(
    config: WatcherConfig, files: list, started_at: datetime
) -> str | None:
    """What, if anything, is worrying about this folder's opening state.

    Two folder shapes, two questions.

    A drained inbox should be empty when nothing is pending, so anything
    in it at startup is work that will now never trigger — worth saying
    however old it is.

    A folder that is never drained is always full, so its size says
    nothing at all. What still says something is a file modified shortly
    before this process started: plausibly during the downtime, and
    therefore plausibly a change that will never fire. Everything older
    than that was already handled by the run that preceded the restart.
    """
    if not files:
        return None

    if config.drained_by_downstream:
        return (
            f"Baselined {len(files)} pending file(s) in {config.folder_id} "
            "on start — these will not trigger. Anything that arrived "
            "while this cog was down is among them."
        )

    cutoff = started_at - timedelta(minutes=config.baseline_recent_change_min)
    recent = []
    for f in files:
        mod = getattr(f, "modified_time", None)
        if not mod:
            continue
        try:
            ts = datetime.fromisoformat(str(mod).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if ts >= cutoff:
            recent.append(getattr(f, "name", None) or getattr(f, "id", "?"))

    if not recent:
        return None
    named = ", ".join(str(n) for n in recent[:3])
    more = f", +{len(recent) - 3} more" if len(recent) > 3 else ""
    return (
        f"Baselined {len(recent)} file(s) in {config.folder_id} modified in "
        f"the {config.baseline_recent_change_min} minutes before start — "
        f"those changes will not trigger: {named}{more}"
    )


async def run_watcher(config: WatcherConfig) -> None:
    """Run a single folder watcher loop forever."""
    # Track file_id -> modified_time string so we detect both new files
    # and modifications to existing files.
    seen: dict[str, str | None] = {}
    initialized = False
    # Length of the current run of consecutive poll failures. Used to
    # report the first failure and the recovery, and nothing in between:
    # a Drive outage on a one-minute poll would otherwise post sixty
    # identical messages an hour, which is how a channel gets muted right
    # before it matters.
    error_streak = 0
    #: Every cause already reported during the current streak. A set
    #: rather than the last-seen value: with one slot, a streak that
    #: alternated between two causes counted every single cycle as "a new
    #: cause" and reported on all of them — one message a minute for the
    #: length of the outage, which is the storm this exists to prevent.
    #: Cleared on recovery, so the next outage speaks again.
    reported_kinds: set[str] = set()
    #: When this loop started, which is the only reference point a
    #: restart has for "modified during the downtime" — nothing is
    #: persisted across restarts.
    started_at = datetime.now(UTC)

    while True:
        current_interval = config.interval_min
        try:
            if config.activity_signal == "file_mod_time" and config.activity_file_id:
                mod_time = drive_client.get_file_modified_time(config.activity_file_id)
                if mod_time is not None:
                    age_min = (datetime.now(UTC) - mod_time).total_seconds() / 60
                    if age_min > config.activity_threshold_min:
                        current_interval = config.idle_interval_min

            files = drive_client.list_folder(config.folder_id)
            current: dict[str, str | None] = {
                file.id: file.modified_time for file in files
            }

            if not initialized:
                seen = current
                initialized = True
                log.info("[%s] initialised with %s file(s)", config.name, len(seen))
                concern = _baseline_concern(config, files, started_at)
                if concern:
                    # Whatever is in the folder now is the baseline and
                    # will never fire a trigger. That is correct on a
                    # first-ever start and a swallowed backlog on a
                    # restart, and from in here the two are identical —
                    # so the folder's own shape has to decide whether it
                    # is worth saying.
                    await _report(config, "WARN", concern, notable=True)
            else:
                new_files = [fid for fid in current if fid not in seen]
                modified_files = [
                    fid
                    for fid, mtime in current.items()
                    if fid in seen and mtime != seen[fid]
                ]

                if new_files or modified_files:
                    try:
                        await prefect_trigger.fire(
                            config.deployment_id,
                            parameters=config.parameters,
                        )
                    except Exception as exc:
                        raise _TriggerFailed(f"{type(exc).__name__}: {exc}") from exc
                    seen = current
                    log.info(
                        "[%s] %s new, %s modified — trigger fired",
                        config.name,
                        len(new_files),
                        len(modified_files),
                    )
                    # The event worth hearing about. A poll that changes
                    # nothing is the steady state and stays silent; a
                    # poll that fires a downstream deployment is the
                    # moment work entered the pipeline, and it is the
                    # only record of that moment outside Prefect.
                    await _report(
                        config,
                        "SUCCESS",
                        (
                            f"Triggered {config.deployment_id}: "
                            f"{len(new_files)} new, "
                            f"{len(modified_files)} modified"
                        ),
                        notable=True,
                    )
                else:
                    seen = current
                    log.debug("[%s] no changes", config.name)

            if error_streak:
                recovered_after = error_streak
                # Named, not assumed. A streak of trigger failures used to
                # end with "Polling recovered", which is the wrong
                # subsystem — the same confusion the trigger/poll split
                # was written to remove.
                what = " and ".join(sorted(reported_kinds)) or "polling"
                error_streak = 0
                reported_kinds.clear()
                await _report(
                    config,
                    "SUCCESS",
                    f"{what} recovered after {recovered_after} failed cycle(s)",
                    notable=True,
                )

            # Deliberately not in a `finally`. Healthchecks fires on
            # absence, which is only a useful alarm if the ping means
            # "this cycle read the folder and acted on it". Pinging from
            # a `finally` meant it also meant "this cycle raised and did
            # nothing", so expired credentials could keep the check green
            # indefinitely while the folder went unwatched.
            await heartbeat.ping()

        except Exception as exc:
            kind = "trigger" if isinstance(exc, _TriggerFailed) else "poll"
            log.error("[%s] %s error: %s", config.name, kind, exc, exc_info=True)

            # Report the first failure of each *cause*, not merely the
            # first failure of a streak. Sixty identical Drive timeouts
            # still produce one message; a trigger that starts failing
            # during a Drive outage is a new fact and gets its own.
            first_of_kind = kind not in reported_kinds
            error_streak += 1

            if first_of_kind:
                if kind == "trigger":
                    text = (
                        f"Trigger failed for deployment {config.deployment_id}: "
                        f"{exc}. Drive changes were seen and no run was "
                        "started; the next cycle will retry the same files. "
                        "Further failures of this kind are logged but not "
                        "repeated here."
                    )
                else:
                    text = (
                        f"Poll failed for folder {config.folder_id}: "
                        f"{type(exc).__name__}: {exc}. "
                        "Further failures of this kind are logged but not "
                        "repeated here."
                    )
                # Only record the cause if the message actually landed. A
                # report that failed leaves the set unchanged, so the next
                # cycle tries again rather than suppressing itself.
                if await _report(config, "ERROR", text):
                    reported_kinds.add(kind)

        await asyncio.sleep(current_interval * 60)
