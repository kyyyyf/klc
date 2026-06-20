# Tracks — Ticket sizing and phase sequences

Tracks determine which phases a ticket goes through based on complexity, uncertainty, risk, and manual work required.

## Track decision flowchart

```
Start: Ticket in intake phase
  │
  ├─> Estimate complexity, uncertainty, risk, manual
  │
  ├─> Calculate total = complexity + uncertainty + risk + manual
  │
  └─> Select track:
      │
      ├─> total ≤ 3              → XS track (fast path)
      ├─> total = 4-6            → S track
      ├─> total = 7-10           → M track
      └─> total ≥ 11             → L track
```

## Estimation dimensions

Each dimension scores 0-5:

| Dimension | 0 | 1 | 2 | 3 | 4 | 5 |
|-----------|---|---|---|---|---|---|
| **Complexity** | Trivial | Simple | Moderate | Complex | Very complex | Extreme |
| **Uncertainty** | Known solution | Minor unknowns | Some research | Significant unknowns | High uncertainty | Research-heavy |
| **Risk** | No risk | Low | Moderate | High | Very high | Critical |
| **Manual** | Fully automated | Minimal manual | Some manual | Significant manual | Mostly manual | Entirely manual |

**Examples**:

- **Complexity=0**: One-line config change
- **Complexity=3**: Refactor 500 LOC across 5 files with new abstraction
- **Uncertainty=0**: Copy-paste from existing pattern
- **Uncertainty=3**: Need to prototype two approaches before deciding
- **Risk=0**: Docs-only change
- **Risk=3**: Database migration on production table with 50M rows
- **Manual=0**: Fully automated by agent
- **Manual=3**: Agent generates code, human does manual QA on staging

## Track comparison

| Track | Total | Phases | Typical duration | Example tickets |
|-------|-------|--------|------------------|-----------------|
| **XS** | ≤3 | intake → discovery → xs-build → review-lite → integrate → learn | 0.5-1 day | Typo fix, simple config change, add log statement |
| **S** | 4-6 | intake → discovery-lite (spec+test-plan+impl-plan) → build → review → integrate → observe → learn | 1-3 days | New endpoint, refactor module, add feature flag |
| **M** | 7-10 | intake → discovery → acceptance-test-plan → design (impl-plan w/ per-step tests) → build → review → manual → integrate → observe → learn | 3-7 days | Multi-module refactor, new subsystem, non-trivial algorithm |
| **L** | ≥11 | intake → discovery → acceptance-test-plan → design → detailed-test-plan → build → review → manual → integrate → observe → learn | 7-14 days | Architecture change, new service, large-scale migration |

<!-- BEGIN GENERATED:tracks-thresholds -->
| Track | Max total |
| ----- | --------- |
| XS | 2 |
| S | 5 |
| M | 8 |
| L | unbounded (≥9) |
<!-- END GENERATED:tracks-thresholds -->

<!-- BEGIN GENERATED:tracks-phase-sequences -->
**XS**: intake → discovery-lite → xs-build → review-lite → integrate → learn

**S**: intake → discovery-lite → build → review → integrate → observe → learn

**M**: intake → discovery → acceptance-test-plan → design → build → review → manual → integrate → observe → learn

**L**: intake → discovery → acceptance-test-plan → design → detailed-test-plan → build → review → manual → integrate → observe → learn
<!-- END GENERATED:tracks-phase-sequences -->

## Phase sequences

### XS track
```
intake:ack-needed → intake:ack
  ↓
discovery:work → discovery:ack-needed → discovery:ack
  ↓
xs-build:work (combined build+test, no test-plan.md required)
  ↓
review-lite:work (fast review, no detailed audit)
  ↓
integrate:work (merge to main)
  ↓
learn:work (lightweight retrospective)
```

**Key differences**:
- No acceptance-test-plan phase (test-plan.md not required)
- xs-build combines test writing and implementation
- review-lite skips detailed audit
- No observe phase (no metrics monitoring)

