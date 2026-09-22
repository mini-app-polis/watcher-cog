# Configuration

All configuration is via environment variables. See .env.example
for the full list with descriptions.

| Variable | Required | Description |
|---|---|---|
| GOOGLE_CREDENTIALS_JSON | Yes | Service account credentials JSON as a string |
| HEALTHCHECKS_URL_WATCHER | Yes | Healthchecks.io ping URL |
| SENTRY_DSN | Yes | Sentry DSN for error tracking |
| LOG_LEVEL | No | DEBUG, INFO (default), WARNING |
| CSV_SOURCE_FOLDER_ID | Yes | Drive folder ID watched by `dj-sets` |
| NOTES_INPUT_FOLDER_ID | Yes | Drive folder ID watched by `wcs-notes` |
| GOOGLE_DRIVE_VOICE_INBOX_FOLDER_ID | Yes | Drive folder ID watched by `voice-notes` — same env-var name the transcription-cog voicenotes sub-pipeline reads, so the Doppler config holds one value for both |

## Watcher config

Watchers are defined in src/watcher_cog/config.py as a list of
WatcherConfig dataclasses. See README.md for full field documentation.

Each watcher's target is an API route, `api_path`. Watcher POSTs
`parameters` to it as `watcher-cog` (`WATCHER_COG_API_KEY`), and the API
enqueues onto the owning cog's queue. `parameters` pins the cog's `mode`.
A `per_file` watcher posts once per changed file and adds `drive_file_id`
to the body; the others post once for the folder. Examples:

- `dj-sets` and `live-history` POST `/v1/deejay/runs` once per change,
  with `{"mode": "process-new-files"}` and `{"mode": "ingest-live-history"}`
  respectively. deejay-cog's job is a sweep of the folder.
- `wcs-notes` and `voice-notes` POST `/v1/transcription/runs` once per
  changed file, with `{"mode": "wcs-transcripts", "drive_file_id": ...}`
  and `{"mode": "voicenotes", "drive_file_id": ...}` respectively.
  transcription-cog's job is one file, because a sweep of its folder does
  not fit in one Lambda invocation. Because they can name files, these two
  also ask for whatever is already in their folder when watcher starts,
  rather than baselining it. See
  [ADR-004](decisions/ADR-004-api-trigger-per-file.md).

Both cogs used to be triggered as Prefect deployments. Prefect is retired,
and no watcher can reach it.
