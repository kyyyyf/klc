---
ticket: KLC-052
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no conversation context) + codex external review
reviewed_at: 2026-07-11
branch: feature/klc-052-orchestrator
---

# Review report — KLC-052

## Summary

Two independent reviews ran against this branch: a codex external review
(`.klc/tickets/KLC-052/codex_external_review.md`, verdict CHANGES REQUESTED,
2 HIGH + 1 MEDIUM) and a fresh `general-purpose` subagent review launched
per CLAUDE.md's mandatory pre-review-report step (no dedicated
`code-reviewer` agent type exists in this environment, so `general-purpose`
— fresh, no conversation context — was used instead). The fresh review
found 1 HIGH + 2 LOW, none overlapping with codex's findings. All 3 HIGH
findings across both reviews were fixed and verified with a true RED/GREEN
cycle before this report. Both LOW findings were assessed: one already
fixed as a side effect of the codex-driven work, one accepted as harmless.

## Findings and assessments

### C1 — HIGH (codex) — `/klc:run` documented but not exposed as a plugin slash command

`klc-plugin/skills/run/SKILL.md` and `klc-plugin/README.md` documented
`/klc:run <KEY>`, but the plugin's actual slash-command surface is
generated from `klc-plugin/commands/*.md` by `plugin_gen.py`'s
`_LIFECYCLE_CMDS`, which only covered the 8 legacy CLI-passthrough verbs.
`tests/integration/test_plugin_manifest.py` didn't require a `run.md`
either, so the gap was invisible to CI.

**Fix (applied):** `plugin_gen.py`'s `_generate_commands` now also writes
`klc-plugin/commands/run.md`, pointing at `klc-plugin/skills/run/SKILL.md`
as the single source of truth (not duplicating the loop instructions).
Added `"run"` to `test_plugin_manifest.py`'s `LIFECYCLE_CMDS` so this
can't silently regress. Commit `3475b63`.

### C2 — HIGH (codex) — Mandatory clarify gate could be silently skipped

`SKILL.md` step 4 said "Interactive gate — STOP" for both the mandatory
clarify gate and ordinary human-pick gates, mentioning the clarify
`AskUserQuestion` pass only as an "e.g." A plausible reading let the loop
park on a low-confidence ticket without ever asking the clarify questions,
defeating AC-7/AC-8's "always fires" requirement.

**Fix (applied):** rewrote step 4 into two explicit branches — the
clarify gate is now "run the pass now, in this turn, then continue";
only non-clarify interactive gates are "stop for real." Corrected the
frontmatter description and the "Stop conditions" summary, which repeated
the same blanket framing. Commit `3475b63`.

### C3 — MEDIUM (codex) — `runner.run_agent(ticket=...)` doesn't consume the resolved model/track

`run_agent` calls `phase_resolver.resolve_phase(ticket, phase_id)` only
for the interactive park check, then falls back to
`models.resolve(phase_id, track=track)` rather than consuming
`phase_resolver`'s resolved model directly. If a caller ever supplies
`ticket` with a `track` inconsistent with `meta.json:track`, the two
would diverge.

**Assessment: won't fix in this iteration.** Codex itself flagged this
non-blocking: every current call site that will pass `ticket=` also
passes a consistent `track`, so behavior is unaffected today. Fully
closing this requires deciding whether `track` should become derived-only
from `ticket` (an API change to `run_agent`, touching a shared module used
by non-KLC-052 callers) — out of scope for this ticket's surface.
Tracked as a known follow-up, not a live bug.

### F1 — HIGH (fresh review) — `agent_type` derives from `phase_id`, not the phase's actual agent file

`phase_resolver.resolve_phase()` computed
`klc-plugin/agents/{phase_id}.md` and returned `agent_type=None` when
that exact filename didn't exist. 5 of 14 real phases point at a
differently-named shared agent (`build` → `impl.md`,
`acceptance-test-plan`/`detailed-test-plan` → `test-planner.md`, `manual`
→ `manual-check.md`, `learn` → `retrospective.md`). This silently broke
AC-2's `Task(subagent_type=...)` dispatch for `build` — the single
most-executed phase for every S/M/L ticket — not an edge case. No
existing test caught it because every prior test only resolved phase ids
where `phase_id == prompt stem` (design, discovery) or where the bug was
masked by the always-inline path (xs-build).

**Fix (applied):** derive the agent filename from `phase.prompt`'s stem
instead of `phase_id`; falls back to `None` only for phases with no
prompt at all (intake, integrate, observe). Verified true RED by
reverting the fix and confirming the new regression test failed exactly
as described (`build` → `None` instead of `klc-impl`), then restored the
fix and confirmed GREEN. Added a parametrized test covering every phase
in `phases.yml` against its real expected agent, plus the no-agent
phases. Commit `f06fd78`.

