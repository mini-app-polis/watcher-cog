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

## Watcher config

Watchers are defined in src/watcher_cog/config.py as a list of
WatcherConfig dataclasses. See README.md for full field documentation.
