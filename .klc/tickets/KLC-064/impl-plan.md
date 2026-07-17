# Implementation plan — KLC-064 (throttled feature-ON heartbeat)

> **Merge-order:** land AFTER KLC-061 (`feature/klc-061-wrap-verbs-state-tx`) is
> merged — steps reuse the `state_tx` holder envelope 061 establishes. Rebase this
> branch onto the merged 061 before build. Align with KLC-062's read-only meta
> probe (soft dep). See spec.md D-061/D-062.

## step-1 — throttle constant + `klc heartbeat` verb (feature-ON write via state_tx)

**Goal:** Add `HEARTBEAT_PUSH_INTERVAL_SECONDS = HOLDER_TTL_SECONDS // 3` and a
`core/phases/heartbeat.py` `run(argv)` that, feature-ON, refreshes an
identity-held `:work` ticket's `heartbeat_at` and CAS-pushes it through
`state_tx` — but only when the throttle window has elapsed. Register in
`scripts/klc`.
**RED:** `tests/integration/test_heartbeat.py::test_feature_on_first_push_advances_heartbeat_at_at_origin` and `::test_long_hold_active_holder_not_stealable` — fail (no command, no propagation).
**GREEN:** `heartbeat.py`: feature-OFF guard → returns 0; else read-only meta probe, require holder held-by-me and phase `:work`, throttle on `age(heartbeat_at else since) < HEARTBEAT_PUSH_INTERVAL_SECONDS`, else `with acquire_lock: with state_tx(...) as tx: if tx: holder.heartbeat_holder(ticket)`. Wrap all in try/except → exit 0. Add `HEARTBEAT_PUSH_INTERVAL_SECONDS` to `holder.py`; add `"heartbeat"` to `LIFECYCLE_CMDS` + `NO_DRAIN_CMDS`.
**VERIFY:** `PROJECT_ROOT="$(git rev-parse --show-toplevel)" python3 -m pytest tests/integration/test_heartbeat.py -k "first_push or long_hold" -q`
**Expected:** `2 passed`
**COMMIT:** `KLC-064 step-1: klc heartbeat — throttled feature-ON heartbeat_at push`
**Affected files:** `core/skills/holder.py`, `core/phases/heartbeat.py`, `scripts/klc`, `tests/integration/test_heartbeat.py`
**Interfaces:** `heartbeat.run(argv: list[str]) -> int` (always 0); `holder.HEARTBEAT_PUSH_INTERVAL_SECONDS: int`. No change to `heartbeat_holder`.
**Depends on:** KLC-061 (state_tx holder envelope)
**Code sketch:**
```python
# core/phases/heartbeat.py  (best-effort; always returns 0)
def run(argv):
    try:
        if not state_feature.enabled():
            return 0                              # feature-OFF: no-op, byte parity
        identity = _git_user()                    # non-raising (like remind)
        for ticket in _identity_held_work_tickets(identity):  # read-only probe
            try:
                h = _read_meta_readonly(ticket)["holder"]     # KLC-062 side-effect-free read
                last = h.get("heartbeat_at") or h.get("since")
                if _age_seconds(last) < holder.HEARTBEAT_PUSH_INTERVAL_SECONDS:
                    continue                      # throttled: no write / no push
                with acquire_lock(ticket):
                    with state_tx(ticket, f"heartbeat {ticket}") as tx:  # KLC-061 envelope
                        if tx is not None:
                            holder.heartbeat_holder(ticket)   # write + glob-commit + CAS-push
            except Exception:
                continue                          # one bad ticket never aborts the rest
        return 0
    except Exception:
        return 0
```

## step-2 — non-blocking UserPromptSubmit hook

