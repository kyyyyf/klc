---
ticket: KLC-045
kind: impl-plan
design_choice: option-A-minimal
last_generated: 2026-06-24
---

# KLC-045 — Implementation plan (executable, for Sonnet)

Build target: a `gate` level on every pick, a pure auto-proceed predicate, a signal
collector, and a `klc ack --auto` hook. Per-step contract: **Goal / RED / Interfaces /
Expected / VERIFY / COMMIT / Affected / Code sketch / Depends-on**. Run after each step:
`python3 -m pytest tests/ -q --ignore=tests/fixtures`. COMMIT subjects verbatim.

## step-1 — gate field on Pick + phases.yml annotations

- **Goal:** parse a `gate` level per pick and require it on every pick. (AC-1, AC-2)
- RED: not applicable — tests and implementation were developed concurrently in one commit
  (`fac1673 [mixed]`). Tests exist and pass; separate RED commit not committed.
  Original intent: `test_pick_gate_field_parsed`, `test_every_pick_has_gate`.
- **Interfaces:** `Pick.gate: str` (default `"decision"`) in `core/skills/phases.py`;
  `_parse_pick` reads `gate`, raising on a value outside `{auto, conditional, decision}`;
  a `gate:` line on every pick in `config/phases.yml`.
- **Expected:** known values parse; unknown raises at load; all picks annotated.
- **VERIFY:** `python3 -m pytest tests/integration/test_gate_policy.py -k gate_field -q`
- **COMMIT:** `KLC-045 step-1: gate level on Pick + phases.yml annotations`
- **Affected:** `core/skills/phases.py`, `config/phases.yml`,
  `tests/integration/test_gate_policy.py` (new).
- Depends-on: none.
- **Code sketch:**

```python
_GATES = {"auto", "conditional", "decision"}
def _parse_pick(d, phase_id):
    gate = d.get("gate", "decision")
    if gate not in _GATES:
        raise ValueError(f"phase {phase_id!r} pick {d.get('id')}: bad gate {gate!r}")
    return Pick(id=..., label=..., goto=..., supersede=..., gate=gate)
```

## step-2 — evaluate() predicate (fail-closed)

- **Goal:** a pure function mapping gate + signals to a proceed/pause decision, where a
  MISSING signal key is treated as dirty (fail-closed), not clean. (AC-3, AC-6)
- RED: not applicable — tests and implementation were developed concurrently in one commit
  (`928419b [impl]`). Tests exist and pass; separate RED commit not committed.
  Original intent: `test_evaluate_auto_conditional_decision`, `test_evaluate_missing_signal_is_dirty`.
- **Interfaces:** `core/skills/gate_policy.py` — `@dataclass GateDecision(proceed: bool,
  reasons: list[str])`; `evaluate(gate: str, signals: dict) -> GateDecision`. The seven
  expected keys are fixed in `_REQUIRED_SIGNALS`; a key absent from `signals` is dirty.
- **Expected:** auto→proceed; decision→pause; conditional with all seven keys clean→proceed;
  conditional with any dirty OR any missing key→pause with one reason per offending key.
- **VERIFY:** `python3 -m pytest tests/integration/test_gate_policy.py -k evaluate -q`
- **COMMIT:** `KLC-045 step-2: gate_policy.evaluate predicate (fail-closed)`
- **Affected:** `core/skills/gate_policy.py` (new), `tests/integration/test_gate_policy.py`.
- Depends-on: step-1.
- **Code sketch:**

```python
_REQUIRED_SIGNALS = ("advisory", "scope_expansion", "sentinels", "mutation",
                     "budget_overrun", "verdict", "route_confidence")
# a signal is clean only when present AND its checker passes; missing => dirty
_CHECK = {
  "advisory": lambda v: not v,
  "scope_expansion": lambda v: v is False,
  "sentinels": lambda v: v is False,
  "mutation": lambda v: v is False,
  "budget_overrun": lambda v: v is False,
  "verdict": lambda v: v in ("approve", "APPROVED", "PASS", "clean"),
  "route_confidence": lambda v: v in ("high", "medium"),
}
def evaluate(gate, signals):
    if gate == "auto": return GateDecision(True, [])
    if gate == "decision": return GateDecision(False, ["decision gate — human required"])
    bad = [k for k in _REQUIRED_SIGNALS
           if k not in signals or not _CHECK[k](signals[k])]
    return GateDecision(not bad, [f"{k} not clean" for k in bad])
```

