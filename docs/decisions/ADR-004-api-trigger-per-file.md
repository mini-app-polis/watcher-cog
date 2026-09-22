# ADR-004: Trigger through the API only, and per file for transcription-cog

Date: 2026-09-21

## Status

Accepted

Supersedes [ADR-002](./ADR-002-raw-httpx-prefect-trigger.md).

## Context

watcher-cog started every downstream run by calling Prefect's
`create_flow_run` on a deployment. The fleet has moved off Prefect onto one
SQS queue and one Lambda function per cog (ecosystem-standards ADR-009),
and api-kaianolevine-com is the only thing that writes to a queue.
deejay-cog moved first: its two watchers POST `/v1/deejay/runs` and the API
enqueues. transcription-cog is the last cog watcher triggers, so with it
moved watcher no longer needs Prefect at all.

transcription-cog does not fit the deejay shape. deejay's job is a sweep of
the folder, and one message sweeps whatever is there. A transcript's
extraction alone has taken five minutes, so a sweep of a few files outlives
Lambda's 900-second ceiling. The job has to be one file.

watcher already knows which files changed: it diffs every poll against the
last one. The alternative was for the cog to sweep the folder and ask the
API for one job per file it found. That puts a second producer in the
chain for information watcher already holds.

## Decision

- Every watcher's target is an API route (`api_path`). `deployment_id`,
  `prefect_trigger.py` and the `prefect` dependency are removed.
- A `per_file` watcher POSTs once per new or modified file and adds
  `drive_file_id` to the body. `wcs-notes` and `voice-notes` are per-file,
  on `/v1/transcription/runs`. The deejay watchers are not.
- A per-file watcher on a drained folder asks for whatever is already in
  the folder when it starts, instead of baselining it. A folder-sweep
  watcher can only warn that those files will not trigger; a per-file
  watcher can name them. Until that fire succeeds the watcher stays
  uninitialised and tries again on the next cycle.
- A per-file fire that fails partway raises without advancing `seen`, so
  the next cycle asks for every changed file again, including the ones
  already queued.

## Consequences

- PIPE-019 passes: no Prefect client and no queue writes.
- Asking twice for one file is expected, after a partial failure or a
  restart. transcription-cog absorbs it: a file run skips a file that is no
  longer in its inbox, and runs one job at a time.
- Nothing sweeps a transcription folder any more. A file whose job fails
  every retry lands in transcription-cog's dead-letter queue and alarms;
  it is not picked up by the next upload, as it was when every trigger
  re-swept the folder. Redriving the dead-letter queue is the recovery.
- A multi-file change is several runs. The watcher's report names every
  message id in its text and carries one as its run id only when there is
  exactly one.
