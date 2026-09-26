# ADR-005: A stateless watcher on a schedule, with the API deduplicating

Date: 2026-09-26

## Status

Accepted

Supersedes [ADR-001](./ADR-001-always-on-not-a-flow.md) and
[ADR-003](./ADR-003-polling-cadence.md).

## Context

watcher-cog was the last always-on process in the fleet: an asyncio loop
on Railway that remembered which files it had seen and fired on the
difference. Every other cog had moved to a queue and a Lambda function.

The memory was the problem. A restart had to decide whether a folder's
contents were a backlog to fire or a baseline to ignore, and from inside
the process the two were identical — ADR-004 and the baseline warnings
existed to paper over that. And a job that failed every retry sat in a
dead-letter queue until someone redrove it, because nothing would ever
ask for the file again.

Push notifications from Drive were considered and rejected. Neither
`changes.watch` nor the Workspace Events API guarantees delivery, so
either needs a polling backstop anyway, plus a channel or subscription to
renew and a second cloud's credentials for the Events API. The question
the watcher answers — is there unprocessed work in this folder — is a
state check, and polling the state is sturdier than any event mechanism:
a missed check is caught by the next one.

## Decision

- watcher-cog is a Lambda function invoked by EventBridge every minute,
  with a reservation of one, no async retries, and a 50-second timeout.
  Its infrastructure is `module "watcher"` in mini-app-polis/infra.
- It remembers nothing. Every tick lists every folder and asks the API
  for every file present: a sweep watcher names them all in
  `drive_files`, a `per_file` watcher asks once per file.
- The API deduplicates, with a claim per file in `dispatch_claims`. A
  drained inbox claims by file id, and a file still present after six
  hours is dispatched again, up to three times, then reported once and
  left alone. A folder whose files are edited in place (live-history)
  claims by file id and modifiedTime, once per version, forever.
- Deduplication lives in the API rather than here, because the API
  already holds the fleet's state and is the only producer: the watcher
  stays list-and-POST, and its key can ask for work but not enqueue it.
- A repeat is answered with the message id of the job that has the file,
  so a report can be traced to the run.
- Failure reporting moves from this process to the platform. A tick
  checks every folder, then raises if any failed; the function's error
  alarm notifies once on the change into ALARM. Healthchecks, pinged only
  after a clean tick, catches the one failure nothing else can see: a
  schedule that stopped invoking the function.

## Consequences

- No baseline, no restart logic, no seen-set. A restart is not an event.
- The dead-letter queue no longer needs redriving: the file still in its
  folder is the retry. ADR-004's "redriving the dead-letter queue is the
  recovery" no longer holds.
- A file whose cog completes the work but fails to move it is processed
  again after six hours. Each cog's side effects must tolerate that, or
  move the file as early as it safely can.
- The claim window must outlast a cog's longest possible job
  (max receive count × visibility timeout). The infra repository checks
  this at plan time.
- The first tick asks for everything present, which includes all of
  live-history's sheets: one ingest sweep at cutover.
- The Railway service and its always-on process go away. Until they do,
  `python -m watcher_cog.main` runs the same stateless tick in a loop, and
  running it beside the Lambda is safe.