## step-3 — collect_signals() against the REAL skill APIs

- **Goal:** assemble all seven signals from the real skills, with every helper defined and
  every call matched to the actual API. No undefined helpers, no invented functions. (AC-4, AC-6)
- RED: add `test_collect_signals_clean` (a fixture ticket with no expansion / no sentinel /
  clean budgets → every value clean) AND `test_collect_signals_dirty` (a fixture with a real
  scope expansion via a planted modules mismatch, a real sentinel hit in the diff, and a
  budget counter at its limit → those values come back DIRTY). Shape-only assertions are NOT
  sufficient — assert the dirty VALUES, so a stub returning clean constants fails.
- **Interfaces / real APIs (verified):**
  - `advisory`: `phase_completion.can_complete(ticket, phase_id)` returns `(ok, advisory)`;
    use the advisory string (empty when clean).
  - `scope_expansion`: `scope_delta.compare(ticket)` returns a dict; dirty when
    `delta.get("expansion")` is truthy OR `delta.get("skipped")` is set (unavailable → dirty).
  - `sentinels`: `scan_sentinels` has NO `scan(ticket)`. The real API is
    `scan_sentinels.scan_diff(diff_path, config)`. Helper `_sentinel_hits(ticket)` writes the
    ticket's branch diff to a temp file (`git diff <base>..HEAD`), calls `scan_diff`, returns
    True on any hit; on any error (no git, no diff) → dirty (True).
  - `mutation`: `_budget_at_limit(ticket, "mutation_fix_attempts")` (see budget reuse below).
  - `budget_overrun`: `any(_budget_at_limit(ticket, c) for c in budget._load_limits())`.
  - `verdict`: there is NO machine-readable verdict field. Helper `_read_verdict(ticket)`
    reads `review-report.md`: returns `"PASS"` only when the file exists and its `## Verdict`
    section contains PASS/APPROVED and no "CHANGES REQUESTED"/"NEEDS_FIX"; missing file or
    request-changes → a dirty value. (A follow-up may add a `meta.verdict` field; for now the
    report is the source.)
  - `route_confidence`: `lifecycle.read_meta(ticket).get("route_confidence")` (written by
    intake.py:223). Missing → omit the key (evaluate treats absent as dirty).
- **Expected:** clean fixture → all seven clean; dirty fixture → the planted signals are dirty;
  an unavailable source (no modules.json, no git, no review-report) yields dirty, never clean.
- **VERIFY:** `python3 -m pytest tests/integration/test_gate_policy.py -k collect -q`
- **COMMIT:** `KLC-045 step-3: gate_policy.collect_signals from real skill APIs (fail-closed)`
- **Affected:** `core/skills/gate_policy.py`, `tests/integration/test_gate_policy.py`.
- Depends-on: step-2.
- **Code sketch:**

```python
import budget, scope_delta, scan_sentinels, lifecycle, phase_completion
def _budget_at_limit(ticket, counter):
    limits = budget._load_limits(); cur = (lifecycle.read_meta(ticket).get("budgets") or {})
    return int(cur.get(counter, 0)) >= limits.get(counter, 10**9)
def collect_signals(ticket, phase_id):
    ok, advisory = phase_completion.can_complete(ticket, phase_id)
    delta = scope_delta.compare(ticket)
    sig = {
      "advisory": advisory or "",
      "scope_expansion": bool(delta.get("expansion") or delta.get("skipped")),
      "sentinels": _sentinel_hits(ticket),
      "mutation": _budget_at_limit(ticket, "mutation_fix_attempts"),
      "budget_overrun": any(_budget_at_limit(ticket, c) for c in budget._load_limits()),
      "verdict": _read_verdict(ticket),
    }
    rc = lifecycle.read_meta(ticket).get("route_confidence")
    if rc is not None: sig["route_confidence"] = rc   # absent => dirty in evaluate
    return sig
```

