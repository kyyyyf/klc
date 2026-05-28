---
ticket: KLC-007
kind_hint: tech
created: 2026-05-28T11:15:07Z
---
# KLC-007 — Code refactoring: deduplicate skills, simplify phases

## Context

`core/skills/` (38 files) and `core/phases/` (12 files) accreted across Phases 1–4. Some duplication and dead code suspected; no audit done.

## Problem

Suspected (need confirmation in discovery phase):
1. **Duplicate logic across skills**: e.g., YAML loading, path resolution, artefact-write helpers
2. **`.bak` files in tree**: `callgraph_rust_pattern.py.bak` should be deleted, possibly others
3. **Inconsistent CLI conventions**: some skills use `--out`, some `--output`, some positional args
4. **Phase implementations vary in shape**: some `core/phases/*.py` are thin wrappers, some embed logic that belongs in skills
5. **Mixed responsibilities**: `runner.py`, `lifecycle.py`, `phases.py`, `phase_completion.py` overlap in "what is the current state of a ticket"
6. **Token / context inefficiency in Build phase** (per memory `project_refactor_plan.md`): skills load whole files when symbol-level slices would suffice

## Proposed solution

Two-step refactor:

**Step 1 — Audit (discovery phase output)**:
- Inventory: every file in `core/skills/`, `core/phases/`, `scripts/`
- Mark each: `keep`, `merge-with-X`, `delete`, `move-to-Y`
- Identify shared helpers worth extracting into `core/skills/_common.py`

**Step 2 — Refactor (build phase)**:
- Delete `.bak` files
- Extract shared helpers (YAML, path, artefact I/O) into `_common.py` or expand `_yaml.py`/`_paths.py`
- Standardize skill CLI: `--ticket`, `--out`, `--root`, exit codes
- Collapse `runner.py` / `lifecycle.py` / `phases.py` overlap into clear ownership:
  - `lifecycle.py` = state machine (current phase, allowed transitions)
  - `phases.py` = phase metadata (read from `config/phases.yml`)
  - `runner.py` = invokes agents for a phase (CLI entry)
  - `phase_completion.py` = artefact-based "is phase done?" check
- No behavior changes; `tests/smoke.py` and `tests/test_callgraph_rust_lsp.py` still pass

## Acceptance criteria

- AC-1: Audit table in `discovery.md` lists every file with disposition (keep/merge/delete/move)
- AC-2: All `.bak` files removed from tree
- AC-3: Skill CLIs follow documented convention (see `docs/glossary.md` from KLC-006)
- AC-4: `tests/smoke.py` passes unchanged
- AC-5: `tests/test_callgraph_rust_lsp.py` passes unchanged
- AC-6: No new imports from `scripts/` into `core/skills/` (one-way dependency)
- AC-7: Line count reduction ≥10% in `core/skills/` (sanity check, not hard requirement)

## Out of scope

- Adding new functionality (purely refactor)
- Performance tuning (separate ticket if needed)
- Rewriting agent prompts (`core/agents/*.md` content)

## Estimate

- Complexity: 3 (touches many files, dependency mapping needed)
- Uncertainty: 2 (audit may find more than expected)
- Risk: 1 (regression risk — mitigated by smoke tests)
- Manual: 1 (re-run smoke + LSP test)
- Total: 7
- Track: M (or S if audit shows minor scope)

## Related

- Depends on KLC-008 (e2e fake-agent pipeline) — gives confidence to refactor without breaking
- Depends on KLC-006 (CLI convention documented in glossary)
- KLC-009 (config cleanup) is independent, can run in parallel

## Notes

Run KLC-008 first so e2e tests catch regressions during this refactor.
