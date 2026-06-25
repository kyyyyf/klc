---
ticket: KLC-050
kind: impl-plan
design_choice: option-A-minimal
last_generated: 2026-06-24
---

# KLC-050 — Implementation plan (executable, for Sonnet)

Build target: four independent gate-hardening fixes. Per-step contract: **Goal / RED /
Interfaces / Expected / VERIFY / COMMIT / Affected / Code sketch / Depends-on**. Run after
each step: `python3 -m pytest tests/ -q --ignore=tests/fixtures`. COMMIT subjects verbatim.

## step-1 — broaden the no-pre-judgment lint

- **Goal:** catch contractions and paraphrases of pre-judgment directives. (AC-1)
- RED: add `test_lint_catches_paraphrases` + `test_lint_ignores_benign` to
  `tests/integration/test_no_pre_judgment_lint.py`. Fails today (narrow patterns).
- **Interfaces:** extend `_PATTERNS` in `core/skills/lint_review_prompts.py` to cover
  `don'?t flag`, `ignore (this|the) (issue|finding|file)`, `treat .*as (minor|trivial)`,
  `downgrade (it|this|the severity)`.
- **Expected:** the four phrasings are flagged; benign prose ("should not ignore edge cases")
  is not.
- **VERIFY:** `python3 -m pytest tests/integration/test_no_pre_judgment_lint.py -q`
- **COMMIT:** `KLC-050 step-1: broaden no-pre-judgment lint to contractions and paraphrases`
- **Affected:** `core/skills/lint_review_prompts.py`,
  `tests/integration/test_no_pre_judgment_lint.py`.
- Depends-on: none.
- **Code sketch:**

```python
_PATTERNS += [
    re.compile(r"(?i)don'?t\s+flag"),
    re.compile(r"(?i)ignore\s+(this|the)\s+(issue|finding|file)"),
    re.compile(r"(?i)treat\b.*\bas\s+(minor|trivial)"),
    re.compile(r"(?i)downgrade\s+(it|this|the\s+severity)"),
]
```

## step-2 — placeholder-aware recorded_pick

- **Goal:** reject a verbatim template pick as a real decision. (AC-2)
- RED: add `test_recorded_pick_rejects_placeholder` AND `test_recorded_pick_accepts_concrete`
  to `tests/integration/test_socratic_gate.py`. The accept-case MUST include
  `Picked: Option A — reason` with trailing whitespace to catch the `\s*$`
  false-positive (a naive regex would wrongly reject a real pick whose line has trailing
  spaces), plus a `DECISION D-001`-only spec (no Picked line) → True.
- **Interfaces:** in `core/skills/spec_structure.py`, `recorded_pick` returns False when the
  text after the pick label is empty, an angle-bracket placeholder, or a to-be-decided
  marker, and keeps the `DECISION D-NNN` alternate marker working.
- **Expected:** a placeholder pick (angle-bracket or to-be-decided) returns False; a concrete
  `Picked: Option A — reason` and a `DECISION D-001` marker return True.
- **VERIFY:** `python3 -m pytest tests/integration/test_socratic_gate.py -k recorded_pick -q`
- **COMMIT:** `KLC-050 step-2: recorded_pick rejects placeholder picks`
- **Affected:** `core/skills/spec_structure.py`, `tests/integration/test_socratic_gate.py`.
- Depends-on: none.
- **Code sketch:**

```python
# capture the pick text, strip it, THEN classify — avoids the trailing-\s false positive
_PICK_RE = re.compile(r"(?im)^\s*Picked:\s*(.*?)\s*$")
def recorded_pick(text):
    if _DECISION_RE.search(text): return True
    m = _PICK_RE.search(text)
    if not m: return False
    val = m.group(1).strip()
    if not val: return False                       # empty
    if re.fullmatch(r"<[^>]*>|TBD", val, re.I): return False  # placeholder
    return True
```

## step-3 — strict model-on-subagent guard

- **Goal:** reject a subagent dispatch with no resolved model, not just warn — AND prove the
  refusal at the PUBLIC dispatch path, not only the helper. (AC-3)
- RED:
  - `test_model_guard_strict_rejects` — `require_subagent_model(None)` raises `ValueError`.
  - `test_runner_refuses_dispatch_without_model` — call the runner's dispatch entry (the
    function wrapping `runner.py:318`'s `check_subagent_dispatch` call) with a `resolved`
    lacking a model, with the actual subprocess/dispatch MOCKED; assert it raises/returns
    non-zero AND the mocked dispatch was NOT invoked (zero calls). This is the wiring proof —
    a helper that raises in isolation is not enough.
  - `test_build_orchestrator_refuses_dispatch_without_model` — same assertion at the
    `build_orchestrator.py:144` dispatch site.
