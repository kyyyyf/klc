---
ticket: KLC-051
reviewer: codex
role: external
reviewed_ref: feature/klc-051
reviewed_range: c2ae0cc..af88935
verdict: CHANGES REQUESTED
---

# External review — KLC-051

## Findings

### [HIGH] Same-plan module attributes are still flagged as unresolved

AC-1 says `unresolved_api_refs` must not flag a symbol introduced by the same plan, including symbols from `def` / `class` sketches and `(new)` affected files. The implementation only collects bare introduced names from fenced `def` / `class` lines at `core/skills/plan_quality.py:54` through `core/skills/plan_quality.py:55`, then exempts a reference only when the called attribute name appears in that global set at `core/skills/plan_quality.py:58` through `core/skills/plan_quality.py:63`.

That means a plan adding `core/skills/foo.py (new)` with `def run(...)` and then sketching `foo.run(...)` is still flagged if `core/skills/foo.py` does not exist yet, or if a plan adds a new function to an existing skill and later sketches `existing_skill.new_helper(...)`. Those are exactly same-plan-introduced APIs, but they still fail because `_known_modules()` only sees existing files at `core/skills/plan_quality.py:20` through `core/skills/plan_quality.py:21`, and the introduced-name exemption is not associated with the module side of `module.attr(`.

This violates AC-1 and will block valid plans that introduce a new skill/module and then use it in a later step. Parse `(new)` affected `core/skills/<module>.py` entries and code-sketch definitions per module, then exempt `module.attr` when that module or attr is introduced by the same plan. Add a regression with a new `core/skills` module referenced as `new_module.new_func(` and another with an existing skill gaining a planned helper.

### [MEDIUM] Design/M-L gate wiring is untested

AC-2 requires the API-existence gate to block both discovery-lite S ack and design M/L ack through real completion entry points. The implementation wires discovery-lite at `core/skills/phase_completion.py:350` through `core/skills/phase_completion.py:357` and generic phase-output completion at `core/skills/phase_completion.py:494` through `core/skills/phase_completion.py:504`, but the regression tests only call `can_complete_discovery_lite` at `tests/integration/test_plan_quality.py:179` through `tests/integration/test_plan_quality.py:193`.

If the design phase stops declaring `impl-plan.md` as an output, or `_can_complete_generic` is bypassed/refactored for design, this test suite will still pass while M/L planning loses the new gate. Add an M/L fixture that drives `can_complete(ticket, "design")` or the exact design ack path with `scan_sentinels.scan(` and verifies it blocks, plus the corresponding passing `scan_diff(` case.

### [MEDIUM] Self-review coverage does not exercise a self-review path

AC-5 says the agent-side self-review runs `unresolved_api_refs` over the impl-plan before emitting. The added test at `tests/integration/test_plan_quality.py:200` through `tests/integration/test_plan_quality.py:208` calls `unresolved_api_refs` directly and asserts the helper returns a finding. It does not exercise any self-review function, prompt-regression harness behavior, or even assert that the planning prompts instruct the agent to run that API-existence check.

The prompt text does include `plan_quality.unresolved_api_refs` in `core/agents/design.md` and `core/agents/discovery-lite.md`, but there is no permanent regression test tied to that instruction. Add a structural prompt test that both planning prompts mention `plan_quality.unresolved_api_refs`, or add a real self-review helper wrapper and test that wrapper. As written, the test would pass even if the self-review instruction were removed.

## Verification

Static review only. I did not run tests because the request was to avoid modifying files, and pytest/import runs may create local cache files in this workspace.

## Verdict

CHANGES REQUESTED