**Goal:** Fire `klc heartbeat` on every agent turn so `heartbeat_at` advances
during a long single phase; per-prompt cost is the cheap throttle read, the push
happens ≤ once per window.
**RED:** `tests/integration/test_heartbeat.py::test_hook_exits_0_on_child_failure` and `::test_within_window_is_readonly_noop` — fail (no hook; churn on repeat).
**GREEN:** `klc-plugin/hooks/heartbeat.py` — near-copy of `remind.py` running `[*klc_cmd, "heartbeat"]` with timeout, swallow all errors, return 0, do NOT forward stdout (silent). Add a third `UserPromptSubmit` block to `klc-plugin/hooks/hooks.json`.
**VERIFY:** `PROJECT_ROOT="$(git rev-parse --show-toplevel)" python3 -m pytest tests/integration/test_heartbeat.py -k "hook or readonly_noop or at_most_one_push" -q`
**Expected:** `3 passed`
**COMMIT:** `KLC-064 step-2: throttled UserPromptSubmit heartbeat hook`
**Affected files:** `klc-plugin/hooks/heartbeat.py`, `klc-plugin/hooks/hooks.json`, `tests/integration/test_heartbeat.py`
**Interfaces:** hook `main() -> int` (always 0); `hooks.json` +1 UserPromptSubmit entry.
**Depends on:** step-1
**Code sketch:**
```python
# klc-plugin/hooks/heartbeat.py  (mirrors remind.py; silent)
def main() -> int:
    klc_cmd = shlex.split(os.environ.get("KLC_BIN", "klc"))
    try:
        subprocess.run([*klc_cmd, "heartbeat"], capture_output=True,
                       text=True, timeout=10)
    except Exception:
        return 0
    return 0     # non-blocking; heartbeat is silent (no stdout forward)
```

## step-3 — feature-OFF parity + best-effort hardening + docstring truth-up

**Goal:** Lock feature-OFF byte-parity and best-effort-never-crash, and fix the
now-true "kept fresh by heartbeat_holder" docstrings to name `klc heartbeat` + the
hook.
**RED:** `tests/integration/test_heartbeat.py::test_feature_off_meta_byte_identical` and `::test_advisory_never_crashes_exits_0` — fail until the feature-OFF hard guard and error-swallowing are in place.
**GREEN:** Confirm the feature-OFF top guard and per-ticket try/except cover missing identity, corrupt meta, absent holder, and pull/push failure; assert `meta.json` bytes unchanged feature-OFF. Update docstrings in `core/phases/steal.py:5` and `core/skills/holder.py`.
**VERIFY:** `PROJECT_ROOT="$(git rev-parse --show-toplevel)" python3 -m pytest tests/integration/test_heartbeat.py -q`
**Expected:** all passed
**COMMIT:** `KLC-064 step-3: feature-OFF parity, best-effort, docstrings`
**Affected files:** `core/phases/heartbeat.py`, `core/phases/steal.py`, `core/skills/holder.py`, `tests/integration/test_heartbeat.py`
**Interfaces:** none
**Depends on:** step-2

## step-4 — steal-vs-heartbeat property/fuzz test on a REAL bare-repo substrate

**Goal:** Prove the AC-5 coherence invariant across many heartbeat/steal
interleavings on a real `klc-state` bare-repo fixture (two worktrees), not stubs —
the KLC-057 real-substrate lesson.
**RED:** `tests/integration/test_heartbeat_race.py::test_steal_vs_heartbeat_coherence_over_interleavings` — fails until steps 1-3 land and compose with KLC-061's `state_tx`-wrapped `steal`.
**GREEN:** Build a bare `klc-state` origin + two worktrees (A holds & heartbeats, B steals). Enumerate/randomize orderings of A's throttled heartbeat push and B's steal; after each, assert the race invariant (see test-plan.md). CAS serialization must make exactly one writer win per race.
**VERIFY:** `PROJECT_ROOT="$(git rev-parse --show-toplevel)" python3 -m pytest tests/integration/test_heartbeat_race.py -q`
**Expected:** all passed
**COMMIT:** `KLC-064 step-4: steal-vs-heartbeat race property test (real substrate)`
**Affected files:** `tests/integration/test_heartbeat_race.py`, `tests/integration/conftest.py` (bare-repo fixture if not already shared)
**Interfaces:** none (test-only)
**Depends on:** step-3, KLC-061
