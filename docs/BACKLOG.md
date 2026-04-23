# Backlog

## Migrate prefect_trigger.py to PrefectClient

**Status:** Deferred — no blocker, low priority, do when next in this repo.

**What:** Replace the raw `httpx.AsyncClient().post()` call in `src/watcher_cog/prefect_trigger.py::fire()` with `prefect.client.orchestration.PrefectClient.create_flow_run_from_deployment()`.

**Why:**
- Closes PIPE-001 (deterministic finding on `run_deployment` reference).
- Gives typed responses and schema stability against future Prefect API changes.
- Makes trigger events visible in Prefect Cloud as client-initiated API calls rather than opaque HTTP posts.
- Removes hand-rolled Bearer-token auth header construction; the client handles it.

**Why not yet:**
- Current implementation works. Tenacity retries are fine. No active failure mode.
- Adds `prefect` to watcher-cog's runtime dependency tree, pulling in the Prefect SDK. Modest cost but worth noting.

**Non-goals:**
- This is NOT a step toward making watcher-cog a Prefect flow. Watcher-cog stays an always-on Railway process. Making it a flow would consume a Hobby-tier deployment slot and reintroduces the "who watches the watcher" problem.

**Touch points when doing this:**
- `src/watcher_cog/prefect_trigger.py` — swap the httpx call for PrefectClient.
- `pyproject.toml` — add `prefect` to dependencies.
- `tests/test_prefect_trigger.py` — update mocks from httpx/respx to PrefectClient.
- Deterministic PIPE-001 finding should clear on next conformance run.
