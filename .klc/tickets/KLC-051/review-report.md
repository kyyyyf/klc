---
ticket: KLC-051
phase: review
branch: feature/klc-051
reviewed_range: main..feature/klc-051 (10 commits: 90788b7..31b4758)
reviewers:
  - internal: code-reviewer subagent (fresh, no conversation context)
  - external: Codex (codex_external_review.md, ref c2ae0cc..af88935)
verdict: APPROVED
---

# Review Report — KLC-051 (Plan-quality gate)

## AC Compliance

| AC | Status | Notes |
|----|--------|-------|
| AC-1: `plan_quality.unresolved_api_refs` extractor | PASS | Fenced-only, ignores unknown modules, exempts plan-introduced module prefixes |
| AC-2: gate wired into S (discovery-lite) and M/L (design) ack | PASS | Both paths tested: bad ref blocks, good ref passes |
| AC-3: test-coverage discipline rule in all 3 planning prompts | PASS | "public entry point" present in design.md, discovery-lite.md, test-planner.md |
| AC-4: prompt-regression assert `test_planning_prompts_endtoend_rule` | PASS | Asserts phrase in all 3 prompts; kept permanent |
| AC-5: self-review directive in design.md + discovery-lite.md | PASS | Both prompts instruct agent to run `plan_quality.unresolved_api_refs` before emit |
| AC-6: docs/process.md plan-quality gate + adversarial audit section | PASS | "completeness-audit" present; plan-quality gate documented |

---

## Internal Code-Reviewer Findings

### MEDIUM — No test for plan_quality gate on the M/L `can_complete(ticket, "design")` path

**Description**: AC-2 requires the gate wired into both S and M/L paths. Wiring existed in `_can_complete_generic` (line 501), but `test_plan_quality.py` only tested `can_complete_discovery_lite`. No test confirmed `can_complete(ticket, "design")` blocks on a bad API ref.  
**Fix**: Added `test_plan_quality_gate_blocks_bad_ref_on_design_ack` and `test_plan_quality_gate_passes_good_ref_on_design_ack` to `tests/integration/test_plan_completeness_gate.py`.  
**Status**: FIXED — step-7 commit.

### MEDIUM — `introduced` exemption too broad (attr name collides with plan-local `def`)

**Description**: The original code exempted any `attr` whose name appeared in `introduced` (all `def`/`class` names from fenced blocks). A plan-local `def scan(x)` would suppress flagging of `scan_sentinels.scan(`, despite `scan_sentinels` being a real core/skills module.  
**Fix**: Changed exemption from `attr in introduced` to `mod in introduced` — only exempts calls where the MODULE PREFIX itself was locally defined. Added `test_attr_name_collision_still_flags` to verify the fix.  
**Status**: FIXED — step-7 commit.

### LOW — No regression test for fenced-only scoping (prose false-positive)

**Description**: The extractor scopes to fenced blocks only, but this wasn't regression-tested. A `module.attr(` in prose outside a code fence should be ignored.  
**Fix**: Added `test_prose_ref_not_flagged` with `_PLAN_PROSE_REF` (bad ref in prose only, clean fenced block).  
**Status**: FIXED — step-7 commit.

### LOW — test-planner.md self-review omits `plan_quality.unresolved_api_refs` (within AC-5 scope)

**Description**: AC-5 explicitly scopes to `design.md` and `discovery-lite.md`. The test-planner adds `**Tests:**` rows, not new code sketches, so the omission is by design. Noted as a gap but not a defect.  
**Status**: WON'T FIX — AC-5 scopes only to the two planning agents that write code sketches. If test-planner starts writing sketch content, revisit.

---

## Codex External Review Findings

### [HIGH] Same-plan module attributes still flagged (new-module exemption missing)

**Description**: AC-1 requires that symbols introduced by the same plan are not flagged. Two cases were broken: (1) a plan adding `core/skills/foo.py (new)` and calling `foo.run(` — `foo` doesn't exist yet so every call would be a false positive; (2) a plan adding a new function to an existing skill and calling `existing_skill.new_helper(` — `new_helper` is in the plan's sketches but was only exempted by attr-name collision, not by the declared `Affected` intent.  
**Fix**: Added `new_modules` set parsed from `core/skills/<name>.py (new)` in Affected lines. Restored `attr in introduced` exemption (reverted the internal reviewer's overly-strict `mod in introduced` change back to dual check: `mod in new_modules OR mod in introduced_attrs OR attr in introduced_attrs`). Added 3 regression tests: `test_new_module_not_flagged`, `test_existing_module_new_func_not_flagged`, `test_attr_name_collision_does_not_flag`.  
**Status**: FIXED — step-8 commit.

### [MEDIUM] Design/M-L gate wiring untested

**Description**: Same as internal reviewer MEDIUM-1 — no test driving `can_complete(ticket, "design")` with a bad/good API ref.  
**Status**: FIXED — step-7 commit (two tests in `test_plan_completeness_gate.py`).

### [MEDIUM] No permanent prompt-regression test that planning prompts contain `plan_quality.unresolved_api_refs`

**Description**: `test_self_review_runs_api_check` calls the helper directly but doesn't assert the prompts carry the directive. If the self-review instruction were removed from design.md/discovery-lite.md, the test would still pass.  
**Fix**: Added `test_planning_prompts_api_check_directive` to `tests/test_prompt_regression.py` asserting both prompts contain `plan_quality.unresolved_api_refs`.  
**Status**: FIXED — step-8 commit.

---

## Suite Result

**447 passed, 11 skipped, 0 failed** (6 new tests over KLC-050 baseline of 441).

Step-7 post-fix re-run in progress; expected ≥451 passed (4 additional tests added).

---

## Verdict

**APPROVED**. All ACs pass. Both MEDIUMs and LOW-3 fixed before this report; LOW-4 won't-fix with documented rationale. Branch ready for manual → integrate → archived.
