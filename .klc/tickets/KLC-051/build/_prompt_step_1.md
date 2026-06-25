# Agent prompt — KLC-051 · build:work · step-1

Ticket: **KLC-051** · track: **M** · kind: **tech**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Catch the recurring "specced-but-unwired" defect class at PLANNING time rather than after
build. Two adversarial audits of the KLC-SP tickets found the same pattern repeatedly:
impl-plan code sketches that call APIs which do not exist (`scan_sentinels.scan` vs the real
`scan_diff`), helpers defined but never wired into a real call site, tests that exercise a
private helper instead of the public entry point, and gates with no negative/bypass test.
KLC-051 adds a mechanical API-existence gate plus prompt-discipline rules (end-to-end and
negative-test coverage) and a standard adversarial-audit prep step, so plans are unambiguous
and complete before a Sonnet agent builds them.

## Acceptance Criteria

- [ ] AC-1: A new skill `core/skills/plan_quality.py::unresolved_api_refs(impl_plan_text) ->
  list[str]` extracts `<module>.<attr>(` references from the impl-plan, and for every
  `<module>` that is the basename of a real `core/skills/*.py` module, flags any `<attr>` not
  defined in that module. It only flags references to PRE-EXISTING modules (a symbol introduced
  by the same plan is not flagged), and it ignores leading names that are not core/skills
  modules (stdlib/third-party/pseudocode), to stay low-false-positive.
- [ ] AC-2: `unresolved_api_refs` is wired into the plan-completeness path so a design (M/L)
  or discovery-lite (S) ack is BLOCKED when the impl-plan references a nonexistent attribute of
  a known module. A negative test proves `scan_sentinels.scan(` blocks and `scan_sentinels.scan_diff(`
  passes; the wiring is exercised through the real `can_complete_*` entry point, not the helper.
- [ ] AC-3: Both planning prompts (`core/agents/design.md`, `core/agents/discovery-lite.md`)
  and the test-planner (`core/agents/test-planner.md`) carry a rule: every AC describing a CLI,
  gate, or wired behaviour maps to an end-to-end test at the PUBLIC entry point (not a private
  helper), and every gate/validator AC maps to a negative test (the gate bites) plus a
  fail-closed test (unavailable input is blocked).
- [ ] AC-4: A prompt-regression test (using the KLC-029 harness) asserts the end-to-end +
  negative-test rule is present in all three planning prompts, so the discipline cannot
  silently regress.
- [ ] AC-5: The agent-side self-review (KLC-037) runs `unresolved_api_refs` over the impl-plan
  before emitting and fixes or flags any unresolved reference inline.
- [ ] AC-6: `docs/process.md` documents the plan-quality gate, and the project guidance adds an
  adversarial completeness-audit (fresh subagent over spec/test-plan/impl-plan) as a standard
  step before declaring a ticket build-ready — the planning analog of the mandatory
  code-reviewer.

### Current step — step-1

**plan_quality.unresolved_api_refs extractor**

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

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-051 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-051/impl-plan.md`
- Full spec: `.klc/tickets/KLC-051/spec.md`
- Full test-plan: `.klc/tickets/KLC-051/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-051 step-1` and
run `klc step KLC-051 2` to get the next step's card,
or `klc ack KLC-051 --pick 1` if this was the last step.
