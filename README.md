# watcher-cog

A scheduled function that watches Google Drive folders and asks api-kaianolevine-com to run the cog that owns a folder when files are in it.

---

## Overview

`watcher-cog` is a scheduled AWS Lambda function. Once a minute it lists each watched Drive folder and asks api-kaianolevine-com for the work that is there. The API claims each file it is told about and enqueues onto the owning cog's queue only when a claim is new, so asking for the same file every minute becomes one job.

**What it does:**
- Lists every watched folder once a minute, on an EventBridge schedule
- POSTs the owning cog's runs route with what it finds — the files for a sweep cog, one request per file for a `per_file` cog
- Reports to the runs channel when work was queued, and stays silent when every file was already claimed
- Pings Healthchecks.io after every tick in which every folder was checked

**What it does not do:**
- Remember anything. There is no seen-set and no baseline: every tick asks for everything present, and the API's dispatch claims make the repeats no-ops
- Process files — that is the responsibility of the cog it triggers
- Write to a queue — the API is the fleet's only producer

---

## How a file becomes one job

```
tick (EventBridge, every minute)
└── for each watcher
    ├── drive_client.list_folder(folder)
    ├── api_trigger.fire(api_path, body)   # body names the files
    │     API: claim each file → enqueue if any claim is new → message id
    │     or:  every file already claimed → deduplicated, earlier message id
    └── report to runs if anything was queued
heartbeat.ping()  # only if every folder was checked
```

The API owns the rules (`services/dispatch_claims.py` there):

| Folder | Claim | A file still there later |
|---|---|---|
| Drained inbox (`drained_by_downstream=True`) — the cog moves a file out when done | by file id | Dispatched again after 6 hours, because its job has failed through every retry by then. After 3 dispatches it is given up on and reported once to the errors channel |
| Edited in place (`drained_by_downstream=False`) — live-history's sheets | by file id and modifiedTime | Never re-dispatched; the next edit is a new version and a new job |

The retry is the file sitting in the folder: the dead-letter queue never needs redriving. To retry a file that was given up on, fix or move it and delete its `dispatch_claims` row.

---

## Configuration

Watchers are defined in `src/watcher_cog/config.py`. Each `WatcherConfig` maps one Drive folder to one API route.

| Field | Default | Description |
|---|---|---|
| `name` | required | Label used in logs and reports |
| `folder_id` | required | Google Drive folder ID |
| `api_path` | required | API route that enqueues the work; `parameters` is the body |
| `per_file` | `False` | One request per file, adding `drive_file_id`, rather than one request naming every file in `drive_files`. For a cog whose job is one file |
| `drained_by_downstream` | `True` | Whether the cog moves files out when done. `False` claims each version instead of each file |
| `parameters` | `{}` | The request body, e.g. `{"mode": "process-new-files"}` |

Environment (loaded from SSM Parameter Store at cold start in Lambda; from `.env` locally):

| Variable | Description |
|---|---|
| `GOOGLE_CREDENTIALS_JSON` | Service account credentials JSON, as a string |
| `WATCHER_COG_API_KEY` | This cog's key for api-kaianolevine-com |
| `HEALTHCHECKS_URL_WATCHER` | Healthchecks.io ping URL |
| `CSV_SOURCE_FOLDER_ID`, `NOTES_INPUT_FOLDER_ID`, `GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID` | Watched folders |
| `SENTRY_DSN`, `LOG_LEVEL` | Optional |

---

## Deployment

The function, its schedule, its error alarm and its deploy role are declared in `mini-app-polis/infra` (`module "watcher"`, `modules/scheduled-worker`). This repository owns only the code, and CI deploys it on each release with the shared `lambda-deploy.yml`. The handler is `watcher_cog.handler.lambda_handler`.

`python -m watcher_cog.main` runs the same tick in a loop every minute — the Railway start command, kept only until the Lambda schedule is switched on. `--once` runs a single tick, which is how to exercise it locally under `doppler run`.

---

## Observability

| Signal | Tool | What it covers |
|---|---|---|
| Silence | Healthchecks.io (1-minute period, 5-minute grace) | Nothing is invoking the function, or every tick is failing |
| Failing ticks | CloudWatch alarm `watcher-failing` → email | 3 failed ticks in 5 minutes; notifies once on the way into ALARM and once back out |
| Why it failed | Sentry, and the function's log group | Which folder, which request |
| Work started | Runs channel | One report per tick that queued anything |
| Work that never finished | The file is still in its folder; each cog's dead-letter alarm | Dispatched again after 6 hours; given up on after 3 |

A tick checks every folder even when one fails, then raises, so one broken folder does not stop the others and still marks the tick as failed.

---

## Project structure

```
src/watcher_cog/
├── __init__.py       # loads SSM secrets at import
├── handler.py        # Lambda entry point: one tick over every watcher
├── watcher.py        # one folder: list it, ask for what is there
├── api_trigger.py    # POST the owning cog's runs route
├── drive_client.py   # Google Drive listing
├── heartbeat.py      # Healthchecks.io ping
├── config.py         # WatcherConfig and the watcher list
└── main.py           # local / interim Railway runner
```

---

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check src tests

# Format
uv run ruff format src tests

# Install pre-commit hooks (run once after cloning)
uv run pre-commit install

# Run pre-commit hooks manually against all files
uv run pre-commit run --all-files
```

---

## License

MIT

