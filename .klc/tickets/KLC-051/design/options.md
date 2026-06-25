---
ticket: KLC-051
kind: design-options
authority: human
last_generated: 2026-06-25
---

# KLC-051 — Design options

## Context

Spec picked Option A (mechanical API-existence gate + prompt-discipline for the test-coverage
rule + agent self-review hook + documented audit step). This document records the extractor's
matching contract and the gate-wiring decision.

## Decision D-001: the API-existence matcher (low-false-positive by design)

`unresolved_api_refs(impl_plan_text)`:
1. Build the set of known modules = basenames of `core/skills/*.py` (e.g. `scan_sentinels`,
   `budget`, `phase_completion`).
2. Collect symbols INTRODUCED by this plan: scan the impl-plan for `core/skills/<name>.py (new)`
   in Affected lines and for `def <attr>`/`class <attr>` inside fenced sketches — these are
   exempt (the plan is adding them).
3. Regex-extract `(?<![\w.])(<known_module>)\.(\w+)\s*\(` occurrences OUTSIDE the prose that
   are inside code sketches (fenced blocks) — only sketches contain real call syntax.
4. For each `(module, attr)`, resolve `attr` against the module by AST-parsing
   `core/skills/<module>.py` and collecting its top-level `def`/`class`/assignments. Flag any
   `attr` absent AND not in the plan-introduced set.
5. Leading names not in the known-module set (stdlib, third-party, aliases) are ignored.

This catches `scan_sentinels.scan(` (real module, missing attr) while ignoring `os.path.join(`,
`re.compile(`, and aliased calls — keeping false positives near zero.

## Decision D-002: gate wiring

`phase_completion.can_complete_discovery_lite` (S) and the design-ack path (M/L) call
`plan_quality.unresolved_api_refs(impl_plan_text)` right after `impl_plan_check.impl_plan_violations`,
returning `(False, msg)` naming the first unresolved ref. It composes after the existing
completeness gate so both run; an empty result is a no-op.

## Decision D-003: judgment parts stay prompt + harness + audit

The "end-to-end + negative-test" rule is NOT a hard Python gate (Option B rejected — noisy).
It lives as prose in the three planning prompts, is regression-guarded by a KLC-029 harness
assert (AC-4), and is enforced per-ticket by the agent self-review (AC-5, KLC-037 extension)
and the documented adversarial completeness-audit prep step (AC-6).
