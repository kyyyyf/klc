---
ticket: KLC-045
reviewer: internal + external subagent (fresh code-reviewer) + codex
review_depth: full
date: 2026-06-26
---

# KLC-045 Review Report

## Scope

Branch: `feature/klc-045`
Changed files: `config/phases.yml`, `core/skills/phases.py`,
`core/skills/gate_policy.py` (new), `core/phases/ack.py`,
`tests/integration/test_gate_policy.py` (new), `docs/process.md`.

## AC Coverage

| AC | Status | Notes |
|----|--------|-------|
| AC-1 | PASS | `Pick.gate: str = "decision"` added; `_build_pick` validates against `_GATES`; raises `ValueError` on unknown value (fail-closed load). |
| AC-2 | PASS | Every pick in `phases.yml` has an explicit `gate:`. Decision gates: discovery-lite approve, discovery approve, all design option picks (1–3), design needs-rework and revise-impl-plan, manual passed/failed, integrate merged. All other forward-progress picks are `conditional`. |
| AC-3 | PASS | `evaluate()` is a pure function (no I/O): `auto` → always proceed; `decision` → always pause with reason; `conditional` → checks all `_REQUIRED_SIGNALS`, fail-closed on missing keys. |
| AC-4 | PASS | `collect_signals` assembles all 7 signals from real skill APIs. `route_confidence` is omitted when absent (evaluate treats missing as dirty). Every source failure wrapped in try/except → dirty value. `_sentinel_hits` writes git diff to temp file and calls `scan_sentinels.scan_diff`. `_read_verdict` reads `review-report.md` ## Verdict section. Phase-aware: pre-review phases return `"N/A"` for verdict (clean sentinel; see MEDIUM-1 fix). |
| AC-5 | PASS | `--auto` flag added to argparse. At `:ack-needed`, `_resolve_auto_pick` finds the forward pick; evaluates; either applies ack or exits non-zero with reasons. Manual `klc ack` path unchanged (behind `else` branch). |
| AC-6 | PASS | `test_decision_never_auto` confirms decision picks never auto-ack even with all-clean signals. `test_ack_auto_refuses_risky` and `test_ack_auto_refuses_low_route_confidence` confirm risk signals force pause on conditional picks. |

## Findings

### Internal code-reviewer subagent findings

#### MEDIUM-1 — Duplicate signal-dict definitions in test file

**Description**: `_CLEAN_SIG`, `_SCOPE_DIRTY_SIG`, `_LOW_RC_SIG` were defined twice (lines 392–411 and 413–431). Copy-paste artifact from editing.

**Fix applied**: Removed the first duplicate set. One canonical definition remains.

#### MEDIUM-2 — `test_ack_auto_proceeds_clean` asserted negative direction only

**Description**: Asserted `state != "build:ack-needed"` but not the exact target state.

**Fix applied**: Strengthened to `assert state == "review:work"`.

#### MEDIUM-3 — `budget_overrun` includes `mutation_fix_attempts`, producing dual dirty reasons

**Assessment**: Won't fix. Per spec, these are two separate signals with separate semantics. The redundant reason in the output is acceptable.

#### MEDIUM-4 — `_resolve_auto_pick` fallback; no test for `None` return path

**Assessment**: Won't fix in this ticket. Gate check protects against misuse. Test deferred to KLC-046.

### Codex external review findings (from `.klc/tickets/KLC-045/codex_review.md`)

#### MEDIUM-1 (codex) — `ack --auto` on build requires review-report that cannot exist yet

**Description**: `collect_signals` always read `verdict` from `review-report.md`. At `build:ack-needed`, this file does not yet exist. `_read_verdict` returned `"NO_REPORT"` (dirty), so `--auto` on any build-phase conditional pick always paused — defeating the purpose of the `conditional` gate on build.

**Fix applied**:
- Added `_PRE_REVIEW_PHASES` frozenset in `gate_policy.py`.
- `collect_signals` now returns `"N/A"` for `verdict` when `phase_id` is in `_PRE_REVIEW_PHASES`.
- Added `"N/A"` to the clean values in `_CHECK["verdict"]`.
- Removed the artificial `review-report.md` from `_make_build_ticket` test fixture (it was created to paper over the bug).
- Added `test_collect_signals_pre_review_verdict_na` to assert N/A is returned at build phase and is treated as clean by `evaluate`.

#### MEDIUM-2 (codex) — Sentinel scan uses process cwd, not PROJECT_ROOT

**Description**: `_sentinel_hits` ran `subprocess.run(["git", "diff", "main..HEAD"])` without `cwd`, so it scanned from the current process working directory rather than the project root. Could return wrong results if invoked from a different directory or with a different working tree.

**Fix applied**: Added `cwd=str(_project_root())` to the subprocess call in `_sentinel_hits`, matching the pattern used in `scope_delta._git_changed_files`.

## Full suite

```
$ python3 -m pytest tests/ -q --ignore=tests/fixtures
17 gate-policy tests + 458 existing tests
all passed
```

## Verdict

APPROVED

All six ACs are satisfied. Four findings from two review passes were assessed: two fixed (codex MEDIUM-1 and MEDIUM-2), two fixed from internal review (duplicate dicts, weak assertion), and two won't-fixed with rationale (MEDIUM-3 dual-reason, MEDIUM-4 None-path test deferred to KLC-046). No correctness issues remain.
