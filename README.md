# watcher-cog

A lightweight, always-on service that watches Google Drive folders and fires [Prefect](https://prefect.io) flow runs when new files appear. Built to replace Google Apps Script trigger chains with a single, observable, version-controlled Python service.

---

## Overview

`watcher-cog` is a Railway worker service — no HTTP server, no queue, no framework. It runs a configurable set of folder watchers as concurrent async loops. Each watcher polls a Drive folder on a fixed interval, diffs against its last-known file set, and fires a Prefect deployment run when new files are detected.

**What it does:**
- Polls one or more Google Drive folders on a configurable interval
- Detects new files by diffing against in-memory state
- Fires a Prefect `create_flow_run` API call per watcher when new files appear
- Phones home to a dead man's switch (Healthchecks.io) on every cycle
- Logs structured output on every poll — folder checked, files found, trigger fired or skipped

**What it does not do:**
- Process files — that is the responsibility of the Prefect flow it triggers
- Persist state — seen file IDs are held in memory; a restart re-discovers files from the last poll window
- Serve HTTP — this is a worker process, not an API

**Design principles:**
- Config-driven — adding a new folder-to-flow mapping requires no code changes
- Simple — the entire service is ~300 lines of Python
- Observable — every cycle is logged; external services cover liveness and end-to-end correctness

---

## Architecture

```
main.py
├── Loads watcher config on startup
├── Spawns one asyncio task per watcher
└── asyncio.gather() — all watchers run concurrently

Each watcher loop (while True):
├── drive_client.py  — list files in folder (Google Drive API)
├── Diff against seen_file_ids (in-memory set)
├── prefect_trigger.py  — POST /deployments/{id}/create_flow_run
├── heartbeat.py  — ping HEALTHCHECKS_URL
└── asyncio.sleep(interval_min * 60)
```

State is intentionally in-memory. On restart, each watcher re-fetches the current file list and resets its baseline. Files that arrived during a downtime window will be detected on the first poll after restart. If your downstream flows are idempotent (recommended), this is safe.

---

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management
- A Google Cloud project with the Drive API enabled
- A service account with read access to the watched folders
- A Prefect Cloud account with deployments already created
- A [Healthchecks.io](https://healthchecks.io) account (free tier sufficient)
- [Railway](https://railway.app) (or any always-on host) for deployment

---

## Local development

```bash
# Clone and install dependencies
git clone https://github.com/mini-app-polis/watcher-cog
cd watcher-cog
uv sync

# Copy environment template and fill in values
cp .env.example .env

# Run locally
uv run python src/watcher_cog/main.py
```

---

## Configuration

### Environment variables

All configuration is via environment variables. Copy `.env.example` to `.env` for local development. In production, set these in your host's dashboard (Railway, Fly.io, etc.).

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CREDENTIALS_JSON` | Yes | Service account credentials JSON (as a string, not a file path) |
| `PREFECT_API_KEY` | Yes | Prefect Cloud API key |
| `PREFECT_API_URL` | Yes | Prefect Cloud API URL (e.g. `https://api.prefect.cloud/api/accounts/{id}/workspaces/{id}`) |
| `HEALTHCHECKS_URL` | Yes | Healthchecks.io ping URL for this service |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING` |

### Watcher config

Watchers are defined in `src/watcher_cog/config.py` as a list of `WatcherConfig` dataclasses. Each entry maps one Drive folder to one Prefect deployment.

```python
WATCHERS: list[WatcherConfig] = [
    WatcherConfig(
        name="dj-sets",
        folder_id="1abc...xyz",                    # Google Drive folder ID
        deployment_id="your-prefect-deployment-id", # Prefect deployment UUID
        interval_min=1,                             # Poll every N minutes
    ),
    WatcherConfig(
        name="live-history",
        folder_id="1def...uvw",
        deployment_id="another-prefect-deployment-id",
        interval_min=1,
        idle_interval_min=30,                       # Back off when no activity signal
        activity_signal="file_mod_time",            # "none" | "file_mod_time"
        activity_file_id="1ghi...rst",              # File to check mod time against
        activity_threshold_min=10,                  # Minutes before considered idle
    ),
]
```

**`WatcherConfig` fields:**

| Field | Default | Description |
|---|---|---|
| `name` | required | Human-readable label used in logs |
| `folder_id` | required | Google Drive folder ID to watch |
| `deployment_id` | required | Prefect deployment UUID to trigger |
| `interval_min` | `1` | Poll interval when active |
| `idle_interval_min` | same as `interval_min` | Poll interval when idle (only used with activity signal) |
| `activity_signal` | `"none"` | `"none"` for flat polling, `"file_mod_time"` for two-mode |
| `activity_file_id` | `None` | Drive file ID to check modification time against |
| `activity_threshold_min` | `10` | Minutes since last modification before switching to idle interval |

**Adding a new watcher** is a single `WatcherConfig` entry in `config.py` — no other code changes required.

---

## Activity signals

Most watchers run on a flat interval (`activity_signal: "none"`). The `"file_mod_time"` signal exists for use cases where a known file is written to continuously during an active session (e.g. a DJ application writing a live history file). When the file's modification time is within `activity_threshold_min` minutes, the watcher uses `interval_min`. When it hasn't been touched recently, it backs off to `idle_interval_min`.

This reduces unnecessary trigger calls when the source application is not running, while maintaining fast response when it is.

---

## Deployment

### Railway

1. Create a new Railway project (or add a service to an existing project)
2. Connect your GitHub repo
3. Set all environment variables in the Railway dashboard
4. Railway will deploy automatically on push to `main`

The service has no `PORT` — Railway detects this and runs it as a worker. No `Procfile` or special config needed beyond the environment variables.

### Other hosts

Any host that can run a persistent Python process works. The service has no web server and no port binding. Run it with:

```bash
uv run python src/watcher_cog/main.py
```

---

## Post-deploy setup

Two pieces of configuration live outside the codebase. Both are required for full observability. Neither can be automated — they require manual setup in external dashboards.

### 1. Healthchecks.io — process heartbeat

The watcher pings Healthchecks.io on every poll cycle. If it goes silent, you get an email alert.

**Setup:**
1. Create a free account at [healthchecks.io](https://healthchecks.io)
2. Create a new check with these settings:
   - **Name:** `watcher-cog` (or your preferred label)
   - **Period:** 1 minute
   - **Grace time:** 5 minutes
3. Copy the ping URL (format: `https://hc-ping.com/your-uuid`)
4. Set `HEALTHCHECKS_URL=<ping url>` in your environment

**What this catches:** the watcher process dying, hanging, or Railway failing to restart it within the grace window.

**Why not in code:** The ping URL is the credential on the free tier. It belongs in env vars alongside your other secrets, not hardcoded.

### 2. Prefect Cloud — end-to-end trigger alert

A running watcher process is a necessary but not sufficient condition for correct operation — it also needs to be successfully firing triggers. Prefect's built-in automations catch cases where the watcher runs but triggers fail silently.

**Setup:**

For each deployment that this service triggers, create a Prefect automation:

1. In Prefect Cloud, go to **Automations → New Automation**
2. **Trigger:** Flow run state — no `Completed` run within your expected window (e.g. 2 hours for an hourly processor, 24 hours for a daily one)
3. **Action:** Send notification (email, Slack, PagerDuty — whatever you use)
4. Repeat for each watched deployment

**What this catches:** the watcher running but failing to fire triggers, Prefect API errors, downstream flow failures, and any gap in end-to-end processing.

**Why not in code:** Prefect automation config can be codified via `prefect.yaml` but the UI is sufficient for this use case. If you need to recreate these after losing access to your Prefect workspace, the above steps take under 5 minutes per deployment.

---

## Observability

| Layer | Tool | What it covers |
|---|---|---|
| Process liveness | Healthchecks.io | Is the watcher process running and looping? |
| End-to-end correctness | Prefect Cloud automations | Are triggers firing and flows completing? |
| Crash recovery | Railway auto-restart | Does the process come back after an unhandled exception? |
| Per-cycle detail | Structured logs (Railway log viewer) | What happened on each poll — useful for debugging |

---

## Project structure

```
watcher-cog/
├── src/
│   └── watcher_cog/
│       ├── main.py            # Entry point — loads config, starts watcher tasks
│       ├── config.py          # WatcherConfig dataclass + WATCHERS list
│       ├── watcher.py         # Core watcher loop logic
│       ├── drive_client.py    # Google Drive API wrapper
│       ├── prefect_trigger.py # Prefect create_flow_run API call
│       └── heartbeat.py       # Healthchecks.io ping
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
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

