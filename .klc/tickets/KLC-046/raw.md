---
ticket: KLC-046
kind_hint: feature
created: 2026-06-25T06:58:00Z
---
Phase 6.2 autonomous runner: a klc run command that drives a ticket through the state machine — read state, if work dispatch the phase agent with the resolved model reusing the KLC-042 build orchestrator, run the phase-completion gates, then apply the KLC-045 gate-policy to auto-ack clean conditional gates or pause and notify. Guardrails: a budget ceiling, a cap on consecutive auto-transitions, outward-facing or irreversible transitions (integrate merge, any remote push) always pause, and any risk gate forces a pause. Notifications on each pause. This is the autonomy capstone built on the trusted gates of phases 0 through 5.
