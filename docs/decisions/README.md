# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for this
repository. ADRs document significant architectural decisions, the
context around them, and their consequences.

## Format

Each ADR is a markdown file named `ADR-NNN-short-slug.md` where `NNN`
is a zero-padded three-digit sequence number starting at `001`. This
matches the ecosystem-standards DOC-005 specification.

Each ADR uses three sections: **Context** (what forces motivated the
decision), **Decision** (what change is being made), and
**Consequences** (what becomes easier or harder).

## Index

- [ADR-001: Always-on Railway process, not a Prefect flow](./ADR-001-always-on-not-a-flow.md)
- [ADR-002: Raw httpx for Prefect deployment API](./ADR-002-raw-httpx-prefect-trigger.md)
- [ADR-003: Polling cadence and idle-interval escalation](./ADR-003-polling-cadence.md)
