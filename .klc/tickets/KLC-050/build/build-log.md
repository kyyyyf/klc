# KLC-050 Build Log

**Branch:** `feature/klc-050`
**Steps completed:** 5 (10 commits: 5 RED + 5 GREEN)

## Step 1 — broaden no-pre-judgment lint

Added `test_lint_catches_paraphrases` + `test_lint_ignores_benign`. Extended `_PATTERNS` in `lint_review_prompts.py` with `don'?t\s+flag`, `treat\s+as\s+(minor|trivial)`, `ignore\s+(this|the)\s+(issue|finding|file)`, `downgrade\s+(it|this|the\s+severity)`.

## Step 2 — placeholder-aware recorded_pick

Added `test_recorded_pick_rejects_placeholder` + `test_recorded_pick_accepts_concrete`. Replaced `_PICKED_RE` simple match with `_PICK_LINE_RE` + `_PLACEHOLDER_RE` logic in `spec_structure.py`.

## Step 3 — strict model guard

Added `test_model_guard_strict_rejects`, `test_runner_refuses_dispatch_without_model`, `test_build_orchestrator_refuses_dispatch_without_model`. Added `require_subagent_model()` to `model_guard.py`; wired before dispatch in `runner.run_agent` and `build_orchestrator.run_build`.

## Step 4 — unify step parser + retire stale templates

Added `test_single_step_parser_delegates` + `test_plan_template_renders_gate_passing`. `phase_completion._impl_plan_steps` now delegates to `impl_plan_check.parse_impl_plan_steps` via module reference (enabling spy). Deleted `core/templates/impl-plan.md.j2` and `impl-plan-short.md.j2`.

## Step 5 — docs parity

Added "Gate hardening (KLC-050)" section to `docs/process.md` covering all four hardened gates.

## Evidence

```
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
441 passed, 11 skipped in 164.29s (0:02:44)
```

Previous baseline (KLC-049): 432 passed, 11 skipped, 0 failed.
9 new tests added by KLC-050.
