# watcher-cog pipeline context

watcher-cog is the Drive trigger layer in the MiniAppPolis ecosystem.
It sits between Google Drive and api-kaianolevine-com.

## Where it fits

File appears in watched Drive folder
-> watcher-cog detects change (1-minute poll via Drive API)
-> watcher-cog POSTs the owning cog's runs route on api-kaianolevine-com
   (once per folder change, or once per changed file for a `per_file` watcher)
-> the API enqueues onto that cog's SQS queue
-> the cog's Lambda function runs the job

## What it does not do

watcher-cog does not process files, and it does not write to a queue. It
only detects changed files and asks the API to run the cog that owns them.
All processing logic lives in the target cog.

## Watched folders

Configured in src/watcher_cog/config.py via get_watchers().
Each WatcherConfig maps one Drive folder to one API route.
