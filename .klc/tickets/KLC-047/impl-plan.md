---
ticket: KLC-047
kind: impl-plan
design_choice: option-A-minimal
last_generated: 2026-06-24
---

# KLC-047 — Implementation plan (executable, for Sonnet)

Build target: a read-only `klc work <KEY>` verb. Per-step contract: **Goal / RED /
Interfaces / Expected / VERIFY / COMMIT / Affected / Code sketch / Depends-on**. Run after
each step: `python3 -m pytest tests/ -q --ignore=tests/fixtures`. COMMIT subjects verbatim.

## step-1 — next_action resolver

- **Goal:** a pure function that, given a ticket, returns its current state and the next
  action descriptor (prompt path, outputs, verify command, picks). (AC-1, AC-2, AC-3)
- RED: add `tests/integration/test_work_verb.py::test_work_build_state` and
  `::test_work_ack_needed` driving the resolver against fixtures at `build:work` and an
  `:ack-needed` state. Fail today (no resolver).
- **Interfaces:** `core/phases/work.py::next_action(ticket: str) -> dict` with keys
  `ticket`, `phase`, `state`, `outputs`, `verify` plus one of `prompt` / `picks` / `next`,
  reusing `lifecycle.read_meta_ro` (NOT `current_state` — that calls `read_meta` with
  `persist_migration=True` and WOULD write meta.json for a legacy ticket, violating AC-4)
  and `phases.load_phases` / `phases.parse_state`. There is **no** read-only prompt-path
  helper in `artefacts` (only writers), so `work` builds the path string itself
  (DRIFT-3). The build prompt card is the **per-step** card written by `klc step`
  (`build/_prompt_step_{N}.md`), not a flat `build/_prompt.md` (DRIFT-2).
- **Expected:** at `:work` the dict carries prompt + outputs + verify; at `:ack-needed` it
  carries picks; at `:ack` it carries the `klc next` hint; an archived ticket carries an
  `archived` marker (so the verb reports cleanly, not a crash).
- **VERIFY:** `python3 -m pytest tests/integration/test_work_verb.py -k state -q`
- **COMMIT:** `KLC-047 step-1: next_action resolver over phases.yml + meta`
- **Affected:** `core/phases/work.py` (new), `tests/integration/test_work_verb.py` (new).
- Depends-on: none.
- **Code sketch:**

```python
def next_action(ticket):
    meta = lifecycle.read_meta_ro(ticket)          # read-only; never writes meta
    phase_value = meta.get("phase") or "intake:ack-needed"
    if phase_value == phases.STATE_ARCHIVED:       # handle archived FIRST (like status.py)
        return {"ticket": ticket, "phase": "archived", "state": "archived",
                "next": "(ticket archived — nothing to do)"}
    pid, state = phases.parse_state(phase_value)
    ph = phases.load_phases().by_id(pid)
    verify = ("python3 -m pytest tests/ -q --ignore=tests/fixtures"
              if pid == "build" else f"klc status {ticket}")
    out = {"ticket": ticket, "phase": pid, "state": state,
           "outputs": list(ph.outputs), "verify": verify}
    if state == "work":
        if pid == "build":                          # per-step card (DRIFT-2)
            step = meta.get("impl_step") or 1
            out["prompt"] = f".klc/tickets/{ticket}/build/_prompt_step_{step}.md"
        else:                                       # work builds the path itself (DRIFT-3)
            out["prompt"] = f".klc/tickets/{ticket}/{pid}/_prompt.md"
    elif state == "ack-needed":
        out["picks"] = [(p.id, p.label) for p in ph.picks]
    else:  # ack
        out["next"] = f"klc next {ticket}"
    return out
```

## step-2 — CLI verb + rendering

- **Goal:** wire `klc work <KEY>` to print the resolver output (human + `--json`), read-only,
  with a friendly error for an unknown ticket and a clean report for an archived one; AND make
  the verb visible in `klc --help`. (AC-4, AC-5)
- RED: add `test_work_verify_command`, `test_work_unknown_ticket`, `test_work_archived`
  (archived ticket reports the archived marker, exit 0, no meta write), and `test_work_in_help`
  (the string `klc work` / a `work` line appears in `klc --help` stdout — NOT merely that the
  command routes).
- **Interfaces:** `work.run(argv) -> int` (argparse: `ticket`, `--json`); register `"work"`
  in the `scripts/klc` `LIFECYCLE_CMDS` tuple AND add a `work — print the next required action`
  line to the `scripts/klc` MODULE DOCSTRING (`__doc__`) — the `--help` text is rendered from
  `__doc__` via `_print_help()`, so registration in `LIFECYCLE_CMDS` alone does NOT surface it
  in `--help` (this was the gap to close). Unknown-ticket check mirrors `step.py` /
  `status.py`: `if not klc_ticket_meta_file(ticket).exists(): stderr + return 1` BEFORE
  calling `next_action`, so no meta read/write happens for a missing ticket.
- **Expected:** prints phase/prompt/outputs/verify or picks or the `klc next` hint; `--json`
  emits the dict; unknown ticket exits non-zero without writing meta; archived ticket reports
  cleanly; `klc --help` lists `work`.
- **VERIFY:** `python3 -m pytest tests/integration/test_work_verb.py -q && klc --help | grep -q "work"`
- **COMMIT:** `KLC-047 step-2: klc work verb + dispatcher registration + --help entry`
- **Affected:** `core/phases/work.py`, `scripts/klc` (dispatcher tuple AND module docstring),
  `tests/integration/test_work_verb.py`.
- Depends-on: step-1.
- **Code sketch:**

```python
def run(argv):
    ap = argparse.ArgumentParser(prog="klc work")
    ap.add_argument("ticket"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not klc_ticket_meta_file(a.ticket).exists():
        sys.stderr.write(f"klc work: unknown ticket {a.ticket!r}\n"); return 1
    info = next_action(a.ticket)          # read-only; never writes meta
    print(json.dumps(info) if a.json else _render(info))
    return 0
# scripts/klc module docstring: add a line "    work     — print the next required action ..."
```

## step-3 — docs parity

- **Goal:** document `klc work` in the process docs. (AC-5)
- RED: not applicable — docs-only step. Rule cited: AC-5 + roadmap C.1.
- **Interfaces:** prose only — `docs/process.md` gains a one-line `klc work <KEY>` entry in
  the operational-commands list.
- **Expected:** `grep -rn "klc work" docs/process.md` returns the new content.
- **VERIFY:** `grep -rn "klc work" docs/process.md`
- **COMMIT:** `KLC-047 step-3: docs parity for klc work`
- **Affected:** `docs/process.md`.
- Depends-on: step-2.
- **Code sketch:** not applicable — documentation prose only (RED not applicable).

## Notes for the implementer

- One logical commit per step; COMMIT subjects verbatim.
- Read-only: `work` must never write meta.json. Keep `next_action` pure for unit testing.
