---
ticket: KLC-052
authority: hybrid
---

# Manual checklist — KLC-052

Tick each box as you walk through. If anything fails, stop and run:

    klc ack KLC-052 --pick 2    # 2 = failed (reopens build, supersedes review/manual)

## From AC

None of the 12 ACs in `test-plan.md` are tagged `manual` — every row maps to
an automated `acceptance` test (`tests/integration/test_orchestrator_*.py`,
`test_clarify_gate.py`, `test_clarify_style.py`, `tests/e2e/test_orchestrator.py`,
`test_discovery_split.py`, `test_runner_parks_interactive.py`). No AC-level
manual walkthrough item is required by the test plan.

## Recommended smoke test (not test-plan-mandated, but flagged by review)

The independent fresh-review agent noted it could not verify from pytest
alone whether Claude Code actually exposes `/klc:run` as an invocable slash
command from `klc-plugin/commands/run.md` + `klc-plugin/skills/run/SKILL.md`
(file-existence and frontmatter shape are all pytest can check). Recommend,
before or shortly after merge:

- [x] Install/reload the `klc-plugin` plugin in a real Claude Code session
      and confirm `/klc:run <KEY>` is offered in autocomplete.
- [x] Run `/klc:run` against a real low-confidence-intake ticket and confirm
      the clarify `AskUserQuestion` actually fires (not just documented) —
      this is the exact AC-7/AC-8 behavior the codex review flagged as
      ambiguous in the prompt wording (fixed in `klc-plugin/skills/run/
      SKILL.md`, but prompt-following behavior can only be confirmed by
      actually running it).

## Environment / prerequisites

- [x] `klc-plugin` regenerated (`python3 core/skills/plugin_gen.py`) against
      this branch's `core/agents/*.md` before the smoke test.

<!-- BEGIN: manual -->
QA walked through the smoke test in a live Claude Code session and
confirmed it passed (2026-07-12).
<!-- END: manual -->
