# watcher-cog pipeline context

watcher-cog is the Drive trigger layer in the MiniAppPolis ecosystem.
It sits between Google Drive and api-kaianolevine-com.

## Where it fits

File appears in watched Drive folder
-> watcher-cog lists the folder (a Lambda tick, every minute)
-> watcher-cog POSTs the owning cog's runs route on api-kaianolevine-com
   with every file present (once for the folder, or once per file for a
   `per_file` watcher)
-> the API claims each file and enqueues onto that cog's SQS queue only
   when a claim is new, so the every-minute repeats become one job
-> the cog's Lambda function runs the job

## What it does not do

watcher-cog does not process files, and it does not write to a queue. It
only detects changed files and asks the API to run the cog that owns them.
All processing logic lives in the target cog.

## Watched folders

Configured in src/watcher_cog/config.py via get_watchers().
Each WatcherConfig maps one Drive folder to one API route.

## Scheduled jobs

Some work is asked for because it is time, not because a file arrived.
An invocation with `{"job": "<name>"}` asks the API once for that job's
run and checks no folder. The jobs are listed in src/watcher_cog/jobs.py
(JOBS); each has its own EventBridge schedule, declared in
mini-app-polis/infra. An unknown job name fails the invocation.

What the job's run then does, and whether it writes anything, is the
receiving cog's to decide: `library-backfill` asks deejay-cog for a
library-backfill run (its nightly library job), and `library-reconcile`
for a library-reconcile run; each step does nothing unless its own mode,
a feature flag deejay-cog reads, turns it on.
