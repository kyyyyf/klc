---
ticket: KLC-006
kind: tech
authority: agent
classification:
  complexity: 2
  uncertainty: 1
  risk: 0
  manual: 1
  total: 4
track: S
estimate_days: 4
layer: content
affected_modules:
  - docs
---

# KLC-006 — Documentation refactor

## Goals

Restructure framework documentation into clear, layered structure for human contributors and LLM agents.

## Problem / Context

Current state:
- `docs/process.md` (352 lines) — process overview, scattered details
- `core/agents/*.md` (20 files) — role prompts + human prose mixed
- `README.md` — high-level only
- No role-based runbook
- No glossary

**Gap**: New contributor must reverse-engineer lifecycle from source code.

## Solution

### New documentation structure

```
docs/
  process.md          — Overview + lifecycle diagram (trimmed)
  roles.md            — NEW: As PM/agent/reviewer, you do...
  tracks.md           — NEW: XS/S/M/L decision tree
  glossary.md         — NEW: Term definitions
  phases/             — NEW: One file per phase
    intake.md
    discovery.md
    acceptance-test-plan.md
    design.md
    detailed-test-plan.md
    build.md
    review.md
    manual.md
    integrate.md
    observe.md
    learn.md
```

### Per-phase doc template

Each `docs/phases/<phase>.md`:
- **Purpose**: What this phase accomplishes
- **Inputs**: Required artefacts (from prior phases)
- **Outputs**: Artefacts produced
- **Completion criteria**: When is it done?
- **Ack rules**: Pick options and where they lead
- **Common pitfalls**: What goes wrong
- **Example**: Walkthrough for fictional ticket

### Agent prompts cleanup

`core/agents/*.md`:
- Remove human-oriented "what this phase is for" prose
- Add header: `For human context see docs/phases/<phase>.md`
- Keep only LLM system-prompt content

## Acceptance Criteria

- **AC-1**: New contributor can run ticket end-to-end using only `docs/` (no source reading)
- **AC-2**: `docs/phases/<phase>.md` exists for every phase in `config/phases.yml`
- **AC-3**: `docs/tracks.md` contains decision flowchart with examples
- **AC-4**: `docs/glossary.md` defines all terms used in docs
- **AC-5**: `core/agents/*.md` no longer duplicate phase purpose (moved to `docs/phases/`)
- **AC-6**: All markdown links resolve, no orphan files

## Non-goals

- Rewriting agent system prompts (content stays, structure changes)
- Auto-generating docs from config
- Translations

## Constraints

- Maintain backward compatibility (existing prompts still work)
- `core/agents/*.md` remain the runtime authority for LLM prompts
- `docs/` is purely human-facing documentation layer

## Affected modules

- `docs/` (new structure)
- `core/agents/` (headers added, human prose removed)

## Estimate

- **Discovery**: 0.5 day (this spec)
- **Build**: 3 days
  - Write `docs/roles.md`, `docs/tracks.md`, `docs/glossary.md` (1 day)
  - Write 11 `docs/phases/<phase>.md` files (1.5 days)
  - Clean up `core/agents/*.md` headers (0.5 days)
- **Review**: 0.5 days

**Total**: 4 days → S-track

## Open questions

None.

## Related

- **Unblocks**: KLC-007 build phase (defines CLI conventions in glossary)
- **References**: KLC-008 (how to run E2E tests), KLC-009 (cleaned config)
