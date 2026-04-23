# ADR-003: Polling cadence and idle-interval escalation

Date: 2026-03-15

## Status

Accepted

## Context

watcher-cog polls each watched Drive folder at a fixed cadence. The
cadence choice determines the Drive API call budget and the worst-case
time between a file drop and a triggered flow.

Two cadences are in play per watcher:

- `interval_min`: the active poll interval, default 1 minute.
- `idle_interval_min`: the poll interval when the folder is observed
  to be "idle," default 1 minute (same as active by default; larger
  values enable backoff).

Most folders are touched by humans (DJ sets uploaded after a gig, WCS
notes after a class), so activity is bursty — a flurry of uploads, then
hours or days of silence. Polling at full rate during silence is a
waste of Drive API quota, but detecting bursts quickly is the whole
point of the cog.

An "activity signal" mechanism lets each watcher configure a second
Drive file whose modified time represents "recent activity in this
workflow." When that file's mod time is older than
`activity_threshold_min` (default 10), the watcher polls at
`idle_interval_min` instead of `interval_min`.

This is opt-in per watcher via `activity_signal`, `activity_file_id`,
and `activity_threshold_min` in `WatcherConfig`. Watchers that omit
these fields poll at `interval_min` unconditionally.

## Decision

Support two poll cadences per watcher with an optional activity-signal
escalation. Defaults are symmetric (1 minute active, 1 minute idle), so
watchers that don't configure an activity signal poll uniformly and
the mechanism adds no behavior unless opted in.

Worst-case detection latency with defaults is bounded at
`interval_min` + API round-trip, which is roughly 1 minute + a few
hundred milliseconds. Activity-signal watchers have the same worst
case during active periods and `idle_interval_min` during quiet
periods.

## Consequences

- The code supports the two-cadence model whether or not any watcher
  uses it. This is a small complexity tax on every watcher, paid up
  front and shared by all.
- Operators can tune idle behavior per-watcher via env or config
  without redeploying anything structural.
- The "activity signal" concept depends on there being a Drive file
  whose mod time is a reliable proxy for workflow activity. When no
  such file exists, the feature is unused and the cadence is uniform.
- If Drive API quotas become a concern in the future, raising
  `idle_interval_min` for quiet folders is a knob available without
  further code changes.
- Detection latency is bounded by the poll interval. Sub-minute
  latency would require a different mechanism entirely (push
  notifications via Drive Changes API), which is a larger change and
  not currently on the backlog.
