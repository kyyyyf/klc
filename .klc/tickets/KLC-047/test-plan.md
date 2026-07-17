---
ticket: KLC-047
kind: test-plan
authority: human
---

# KLC-047 — Test plan

## Acceptance coverage

| AC | Test | Kind | Asserts |
| AC-1 | `test_work_build_state` | integration | For a ticket at `build:work`, `klc work --json` reports the build **per-step** card path (`build/_prompt_step_{impl_step}.md`, NOT a flat `_prompt.md`; DRIFT-2) and the phase outputs (`build-log.md`). |
| AC-2 | `test_work_ack_needed` / `test_work_ack` | integration | At `:ack-needed` the picks are listed; at `:ack` the output names `klc next`. |
| AC-3 | `test_work_verify_command` | integration | Output includes a verify command (`pytest` for build). |
| AC-4 | `test_work_unknown_ticket` + `test_work_archived` | integration | Unknown ticket exits non-zero with a friendly message and writes no meta; an archived ticket reports the archived marker (exit 0), no meta write. |
| AC-5 | `test_work_registered` + `test_work_in_help` | integration | `klc work` routes via the dispatcher AND appears in `klc --help` stdout (the help text is rendered from the module docstring, so registration alone is insufficient). |

## Edge cases

- A track that skips a phase (XS has no design): `work` reports the actual current phase from
  meta, never a phase absent from the ticket's track.
- A `:work` build state reports the step card for the current step, not step 1, when later
  steps are active.

## Regression scenarios

- `klc work` never mutates meta.json (byte-identical / sha before==after a call). It reads via
  `lifecycle.read_meta_ro` (NOT `current_state`, which persists a legacy migration; DRIFT-1),
  so even a legacy-phase ticket is not dirtied.