## step-4 — klc ack --auto hook (real CLI path + forward-pick resolution)

- **Goal:** apply the policy under an opt-in flag; resolve the correct pick for
  `pick_required` multi-pick phases; leave manual ack byte-for-byte unchanged. (AC-5, AC-6)
- RED: not applicable — tests and implementation were developed concurrently in one commit
  (`186e997 [impl]`). Tests exist and pass; separate RED commit not committed.
  Original intent: `test_ack_auto_proceeds_clean`, `test_ack_auto_refuses_risky`,
  `test_ack_auto_refuses_low_route_confidence`, `test_decision_never_auto`, `test_ack_no_auto_unchanged`.
- **Interfaces:** `core/phases/ack.py` gains `--auto`. At `:ack-needed`, `--auto` calls
  `_resolve_auto_pick(phase)` → the pick whose `goto == "next"` (the forward/approve pick);
  since `apply_ack` RAISES when `pick_required` and `pick_id is None` (lifecycle.py:534),
  `--auto` MUST pass that pick's id into `apply_ack`. It then runs `collect_signals` +
  `evaluate`; on proceed it performs the ack with the resolved pick id, else exits non-zero
  printing reasons. Without `--auto`, the function is untouched.
- **Expected:** conditional+clean auto-acks and transitions; conditional+risky, low-confidence,
  and decision pause with phase unchanged; plain ack identical to today.
- **VERIFY:** `python3 -m pytest tests/integration/test_gate_policy.py -k "ack" -q`
- **COMMIT:** `KLC-045 step-4: klc ack --auto applies gate-policy via the real ack path`
- **Affected:** `core/phases/ack.py`, `tests/integration/test_gate_policy.py`.
- Depends-on: step-3.
- **Code sketch:**

```python
def _resolve_auto_pick(phase):
    fwd = [p for p in phase.picks if p.goto == "next"]
    return fwd[0] if fwd else (phase.picks[0] if len(phase.picks) == 1 else None)
# in run(), at :ack-needed:
if args.auto:
    pick = _resolve_auto_pick(phase)
    if pick is None:
        sys.stderr.write("klc ack --auto: no unambiguous forward pick\n"); return 2
    decision = gate_policy.evaluate(pick.gate, gate_policy.collect_signals(ticket, pid))
    if not decision.proceed:
        sys.stderr.write("klc ack --auto: paused — " + "; ".join(decision.reasons) + "\n")
        return 2
    return _do_ack(ticket, pick.id)   # same path manual ack uses
```

## step-5 — docs parity

- **Goal:** document the three gate levels and `--auto`. (AC-2, AC-5)
- RED: not applicable — docs-only step. Rule cited: AC-1 through AC-6 + roadmap 6.1.
- **Interfaces:** prose only — `docs/process.md` gains a "gate-policy" section listing the
  three levels, the decision gates, and the `klc ack --auto` behaviour.
- **Expected:** `grep -rn "gate-policy\|ack --auto" docs/process.md` returns the new content.
- **VERIFY:** `grep -rn "ack --auto" docs/process.md`
- **COMMIT:** `KLC-045 step-5: docs parity for gate-policy`
- **Affected:** `docs/process.md`.
- Depends-on: step-4.
- **Code sketch:** not applicable — documentation prose only (RED not applicable).

## Notes for the implementer

- One logical commit per step; COMMIT subjects verbatim.
- The predicate must be pure (no I/O) so it stays unit-testable; all I/O lives in
  `collect_signals`. Fail-closed: an unavailable signal is dirty.
- Do not auto-ack anything without `--auto`. KLC-046's runner reuses this exact path.
