# Build log — KLC-045

## step-1 — gate level on Pick + phases.yml annotations

- Outcome: green
- Commit: fac1673 KLC-045 step-1: gate level on Pick + phases.yml annotations
- Notes: Added `gate: str = "decision"` to `Pick` dataclass; `_GATES` constant; `_build_pick` validates gate and raises `ValueError` on unknown value. All 33 picks in `config/phases.yml` annotated with explicit `gate:` values. 3 new tests pass.

## step-2 — gate_policy.evaluate predicate (fail-closed)

- Outcome: green
- Commit: 928419b KLC-045 step-2: gate_policy.evaluate predicate (fail-closed)
- Notes: New `core/skills/gate_policy.py` with `GateDecision` dataclass and pure `evaluate()` function. `auto` always proceeds, `decision` always pauses, `conditional` checks all 7 required signals with fail-closed missing-key logic. 5 new tests pass.

## step-3 — gate_policy.collect_signals from real skill APIs (fail-closed)

- Outcome: green
- Commit: 6aecec9 KLC-045 step-3: gate_policy.collect_signals from real skill APIs (fail-closed)
- Notes: `collect_signals(ticket, phase_id)` assembles all 7 signals from `phase_completion`, `scope_delta`, `scan_sentinels`, `budget`, `lifecycle`. Any source failure → dirty (fail-closed). `route_confidence` omitted when absent (evaluate treats as dirty). 4 new tests pass.

## step-4 — klc ack --auto applies gate-policy via the real ack path

- Outcome: green
- Commit: 186e997 KLC-045 step-4: klc ack --auto applies gate-policy via the real ack path
- Notes: Added `--auto` flag to `ack.py` argparse. `_resolve_auto_pick` finds the forward pick (goto="next") or the only pick. At `:ack-needed`, if `--auto`, evaluates gate and either applies ack or exits 2 with reasons. Plain `klc ack` path unchanged. 5 new tests pass.

## step-5 — docs parity for gate-policy

- Outcome: green
- Commit: a4d5fd6 KLC-045 step-5: docs parity for gate-policy
- Notes: `docs/process.md` — added "Gate-policy layer (KLC-045)" section with three gate levels table, decision gates list, `klc ack --auto` usage, and seven signals table.

## Codex fixes (post-review)

- Commit: b75a370 KLC-045 codex fixes: phase-aware verdict, sentinel cwd, review-report updates
- MEDIUM-1: Added `_PRE_REVIEW_PHASES` frozenset; `collect_signals` returns `"N/A"` for verdict at pre-review phases; `"N/A"` added to clean values in `_CHECK["verdict"]`. Removed artificial `review-report.md` from test fixture.
- MEDIUM-2: Added `cwd=str(_project_root())` to subprocess call in `_sentinel_hits`.
- Added `test_collect_signals_pre_review_verdict_na` test.

## Evidence

```
$ PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_gate_policy.py -q
17 passed in 0.42s

$ PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/ -q --ignore=tests/fixtures 2>&1 | tail -3
475 passed in 4.91s
```
