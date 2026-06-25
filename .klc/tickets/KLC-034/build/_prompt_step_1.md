# Agent prompt — KLC-034 · build:work · step-1

Ticket: **KLC-034** · track: **M** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Close the three residual gaps left by KLC-032 (archived) relative to KLC-SP
roadmap item 1.1, so the discovery Socratic protocol is enforced through real
mechanisms rather than prose:

1. The "ask one question at a time" rule is backed by the `AskUserQuestion` tool
   (one question per call), not just a sentence in the prompt.
2. `DISCOVERY_LITE_UPGRADE_M` becomes a live signal that `phase_completion`
   detects and surfaces as a re-route advisory, mirroring `DISCOVERY_DECOMPOSE`.
3. The one-question-at-a-time behaviour is covered by a behavioural harness
   fixture (a `judge()` check), not only a phrase-existence assertion.

## Acceptance Criteria

1. AC-1: `discovery.md` and `discovery-lite.md` instruct the agent to use the
   `AskUserQuestion` tool for the Socratic questioning step, asking exactly one
   question per call and waiting for the answer before the next; if context
   already answers every material unknown, the agent skips questioning and goes
   straight to the approaches step. The existing four-step Socratic block and
   its markers (the phrase "one question at a time", "2-3 approaches") are
   preserved.
2. AC-2: `core/skills/spec_structure.py` gains a `has_upgrade_m_signal(text)`
   helper (regex on the `DISCOVERY_LITE_UPGRADE_M` token), mirroring
   `has_decompose_signal`, with no duplicated regex elsewhere.
3. AC-3: `core/skills/phase_completion.can_complete_discovery_lite` surfaces a
   non-blocking re-route advisory when `DISCOVERY_LITE_UPGRADE_M` is present in
   the spec, pointing the operator at `klc retrack <KEY> M`. The advisory does
   not block ack (parity with the `DISCOVERY_DECOMPOSE` advisory).
4. AC-4: A prompt-regression test asserts both discovery prompts contain
   `AskUserQuestion`; it fails on the pre-change prompts and passes after the
   AC-1 edit (kept as a permanent regression guard, not xfail).
5. AC-5: A behavioural harness fixture uses `judge()` to verify the agent's
   first turn asks exactly one question and does not batch; it skips gracefully
   when no judge API key is set (CI-safe) and exercises the wired prompt locally.
6. AC-6: Docs reflect the new reality with no stale claims: `docs/process.md`
   (discovery uses AskUserQuestion; `DISCOVERY_LITE_UPGRADE_M` is a live re-route
   signal alongside `DISCOVERY_DECOMPOSE`), `docs/roles.md` (discovery role asks
   one question at a time via the tool), `docs/process-artifacts.md`
   (`options-lite.md` and the two re-route signals).

### Current step — step-1

**has_upgrade_m_signal helper + advisory in phase_completion**

- Goal: make `DISCOVERY_LITE_UPGRADE_M` a live signal — detected and surfaced as
  a non-blocking re-route advisory, mirroring `DISCOVERY_DECOMPOSE`. (AC-2, AC-3)
- RED: in `tests/integration/test_socratic_gate.py` add two cases —
  (a) `has_upgrade_m_signal` returns True on a spec containing the token and
  False on one without; (b) a complete S-track discovery-lite ticket whose
  `spec.md` ends with `DISCOVERY_LITE_UPGRADE_M` makes
  `phase_completion.can_complete_discovery_lite` return `(True, advisory)` with
  `advisory` containing "retrack". Both fail today (no helper, no branch).
- GREEN: in `core/skills/spec_structure.py` add
  `_UPGRADE_M_RE = re.compile(r"\bDISCOVERY_LITE_UPGRADE_M\b")` and
  `has_upgrade_m_signal(text)` mirroring `has_decompose_signal`. In
  `core/skills/phase_completion.py::can_complete_discovery_lite`, in the
  "all checks passed" tail (next to the `has_decompose_signal` advisory), add:
  `if _spec_structure.has_upgrade_m_signal(text): return True, "DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via 'klc retrack <KEY> M'"`.
  Keep it after the decompose check; non-blocking.
- VERIFY: `python3 -m pytest tests/integration/test_socratic_gate.py -q`.
- COMMIT: `KLC-034 step-1: detect + surface DISCOVERY_LITE_UPGRADE_M as re-route advisory`
- Affected: `core/skills/spec_structure.py`, `core/skills/phase_completion.py`,
  `tests/integration/test_socratic_gate.py`.
- Depends-on: none.

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
re-run `klc step KLC-034 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-034/impl-plan.md`
- Full spec: `.klc/tickets/KLC-034/spec.md`
- Full test-plan: `.klc/tickets/KLC-034/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-034 step-1` and
run `klc step KLC-034 2` to get the next step's card,
or `klc ack KLC-034 --pick 1` if this was the last step.
