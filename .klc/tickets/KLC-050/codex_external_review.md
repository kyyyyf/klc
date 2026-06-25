---
ticket: KLC-050
reviewer: codex
role: external
reviewed_ref: feature/klc-050
reviewed_range: 311c410..3881db8
verdict: CHANGES REQUESTED
---

# External review — KLC-050

## Findings

### [MEDIUM] Removed impl-plan templates are still documented as the contract sample

KLC-050 removes `core/templates/impl-plan.md.j2` and `core/templates/impl-plan-short.md.j2`, and `docs/process.md:727` through `docs/process.md:731` correctly says those stale templates were removed. But `docs/process-artifacts.md:133` through `docs/process-artifacts.md:138` still tells readers that `impl-plan.md` is authored to match `impl-plan.md.j2` / `impl-plan-short.md.j2` and describes those files as the current contract sample.

That leaves the process artifact documentation pointing at files that no longer exist, which is exactly the drift trap AC-5 was meant to close. Update `docs/process-artifacts.md` to name the live enforced contract source instead, such as `core/skills/impl_plan_check.py` and the agent prompt/implementation-plan contract, or remove the template reference entirely.

### [MEDIUM] The strict model guard is not covered at a CLI/user-facing boundary

The new strict guard raises before dispatch in `runner.run_agent` at `core/skills/runner.py:311` through `core/skills/runner.py:319` and in `build_orchestrator.run_build` at `core/skills/build_orchestrator.py:135` through `core/skills/build_orchestrator.py:145`. The tests at `tests/integration/test_model_subagent_guard.py:127` through `tests/integration/test_model_subagent_guard.py:171` prove the helper blocks the mocked dispatch callbacks, but they assert raw `ValueError` propagation from the Python APIs.

AC-3 allows a raised rejection at the helper/dispatch layer, but the ticket goal is an enforceable gate rather than a crashy internal exception. The user-facing paths that call these APIs, such as `klc build-run` via `core/phases/build_run.py`, are not tested to return a controlled non-zero result or clear error when the guard fires. Add coverage at one CLI boundary and either convert the guard failure to a clean non-zero diagnostic there, or explicitly document that a traceback is the intended rejection surface.

## Verification

Static review only. I did not run tests because the request was to avoid modifying files, and pytest/import runs may create local cache files in this workspace.

## Verdict

CHANGES REQUESTED