### S track
```
intake:ack-needed → intake:ack
  ↓
discovery-lite:work → discovery-lite:ack-needed → discovery-lite:ack
  (emits spec.md + test-plan.md + impl-plan.md in one agent call)
  ↓
build:work (TDD loop with test agent + impl agent)
  ↓
review:work → review:ack-needed → review:ack
  ↓
integrate:work
  ↓
observe:work (metrics monitoring, 24h window)
  ↓
learn:work (retrospective)
```

**Key differences**:
- No separate acceptance-test-plan phase — discovery-lite produces spec.md,
  test-plan.md, and impl-plan.md (1–3 steps) in one pass
- Full build TDD loop
- Full review audit
- Observe phase monitors metrics
- No design phase (work from spec.md directly)

### M track
```
intake:ack-needed → intake:ack
  ↓
discovery:work → discovery:ack-needed → discovery:ack
  ↓
acceptance-test-plan:work → acceptance-test-plan:ack-needed → acceptance-test-plan:ack
  ↓
design:work → design:ack-needed → design:ack
  (test-planner enriches each impl-plan step with unit/integration tests — no separate phase)
  ↓
build:work (TDD loop with impl-plan.md)
  ↓
review:work → review:ack-needed → review:ack
  ↓
manual:work (human manual testing/validation)
  ↓
integrate:work
  ↓
observe:work
  ↓
learn:work
```

**Key differences**:
- Adds design phase (options.md → adr.md); test-planner enriches impl-plan steps with
  per-step unit/integration tests (no standalone detailed-test-plan gate for M)
- manual phase between review and integrate (human validation)

### L track
Same as M track but adds a `detailed-test-plan` gate after design (standalone
`## Detailed coverage` in test-plan.md) and has longer duration and higher scrutiny.

## Decision examples

### Example 1: Documentation refactor (KLC-006)
- **Complexity**: 2 (create 15+ files, update agent prompts)
- **Uncertainty**: 1 (structure defined, no unknowns)
- **Risk**: 0 (docs-only, no runtime impact)
- **Manual**: 1 (human validates AC-1 via walkthrough)
- **Total**: 4 → **S track**

### Example 2: E2E test infrastructure (KLC-008)
- **Complexity**: 2 (new test harness, fake agents)
- **Uncertainty**: 1 (pattern clear, but phase sequence mapping needed iteration)
- **Risk**: 1 (framework lifecycle validation, low risk)
- **Manual**: 1 (human runs tests, validates output)
- **Total**: 5 → **S track**

### Example 3: Code cleanup (KLC-007)
- **Complexity**: 3 (audit 53 files, merge/delete/refactor)
- **Uncertainty**: 2 (need to verify no hidden dependencies)
- **Risk**: 1 (code changes, but test coverage exists)
- **Manual**: 1 (human reviews audit, approves deletions)
- **Total**: 7 → **M track**

### Example 4: Typo fix in README
- **Complexity**: 0 (one-line change)
- **Uncertainty**: 0 (obvious fix)
- **Risk**: 0 (docs-only)
- **Manual**: 0 (fully automated)
- **Total**: 0 → **XS track**

## Intake track is provisional

The track printed at `klc intake` is a **provisional floor** from a
deterministic heuristic (`route_heuristic.py`), with a `confidence`. It is
**not** the final track — Discovery/Discovery-lite is the authoritative
classifier and reads **blast-radius** (`modules.json` `depended_by`) so a
foundational-module change is sized by what it breaks, not by description
length. A short description means *under-specified*, not *simple*: on a
short, low/medium-confidence ticket intake recommends the cheap
`intake-triage` agent (or forcing full discovery). Downgrades are forbidden;
upgrades are always allowed.

## When to override track

The framework allows manual track override in `meta.json`, but this should be rare. Valid reasons:

- **Upgrade**: S → M if design phase would reduce rework risk despite low total
- **Downgrade**: M → S if uncertainty was overestimated and solution is now clear

Invalid reasons:
- "Let's skip design to go faster" (undermines process)
- "This should be XS because it's urgent" (urgency ≠ simplicity)

## Summary

- Use total estimate (complexity + uncertainty + risk + manual) to select track
- XS = fast path, S = standard, M/L = design-heavy
- Track determines phase sequence and gate rigor
- Override only when process mismatch is clear

For phase-specific details, see `docs/phases/<phase>.md`.