### F2 — LOW (fresh review) — Completion-signal block on non-dispatched agent files

`core/agents/design-scout.md` and `intake-triage.md` (outside its own
clarify section) got the shared "Completion signal (orchestrator)" block
even though neither `design-scout` nor `intake-triage` is an
independently-dispatched `phases.yml` phase id — they're invoked ad hoc
(transcluded from `design.md`, or from within the `intake` phase's
clarify path).

**Assessment: won't fix.** The reviewer's own assessment: harmless — the
block only matters when a real `resolve_phase` call dispatches with a
matching phase id, which never happens for these two files. Slightly
misleading boilerplate, not a functional issue; removing it selectively
would reintroduce the per-agent drift the shared block was designed to
eliminate (single edit → all 21 files, no exceptions to hand-maintain).

### F3 — LOW (fresh review) — No `klc-plugin/commands/run.md` wrapper

Same underlying gap as C1. The fresh-review agent's read of the branch
predated the C1 fix landing (it ran ~21 minutes in the background while
the codex fixes were applied and committed).

**Assessment: already fixed.** See C1 / commit `3475b63`.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 | PASS | `klc-plugin/skills/run/SKILL.md`, `klc-plugin/commands/run.md`, `tests/e2e/test_orchestrator.py` |
| AC-2 | PASS | `phase_resolver.resolve_phase` (`runs_inline`/`agent_type`, fixed per F1), `tests/integration/test_orchestrator_dispatch.py` |
| AC-3 | PASS | `core/skills/run_signal.py::parse_signal`, shared "Completion signal (orchestrator)" block in `core/agents/*.md`, `tests/integration/test_orchestrator_signal.py` |
| AC-4 | PASS | `tests/integration/test_orchestrator_run_to_gate.py` (reuses KLC-045 `ack --auto`) |
| AC-5 | PASS | `tests/integration/test_orchestrator_stop.py` |
| AC-6 | PASS | `core/skills/run_signal.py::should_retry`, `tests/integration/test_orchestrator_failure.py` |
| AC-7 | PASS | `core/phases/intake.py` clarify_required stamp, `tests/integration/test_clarify_gate.py` |
| AC-8 | PASS | `core/agents/intake-triage.md` "Interactive clarify" section + `SKILL.md` step 4 (fixed per C2) |
| AC-9 | PASS | `core/agents/intake-triage.md` write-back/re-route steps |
| AC-10 | PASS | `tests/integration/test_clarify_gate.py::test_nothing_to_add_satisfies_gate` |
| AC-11 | PASS | `tests/e2e/test_discovery_split.py` |
| AC-12 | PASS | `config/clarify.yml`, `core/skills/clarify_config.py`, `tests/integration/test_clarify_style.py` (C-006 checked directly: `clarify_config` never imported by `runner.py`/`intake.py`/`ack.py`/`next.py`) |

## Final state

Full suite: `508 passed, 12 skipped` (`python3 -m pytest tests/ -q
--ignore=tests/fixtures` — `tests/fixtures/tiny-py` is a standalone
fixture project with its own unrelated collection error, pre-existing).
Last commit before push: see `git log --oneline -1` on
`feature/klc-052-orchestrator`.

## Scope note

`meta.json:affected_modules` was expanded during `klc ack` (scope
expansion signal) to include `intake`, `review`, `runner`, `tests`,
`klc-plugin/README.md`, `klc-plugin/skills/run/SKILL.md` — real
touched modules beyond the discovery-time list, per CLAUDE.md's
"update affected_modules rather than fight it."


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['config', 'core/agents', 'core/phases', 'core/skills', 'docs', 'intake', 'klc-plugin/README.md', 'klc-plugin/agents', 'klc-plugin/skills/run/SKILL.md', 'review', 'runner', 'tests']
  actual modules:  ['config', 'core/agents', 'core/skills', 'docs', 'intake', 'klc-plugin/agents', 'review', 'runner', 'tests']
  unplanned:       ['klc-plugin/README.md', 'klc-plugin/commands/run.md', 'klc-plugin/skills/run/SKILL.md']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-052`.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['config', 'core/agents', 'core/phases', 'core/skills', 'docs', 'intake', 'klc-plugin/README.md', 'klc-plugin/agents', 'klc-plugin/commands/run.md', 'klc-plugin/skills/run/SKILL.md', 'review', 'runner', 'tests']
  actual modules:  ['config', 'core/agents', 'core/skills', 'docs', 'intake', 'klc-plugin/agents', 'review', 'runner', 'tests']
  unplanned:       ['klc-plugin/README.md', 'klc-plugin/commands/run.md', 'klc-plugin/skills/run/SKILL.md']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-052`.