- **Interfaces:** `model_guard.require_subagent_model(resolved) -> None` raises `ValueError`
  when no model is resolved. The two real call sites consult it BEFORE dispatching: the
  function in `core/skills/runner.py` around line 318 (currently only `sys.stderr.write`s the
  note) and the dispatch in `core/skills/build_orchestrator.py` around line 144. The existing
  soft `check_subagent_dispatch` NOTE is KEPT for the `source=="default"` fallback case —
  that is a different condition (a model resolved, but via default tier) from `model is None`.
- **Expected:** a missing model raises and NO dispatch/subprocess is invoked at either call
  site; a resolved model dispatches unchanged; the soft default-fallback note still prints.
- **VERIFY:** `python3 -m pytest tests/integration/test_model_subagent_guard.py -q`
- **COMMIT:** `KLC-050 step-3: model guard rejects dispatch with no resolved model (both call sites)`
- **Affected:** `core/skills/model_guard.py`, `core/skills/runner.py`,
  `core/skills/build_orchestrator.py`, `tests/integration/test_model_subagent_guard.py`.
- Depends-on: none.
- **Code sketch:**

```python
def require_subagent_model(resolved):
    if resolved is None or not getattr(resolved, "model", None):
        raise ValueError("subagent dispatch requires a resolved model (models.yml)")
# runner.py ~318 and build_orchestrator.py ~144, BEFORE the dispatch/subprocess call:
require_subagent_model(resolved)   # raises -> dispatch never runs
```

## step-4 — unify step parser + retire stale templates

- **Goal:** one `## step-N` parser feeding both call sites WITHOUT breaking the existing
  consumer, and no stale plan templates. (AC-4, AC-5)
- RED: add `test_single_step_parser` (the ADAPTED `phase_completion._impl_plan_steps` output
  still yields `step:int` and `red_not_applicable` for a sample plan — what its consumer at
  `phase_completion.py:466` needs) and `test_plan_template_renders_gate_passing`.
- **Interfaces:** the two parsers differ in OUTPUT SHAPE — `impl_plan_check.parse_impl_plan_steps`
  returns `{id, title, body}`; `phase_completion._impl_plan_steps` returns
  `{step:int, red_not_applicable:bool}` and its caller at `phase_completion.py:466` relies on
  those keys. So `_impl_plan_steps` must DELEGATE to the survivor AND ADAPT its output (map
  `id="step-3"` → `step=3`; derive `red_not_applicable` from the body) — not return the raw
  survivor list, which would break the consumer. The stale `core/templates/impl-plan*.j2`
  (grep-confirmed unreferenced) are removed.
- **Expected:** the adapted `_impl_plan_steps` matches the old output on a sample plan (the
  line-466 consumer still works); the duplicate parsing regex is gone; no template caller breaks.
- **VERIFY:** `python3 -m pytest tests/test_impl_plan_check.py tests/integration/test_tdd_order_gate.py -q`
- **COMMIT:** `KLC-050 step-4: unify step parser (with adapter) and retire stale plan templates`
- **Affected:** `core/skills/phase_completion.py`, `core/skills/impl_plan_check.py`,
  `core/templates/impl-plan.md.j2`, `core/templates/impl-plan-short.md.j2`,
  `tests/test_impl_plan_check.py`.
- Depends-on: none.
- **Code sketch:**

```python
# phase_completion.py — delegate to the one parser, then ADAPT to the consumer's shape
from impl_plan_check import parse_impl_plan_steps
def _impl_plan_steps(ticket_dir):
    p = ticket_dir / "impl-plan.md"
    if not p.exists(): return []
    out = []
    for s in parse_impl_plan_steps(p.read_text()):
        out.append({"step": int(s["id"].split("-")[1]),
                    "red_not_applicable": "not applicable" in s["body"].lower()})
    return out
```

## step-5 — docs parity

- **Goal:** note the hardened gates in the process docs. (AC-1 through AC-5)
- RED: not applicable — docs-only step. Rule cited: AC-1 through AC-5 + the quality review.
- **Interfaces:** prose only — `docs/process.md` notes the broadened lint, placeholder-aware
  pick, strict model guard, and single step parser.
- **Expected:** `grep -rn "placeholder-aware\|strict model guard" docs/process.md` returns
  the new content.
- **VERIFY:** `grep -rn "strict model guard" docs/process.md`
- **COMMIT:** `KLC-050 step-5: docs parity for hardened gates`
- **Affected:** `docs/process.md`.
- Depends-on: step-1, step-2, step-3, step-4.
- **Code sketch:** not applicable — documentation prose only (RED not applicable).

## Notes for the implementer

- One logical commit per step; COMMIT subjects verbatim. Build after KLC-049 so the suite is
  green to verify against.
- Hardening only: every previously-valid input must still pass. Add negative fixtures so the
  broadened lint and pick checks do not over-match.
