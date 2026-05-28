---
ticket: KLC-006
kind_hint: tech
created: 2026-05-28T11:15:05Z
---
# KLC-006 — Documentation refactor: roles, phases, process

## Context

Framework grew organically through Phases 1–4. Documentation is fragmented:
- `docs/process.md` (352 lines) — phase map, verbs, tracks
- `core/agents/*.md` (20 files) — role prompts mixed with operational instructions
- `README.md` — high-level only
- No single "how do I run a ticket as <role>?" guide

New contributors / future-self must reverse-engineer the lifecycle by reading source.

## Problem

Specific gaps:
1. **Role-based runbook missing**: no doc that says "as PM, you do X; as agent, you read Y; as reviewer, you check Z"
2. **Phase descriptions scattered**: each phase's purpose / inputs / outputs / completion criteria live partly in `core/agents/<phase>.md`, partly in `config/phases.yml`, partly in `docs/process.md`
3. **Tracks (XS/S/M/L) decision tree unclear**: estimate buckets exist but the "which path do I take" flowchart is implicit
4. **Agent prompts mix audiences**: same `.md` file is read by both the human (to understand role) and the LLM (as system prompt). Hard to update one without polluting the other.
5. **No glossary**: "fact", "sentinel", "tier", "artefact", "intake", "ack" — defined in scattered places

## Proposed solution

Restructure documentation into clear layers:

**`docs/` (human-facing)**:
- `docs/process.md` — high-level lifecycle (keep, but trim to overview + diagram)
- `docs/roles.md` — NEW. "As PM you do …", "As agent you do …", "As reviewer you do …"
- `docs/phases/<phase>.md` — NEW. One file per phase: purpose, inputs, outputs, completion criteria, common pitfalls
- `docs/tracks.md` — NEW. XS/S/M/L decision tree with examples
- `docs/glossary.md` — NEW. Single source of truth for terms

**`core/agents/*.md` (LLM-facing)**:
- Strip human-oriented prose; keep only system-prompt content
- Add header pointing to `docs/phases/<phase>.md` for human context

**Cross-links**: `docs/` files link into source (`config/phases.yml`, `core/agents/*.md`) so source remains the runtime authority.

## Acceptance criteria

- AC-1: A new contributor can read `docs/roles.md` + `docs/process.md` and run a ticket end-to-end without reading source
- AC-2: Each phase has a `docs/phases/<phase>.md` with: purpose, inputs (artefacts read), outputs (artefacts written), completion criteria, ack rules
- AC-3: `docs/tracks.md` contains decision flowchart (estimate → track) with concrete examples for each track
- AC-4: `docs/glossary.md` defines every term used in `docs/` and `core/agents/`
- AC-5: `core/agents/*.md` no longer contain duplicated "what this phase is for" prose (moved to `docs/phases/`)
- AC-6: All docs lint-pass (markdown links resolve, no orphan files)

## Out of scope

- Rewriting `core/agents/*.md` system prompts themselves (covered by KLC-007 if duplication is found)
- Auto-generating docs from config (manual authoring is fine for this round)
- Translating to Russian / other languages

## Estimate

- Complexity: 2 (writing, no new logic)
- Uncertainty: 1 (structure may need iteration after first agent reads it)
- Risk: 0 (docs only)
- Manual: 1 (proofread + walk through as new contributor)
- Total: 4
- Track: S

## Related

- KLC-007 (code refactor) may surface duplication that should be reflected in docs
- KLC-008 (e2e tests) — docs should include "how to run smoke test"
- KLC-009 (config cleanup) — `docs/phases/<phase>.md` should reference cleaned-up `config/phases.yml`

## Notes

Order matters: do KLC-006 first to establish doc structure, then KLC-007/008/009 update docs as part of their changes.
