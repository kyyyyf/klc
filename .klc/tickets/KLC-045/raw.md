---
ticket: KLC-045
kind_hint: feature
created: 2026-06-25T06:31:47Z
---
Phase 6.1 gate-policy layer: add a gate field (auto|conditional|decision) to every pick in phases.yml, and a predicate in core/skills/gate_policy.py that for conditional picks evaluates existing signals (phase_completion advisory, scope_delta, sentinels, mutation/budget overruns, review verdict, route_confidence) and returns auto-proceed only when all clean. Decision picks (discovery approve, design pick, manual passed, integrate merged) always pause; auto picks proceed silently. Hook into core/phases/ack.py behind an explicit --auto flag so existing manual behaviour is unchanged.
