# Phase 2 Complete — Context wiring (ADRs + test plans)

## Summary

Phase 2 from the review overhaul plan is complete. Review sub-agents now
receive ADR and test-plan context, enabling architecture reviewers to detect
when changes contradict documented decisions.

## Changes

### 2.1 Context-loader ADR discovery (shipped in PR #6)
- `core/skills/context-loader.py`: `collect_adrs_from_claude_mds()` function
  parses `## ADRs` sections from CLAUDE.md files, resolves markdown links,
  inlines contents with 50% of remaining symbol-budget headroom.
- `--test-plan` CLI arg: optional path to test-plan.md; inlined if present.
- Result dict includes: `adr_files`, `adr_inlined`, `test_plan_file`, `test_plan_inlined`.

### 2.3 Wire ADR and test-plan context to review sub-agents
- `scripts/review.py`:
  - `_collect_adrs(root, modules_idx, affected)` — parses ## ADRs sections
    from root and affected-module CLAUDE.md files, resolves links, inlines.
  - Detects test-plan.md if spec lives in `PROJ-*/` or `TICK-*/` directory.
  - Writes `adr-context.md` bundle with all inlined ADRs.
  - `_write_job_card()` accepts `adr_context` and `test_plan` params (optional).
  - Job cards now include `- adr_context:` and `- test_plan:` lines.

- `scripts/review-runner.py`:
  - Parse `adr_context` and `test_plan` fields from job cards.
  - Pass them to `run_agent()` as inputs.

### 2.4 Architecture reviewer ADR contradiction detection
- `core/agents/review/architecture.md`:
  - Added `adr_context` and `test_plan` to ## Inputs.
  - Focus area #5: **ADR contradiction** — when `adr_context` is provided,
    check if the diff contradicts a decision recorded in an ADR.
  - New section: **## How to use adr_context** — 5-step protocol:
    1. Read all inlined ADRs (marked with `<!-- BEGIN ADR: path -->`).
    2. Check for contradictions against diff.
    3. Flag `change-contradicts-adr` when diff negates ADR decision.
    4. Do NOT flag when spec references superseding ADR or change is
       implementation detail.
    5. Cite ADR Decision line in finding body.

### 2.5 Review report shows ADRs in scope
- `core/templates/review-report.md.j2`:
  - Added `## ADRs in scope` section after Summary table.
  - Lists all ADRs loaded into review context (if any).

- `scripts/review.py`:
  - Pass `adr_paths` to template renderer as `adrs` parameter.
  - Convert Path objects to strings for template.

## Acceptance criteria (all met)

1. ✅ `adr_context` and `test_plan` fields appear in job cards when available.
2. ✅ Job cards include paths to `adr-context.md` (bundle of inlined ADRs).
3. ✅ `architecture.md` documents how to use `adr_context` input.
4. ✅ `change-contradicts-adr` rule implemented in architecture reviewer.
5. ✅ Review report lists ADRs in scope.
6. ✅ No change to review.py aggregation logic (ADR context is input-only).

## Out of scope for Phase 2

- Risk-based review (tiers, sentinels, per-tier thresholds) — Phase 3a.
- Publish adapters (GitLab, GitHub inline comments, CI checks) — Phase 3b.
- Hallucination detection skill — future.
- Cross-PR finding history — future.

## Next steps

- **Phase 3a** — Risk-based review: tier classification (critical/core/peripheral),
  sentinel patterns, per-tier blocking thresholds.
- **Phase 3b** — Publish adapters: GitLab and GitHub integration for labels,
  inline comments, CI status checks.

## Testing recommendations

To test Phase 2 changes:

1. Create a ticket with `docs/adr/ADR-001-example.md` referenced in root `CLAUDE.md`.
2. Run `klc review --diff <branch> --spec <ticket>/spec.md`.
3. Verify `pending-<TS>/adr-context.md` exists and contains inlined ADR.
4. Verify job cards include `- adr_context: ...` line.
5. Run architecture reviewer, intentionally contradict ADR in diff.
6. Verify finding with `rule_name: change-contradicts-adr` appears.
7. Check `review-<TS>.md` report includes `## ADRs in scope` section.
