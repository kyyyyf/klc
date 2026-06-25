---
ticket: KLC-051
kind: impl-plan
design_choice: option-A-minimal
last_generated: 2026-06-25
---

# KLC-051 — Implementation plan (executable, for Sonnet)

Build target: a mechanical API-existence gate plus prompt-discipline and a self-review hook for
end-to-end/negative test coverage. Per-step contract: **Goal / RED / Interfaces / Expected /
VERIFY / COMMIT / Affected / Code sketch / Depends-on**. Run after each step:
`python3 -m pytest tests/ -q --ignore=tests/fixtures`. COMMIT subjects verbatim.

## step-1 — plan_quality.unresolved_api_refs extractor

- **Goal:** flag impl-plan code-sketch calls that name a real core/skills module but a
  nonexistent attribute, while ignoring unknown modules and same-plan-introduced symbols. (AC-1)
- RED: add `tests/integration/test_plan_quality.py::test_unresolved_api_refs_flags_missing` and
  `::test_unresolved_api_refs_ignores_unknown_and_self`. Fail today (no module).
- **Interfaces:** `core/skills/plan_quality.py::unresolved_api_refs(impl_plan_text: str) ->
  list[str]`. Known modules = basenames of `core/skills/*.py`. Resolves an attr by AST-parsing
  `core/skills/<module>.py` for top-level `def`/`class`/assignments. Plan-introduced symbols
  (from `def`/`class` inside the plan's own sketches and `(new)` Affected files) are exempt.
- **Expected:** `scan_sentinels.scan(` flagged; `scan_sentinels.scan_diff(` not; `os.path.join(`
  and `re.compile(` ignored (not core/skills modules); a self-introduced symbol not flagged.
- **VERIFY:** `python3 -m pytest tests/integration/test_plan_quality.py -k unresolved -q`
- **COMMIT:** `KLC-051 step-1: plan_quality.unresolved_api_refs extractor`
- **Affected:** `core/skills/plan_quality.py` (new), `tests/integration/test_plan_quality.py` (new).
- Depends-on: none.
- **Code sketch:**

```python
import ast, re
from pathlib import Path
_SKILLS = Path(__file__).resolve().parent
def _known_modules():
    return {p.stem for p in _SKILLS.glob("*.py")}
def _defined(module):
    tree = ast.parse((_SKILLS / f"{module}.py").read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names
def unresolved_api_refs(text):
    known = _known_modules()
    fenced = "\n".join(re.findall(r"```[^\n]*\n([\s\S]*?)```", text))
    introduced = set(re.findall(r"(?m)^\s*(?:def|class)\s+(\w+)", fenced))
    out = []
    for mod, attr in re.findall(r"(?<![\w.])(\w+)\.(\w+)\s*\(", fenced):
        if mod in known and attr not in introduced and attr not in _defined(mod):
            out.append(f"unresolved API ref: {mod}.{attr} (not defined in core/skills/{mod}.py)")
    return sorted(set(out))
```

## step-2 — wire the gate into plan-completeness

- **Goal:** block design (M/L) and discovery-lite (S) ack when an impl-plan names a nonexistent
  API of a known module, exercised through the real `can_complete_*` entry. (AC-2)
- RED: add `test_plan_quality_gate_blocks_bad_ref` building a ticket whose `impl-plan.md`
  calls `scan_sentinels.scan(` and asserting `can_complete_discovery_lite` returns blocked
  naming the ref; the same plan with `scan_diff(` passes. Drives `can_complete_*`, not the helper.
- **Interfaces:** in `core/skills/phase_completion.py`, after the `impl_plan_check.impl_plan_violations`
  call in both the design-ack path and `can_complete_discovery_lite`, call
  `plan_quality.unresolved_api_refs(impl_plan_text)` and return `(False, refs[0])` when non-empty.
- **Expected:** bad ref blocks via the public gate; resolvable plan passes; empty result is a no-op.
- **VERIFY:** `python3 -m pytest tests/integration/test_plan_quality.py -k gate -q`
- **COMMIT:** `KLC-051 step-2: wire plan_quality API-existence check into plan-completeness gate`
- **Affected:** `core/skills/phase_completion.py`, `tests/integration/test_plan_quality.py`.
- Depends-on: step-1.
- **Code sketch:**

```python
import plan_quality
_refs = plan_quality.unresolved_api_refs(_impl_plan_path.read_text(encoding="utf-8"))
if _refs:
    return False, _refs[0]
```

## step-3 — planning-prompt rule (end-to-end + negative tests)

- **Goal:** the planning prompts require an end-to-end test per wired AC and a negative +
  fail-closed test per gate AC. (AC-3)
- RED: not applicable — prompt-only step. Rule cited: AC-3 + the two audit reports' recurring
  helper-only-test finding.
- **Interfaces:** prose only — add a "Test-coverage discipline" block to
  `core/agents/design.md`, `core/agents/discovery-lite.md`, and `core/agents/test-planner.md`:
  every AC describing a CLI/gate/wired behaviour maps to a test at the public entry point (not a
  private helper); every gate/validator AC maps to a negative test (the gate bites) plus a
  fail-closed test.
- **Expected:** `grep -rn "public entry point" core/agents/design.md core/agents/discovery-lite.md core/agents/test-planner.md` shows the block in all three.
- **VERIFY:** `grep -rln "public entry point" core/agents/design.md core/agents/discovery-lite.md core/agents/test-planner.md`
- **COMMIT:** `KLC-051 step-3: planning prompts require end-to-end + negative test coverage`
- **Affected:** `core/agents/design.md`, `core/agents/discovery-lite.md`, `core/agents/test-planner.md`.
- Depends-on: none.
- **Code sketch:** not applicable — prompt prose only (RED not applicable).

## step-4 — prompt-regression assert for the rule

- **Goal:** a permanent guard that all three planning prompts carry the test-coverage rule. (AC-4)
- RED: add `tests/test_prompt_regression.py::test_planning_prompts_endtoend_rule` asserting the
  rule phrase is present in each prompt; confirm RED against the pre-step-3 prompts.
- **Interfaces:** a structural assert reusing the existing prompt-regression helpers
  (`tests/prompt_harness.py`); no LLM judge needed (phrase presence is structural).
- **Expected:** the test is RED before step-3 and GREEN after; kept permanent, not `xfail`.
- **VERIFY:** `python3 -m pytest tests/test_prompt_regression.py -k endtoend_rule -q`
- **COMMIT:** `KLC-051 step-4: regression guard for the end-to-end/negative test rule`
- **Affected:** `tests/test_prompt_regression.py`.
- Depends-on: step-3.
- **Code sketch:**

```python
def test_planning_prompts_endtoend_rule():
    for name in ("design.md", "discovery-lite.md", "test-planner.md"):
        text = (AGENTS / name).read_text(encoding="utf-8")
        assert "public entry point" in text
```

## step-5 — agent-side self-review runs the API check

- **Goal:** the planning agent runs `unresolved_api_refs` over its impl-plan before emitting and
  fixes or flags unresolved references inline. (AC-5)
- RED: not applicable — directive is prompt prose only; the behavioral test
  (`test_self_review_runs_api_check`) was committed with step-1 RED as it exercises the same
  AC-1 helper; the AC-5 structural assert (`test_planning_prompts_api_check_directive`) was
  added in the Codex-fix commit.
- **Interfaces:** extend the design/discovery-lite self-review block to call
  `plan_quality.unresolved_api_refs` (the same skill the gate uses), and add the directive to
  the prompts so the agent reconciles refs before emitting.
- **Expected:** a planted `scan_sentinels.scan(` is surfaced by the self-review path; a clean
  plan surfaces nothing.
- **VERIFY:** `python3 -m pytest tests/integration/test_plan_quality.py -k self_review -q`
- **COMMIT:** `KLC-051 step-5: agent self-review runs the API-existence check`
- **Affected:** `core/agents/design.md`, `core/agents/discovery-lite.md`,
  `tests/integration/test_plan_quality.py`.
- Depends-on: step-1.
- **Code sketch:**

```python
# self-review hook reuses the gate's own skill — single source
refs = plan_quality.unresolved_api_refs(impl_plan_text)
assert refs == [] or all("unresolved API ref" in r for r in refs)
```

## step-6 — docs parity + adversarial-audit prep step

- **Goal:** document the plan-quality gate and add the adversarial completeness-audit as a
  standard build-ready prep step. (AC-6)
- RED: not applicable — docs-only step. Rule cited: AC-6 + the planning analog of the mandatory
  code-reviewer.
- **Interfaces:** prose only — `docs/process.md` gains a "plan-quality gate" note (the
  API-existence check + the test-coverage rule) and a "build-ready prep: adversarial
  completeness-audit" step describing a fresh subagent reading spec/test-plan/impl-plan for
  AC-coverage, wiring, end-to-end and negative tests.
- **Expected:** `grep -rn "plan-quality\|completeness-audit" docs/process.md` returns the content.
- **VERIFY:** `grep -rn "completeness-audit" docs/process.md`
- **COMMIT:** `KLC-051 step-6: docs parity for plan-quality gate + audit prep step`
- **Affected:** `docs/process.md`.
- Depends-on: step-2, step-3, step-5.
- **Code sketch:** not applicable — documentation prose only (RED not applicable).

## Notes for the implementer

- One logical commit per step; COMMIT subjects verbatim.
- The extractor is deliberately conservative (literal `module.attr(` on known core/skills
  modules only) — do not try to resolve aliased imports; that would add false positives.
- Single source: the gate (step-2) and the self-review (step-5) call the SAME
  `plan_quality.unresolved_api_refs` — never duplicate the logic.
- After step-2, run `unresolved_api_refs` over the already-prepared plans (045/046/047/049/050)
  as a regression check and fix any real unresolved ref surfaced.
