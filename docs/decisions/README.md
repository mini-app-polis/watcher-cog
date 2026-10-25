# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for this
repository. ADRs document significant architectural decisions, the
context around them, and their consequences.

## Format

Each ADR is a markdown file named `ADR-NNNN-short-slug.md` where `NNNN`
is a zero-padded four-digit sequence number starting at `0001`. This
matches the ecosystem-standards DOC-005 specification. An ADR in another
repository is cited with that repository's name first, as in
`ecosystem-standards ADR-0009`.

Each ADR uses three sections: **Context** (what forces motivated the
decision), **Decision** (what change is being made), and
**Consequences** (what becomes easier or harder).

## Index

- [ADR-0001: Always-on Railway process, not a Prefect flow](./ADR-0001-always-on-not-a-flow.md) — superseded by ADR-0005
- [ADR-0002: Raw httpx for Prefect deployment API](./ADR-0002-raw-httpx-prefect-trigger.md) — superseded by ADR-0004
- [ADR-0003: Polling cadence and idle-interval escalation](./ADR-0003-polling-cadence.md) — superseded by ADR-0005
- [ADR-0004: Trigger through the API only, and per file for transcription-cog](./ADR-0004-api-trigger-per-file.md) — partially superseded by ADR-0005
- [ADR-0005: A stateless watcher on a schedule, with the API deduplicating](./ADR-0005-stateless-scheduled-watcher.md)
