---
ticket: KLC-050
kind: options-lite
authority: human
---

# KLC-050 — Approaches

- Option A: fix each of the four judgment-side weaknesses at its source (broaden lint
  patterns, placeholder-aware `recorded_pick`, strict model-guard reject path, unify the
  step parser + retire stale templates) with one regression test per item.
- Option B: fix only the parser duplication now and leave lint/pick hardening to
  prompt-discipline. Smaller, but leaves the trivially-evadable gates the review flagged.

Picked: Option A — close all four findings at the source with regression tests; each change
is small and additive. (DECISION D-001)
