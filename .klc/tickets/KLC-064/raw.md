---
ticket: KLC-064
kind_hint: feature
created: 2026-07-16T08:56:51Z
---
Wire heartbeat_holder into long-running phases so the TTL steal-safety actually protects active holders. Today nothing calls heartbeat_holder in production -> staleness is always measured from since (acquire time), so a legitimately-active holder on a phase longer than HOLDER_TTL_SECONDS (e.g. a long build) becomes stealable while still working -- the heartbeat_at/since fallback that 058 built provides zero real-world protection. Fix: call heartbeat_holder/lifecycle.heartbeat_holder periodically from the long-running phase/agent loop (or on ack/next transitions). Source: fresh-B LOW/follow-up.
