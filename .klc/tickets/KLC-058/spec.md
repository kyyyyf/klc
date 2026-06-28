---
ticket: KLC-058
kind: feature
authority: agent
track: XS
risk_tags: [user-facing, data]
---

## Goals
Add a heartbeat mechanism that refreshes `holder.heartbeat_at` in meta.json while a holder is active, and a `klc steal <KEY>` command that takes over the holder slot only when the TTL has expired, printing a warning before doing so.

## Acceptance Criteria
- [ ] AC-1: `klc steal <KEY>` fails with a non-zero exit code and a clear error message when the ticket has an active holder whose `heartbeat_at` (or `holder.since` if heartbeat is absent) is within the configured TTL (default 30 minutes); it succeeds and overwrites the holder when the timestamp is older than the TTL.
- [ ] AC-2: A `heartbeat_holder(ticket)` function in `lifecycle.py` updates `meta.json:holder.heartbeat_at` to the current UTC timestamp without changing any other field; calling it when no holder is present raises `ValueError`.

## Affected
lifecycle: `heartbeat_holder`, `steal_holder` functions, src=core/skills/lifecycle.py:95 [!ASSUMPTION if-false=scope-may-expand]
phases/steal: new file `core/phases/steal.py` with `run(argv)` entry point [!ASSUMPTION if-false=scope-may-expand]
scripts/klc: add `"steal"` to `LIFECYCLE_CMDS`, src=scripts/klc:91 [!ASSUMPTION if-false=scope-may-expand]

## Estimate
complexity: 1
uncertainty: 1
risk: 0
manual: 0
total: 2

DISCOVERY_LITE_DONE
