# Configuration

All configuration is via environment variables, supplied by Doppler
(`doppler run` locally, SSM in Lambda); nothing reads a `.env` file. Every
variable, what it does and whether it is required, is in
[`.env.example`](../.env.example).

## Watcher config

Watchers are defined in src/watcher_cog/config.py as a list of
WatcherConfig dataclasses. See README.md for full field documentation.

Each watcher's target is an API route, `api_path`. Every tick, watcher
POSTs `parameters` to it as `watcher-cog` (`WATCHER_COG_API_KEY`) with the
files currently in the folder, and the API claims each file and enqueues
onto the owning cog's queue only when a claim is new. `parameters` pins the
cog's `mode`. Examples:

- `dj-sets` and `live-history` POST `/v1/deejay/runs` once per tick, naming
  every file in `drive_files`. deejay-cog's job is a sweep of the folder.
  live-history's sheets never leave their folder, so each is named with its
  modifiedTime and claimed once per version (`drained_by_downstream=False`).
- `wcs-notes` and `voice-notes` POST `/v1/transcription/runs` once per file,
  with `drive_file_id`. transcription-cog's job is one file, because a sweep
  of its folder does not fit in one Lambda invocation.

See [ADR-005](decisions/ADR-005-stateless-scheduled-watcher.md).
