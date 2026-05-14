# Configuration

All configuration is via environment variables. See .env.example
for the full list with descriptions.

| Variable | Required | Description |
|---|---|---|
| GOOGLE_CREDENTIALS_JSON | Yes | Service account credentials JSON as a string |
| PREFECT_API_KEY | Yes | Prefect Cloud API key |
| PREFECT_API_URL | Yes | Prefect Cloud workspace API URL |
| HEALTHCHECKS_URL_WATCHER | Yes | Healthchecks.io ping URL |
| SENTRY_DSN | Yes | Sentry DSN for error tracking |
| LOG_LEVEL | No | DEBUG, INFO (default), WARNING |
| CSV_SOURCE_FOLDER_ID | Yes | Drive folder ID watched by `dj-sets` |
| NOTES_INPUT_FOLDER_ID | Yes | Drive folder ID watched by `wcs-notes` |
| GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID | Yes | Drive folder ID watched by `voice-notes` — same env-var name the notes-ingest-cog voicenotes sub-pipeline reads, so the Doppler config holds one value for both |

## Watcher config

Watchers are defined in src/watcher_cog/config.py as a list of
WatcherConfig dataclasses. See README.md for full field documentation.

The optional `parameters: dict` field on WatcherConfig is forwarded
as flow-run parameters to `create_flow_run_from_deployment`. Used by
router-style deployments (one Prefect deployment dispatching to
multiple modes via a `mode` parameter) to pin the dispatch mode for
trigger-fired runs. Examples:

- `dj-sets` and `live-history` both point at `deejay-cog/deejay-cog`
  and pass `{"mode": "process-new-files"}` and
  `{"mode": "ingest-live-history"}` respectively.
- `wcs-notes` and `voice-notes` both point at
  `notes-ingest-cog/notes-ingest-cog` (the merged-in-May-2026 deployment
  that hosts the WCS-transcripts and voicenotes pipelines under one
  Railway service) and pass `{"mode": "wcs-transcripts"}` and
  `{"mode": "voicenotes"}` respectively. The notes-ingest-cog router
  has no cron-default mode — every trigger must specify one, and the
  router raises `ValueError` otherwise.
