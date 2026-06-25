---
ticket: KLC-050
phase: review
branch: feature/klc-050
reviewed_range: main..feature/klc-050 (11 commits: dba19cd..3d3ce63)
reviewers:
  - internal: code-reviewer subagent (fresh, no conversation context)
  - external: Codex (codex_external_review.md)
verdict: APPROVED
---

# Review Report — KLC-050 (Gate Hardening)

## AC Compliance

| AC | Status | Notes |
|----|--------|-------|
| AC-1: broaden no-pre-judgment lint to contractions/paraphrases | PASS | All required phrases flag; benign negatives pass |
| AC-2: placeholder-aware `recorded_pick` | PASS | Rejects `<approach>`, `TBD`, empty; trailing whitespace stripped before check |
| AC-3: strict model guard (`require_subagent_model`) | PASS | Raises before dispatch in both `runner.run_agent` and `build_orchestrator.run_build`; CLI boundary returns clean non-zero |
| AC-4: unified step parser via delegation | PASS | `_impl_plan_steps` delegates to `parse_impl_plan_steps`; spy confirms call; adapter shape correct |
| AC-5: stale template retirement | PASS | Both `.j2` files deleted; test asserts glob returns empty |

---

## Internal Code-Reviewer Findings

### HIGH — guard fires after brief file I/O in `run_build`

**Severity**: HIGH  
**Description**: `require_subagent_model` was called after `build_step_brief()` and `brief_path.write_text()`. If the model is misconfigured, the step brief file is written to disk before the guard fires — leaving a stale artifact. Also, if `build_step_brief` raises `SystemExit` (e.g., missing jinja2), `pytest.raises(ValueError)` in the test would mask whether the guard itself fires.  
**Fix**: Moved `mc.resolve(...)`, `require_subagent_model(resolved)`, and `check_subagent_dispatch` to execute BEFORE `build_step_brief(ticket, n)` in `run_build`.  
**Status**: FIXED — `core/skills/build_orchestrator.py` reordered in step-7 commit.

### MEDIUM — same root cause as HIGH (guard position)

**Severity**: MEDIUM  
**Description**: Subset of the HIGH finding — disk state inconsistency from guard firing after write.  
**Status**: FIXED — same reorder in step-7.

### LOW — spy test relies on implicit bare-name import convention

**Severity**: LOW  
**Description**: `test_single_step_parser_delegates` patches via bare `import impl_plan_check`; works because `phase_completion` also uses a bare import for the same `sys.modules` key, but this is not self-documenting.  
**Fix**: Added comment: `# bare import mirrors what phase_completion uses; both resolve to sys.modules["impl_plan_check"]`  
**Status**: FIXED — `tests/test_impl_plan_check.py` in step-7 commit.

### LOW — redundant local `import re as _re` in `_impl_plan_steps`

**Severity**: LOW  
**Description**: `phase_completion._impl_plan_steps` imported `re` locally; `_sync_risk_tags` also had a local `import re`. No functional impact.  
**Fix**: Promoted `re` to module-level import; removed both local imports; replaced `_re.search` with `re.search`.  
**Status**: FIXED — `core/skills/phase_completion.py` in step-7 commit.

---

## Codex External Review Findings

### [MEDIUM] Removed impl-plan templates still documented as contract sample

**Description**: `docs/process-artifacts.md` at lines 133–138 still referenced `impl-plan.md.j2` / `impl-plan-short.md.j2` as the authoring contract, despite those files being deleted.  
**Fix**: Updated `docs/process-artifacts.md` impl-plan.md section to reference `core/skills/impl_plan_check.py` (`REQUIRED_STEP_FIELDS`, `impl_plan_violations`) as the live enforced contract, with explicit note that the stale templates were removed in KLC-050.  
**Status**: FIXED — step-6 commit (`401e77d`).

### [MEDIUM] Strict model guard not covered at CLI boundary

**Description**: Tests asserted `ValueError` propagation from Python API level. `klc build-run` (via `build_run.py`) was not tested to return a controlled non-zero exit on guard failure.  
**Fix**: Added `try/except ValueError` in `core/phases/build_run.py` with clean stderr diagnostic; `run_build` now returns 1 instead of propagating uncaught.  
**Status**: FIXED — step-6 commit (`401e77d`).

---

## Suite Result

**441 passed, 11 skipped, 0 failed** (9 new tests added by KLC-050 over KLC-049 baseline of 432/11/0).

Step-7 re-run post-fixes: **441 passed, 11 skipped, 0 failed** — no regressions.

---

## Verdict

**APPROVED**. All AC pass. All HIGH and MEDIUM findings from both reviewers fixed before this report was written. Two LOW findings (style) also fixed. Branch is ready to advance to manual.
