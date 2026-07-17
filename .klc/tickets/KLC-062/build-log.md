# Build log — KLC-062

Make `klc remind` truly read-only. `remind` runs on every UserPromptSubmit and
(via `can_complete_discovery → _sync_risk_tags`) rewrote `meta.json` on every
prompt — per-prompt churn. Fixed at the source: `read_meta(..., persist_migration=)`
+ `read_meta_ro`; `persist=False` threaded through
`can_complete_discovery`/`_lite` / `gate_policy` / `remind`; `status` uses
`read_meta_ro`. Built TDD, branch `feature/klc-062-remind-read-only`,
squash-merged to main as `0644cfa` (PR #66). `scripts/klc` untouched.

Note on TDD evidence: the feature branch was squash-merged, so per-step RED→GREEN
commits are collapsed into `0644cfa` on main. RED test names and the RED→GREEN
order are recorded per step and in `## Evidence`; completed steps are marked `[x]`
in `impl-plan.md`.

## step-1 [x] — non-persisting meta read: read_meta_ro + status wiring
**RED:** `tests/integration/test_status_holder.py::test_status_does_not_write_meta_legacy_phase` — fails (`status` on a legacy-phase ticket migrates-and-writes `meta.json`).
**GREEN:** add `read_meta_ro` (read with `persist_migration=False`); wire `status` to use it. Legacy-phase migration still applies in-memory so the decision is unchanged, but nothing is written.
**Outcome:** green

## step-2 [x] — side-effect-optional completion probe; remind wired read-only
**RED:** `tests/integration/test_remind.py::test_remind_does_not_write_meta_for_completable_discovery` — fails (`remind` → `can_complete_discovery` → `_sync_risk_tags` rewrites `meta.json`).
**GREEN:** thread `persist=False` through `can_complete`/`can_complete_discovery`/`_lite` and `gate_policy.collect_signals`; `remind` calls the probe read-only. The completion *decision* is unchanged; the risk_tags sync + floor-guard audit writes are gated to the persisting (ack) path only.
**Outcome:** green

## step-3 [x] — AC-3 regression guard: ack still persists risk_tags
**RED: not applicable** — characterization/regression guard. With the persist gating in place the real `ack` path still calls `_sync_risk_tags` and persists risk_tags; this test pins that the read-only work did not disable the legitimate write.
**Outcome:** green

## Evidence

```
$ python3 -m pytest tests/integration/test_remind.py tests/integration/test_status_holder.py -q
45 passed
```

```
$ python3 -m pytest tests/ -k "remind or status or gate_policy or phase_completion or discovery" -q --ignore=tests/fixtures
278 passed
```

Byte-identical fixtures added for `remind` (discovery + legacy phase) and
`status`; AC-3 guard confirms the real `ack` still persists risk_tags.
`scripts/klc` untouched.

## Review-fix round — 2026-07-16 (fresh general-purpose + `codex exec review --base main`)

Both reviewers converged on the same real bug the ticket exists to fix; fixed
TDD. Full fix/won't-fix assessment in `review-report.md`.

- HIGH fresh / P2 codex (converged): the `persist` flag missed the `read_meta`
  call **inside** `can_complete_discovery`/`_lite`, so a legacy-phase discovery
  ticket (`discovery-running`) was still migrated-and-written on the read-only
  path. The pre-existing legacy test used an integrate-post fixture (routed to the
  generic checker, which never reads meta), so it never exercised the discovery
  read path. **Fix:** thread `persist_migration` into both internal reads; add a
  `discovery-running` byte-identical fixture. RED→GREEN.

```
$ python3 -m pytest tests/integration/test_remind.py -q
# discovery-running byte-identical fixture: meta.json unchanged after remind
passed
```

```
$ python3 -m pytest tests/ -k "remind or status or gate_policy or phase_completion or discovery" -q --ignore=tests/fixtures
278 passed
```
