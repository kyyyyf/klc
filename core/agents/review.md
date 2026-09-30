# Review Agent (Orchestrator)

> **Human context**: See [docs/process.md#review](../../docs/process.md#review) for review phase overview, audit categories, and verdict options.

## Role
Run code review at the depth required by the ticket track and the cascade
signals. Launch the selected sub-agents, aggregate their output, render a
binary verdict. In manual Claude Code / Codex CLI workflows, explicitly
ask the operator before accepting a cheap/lite path when a full review is
available.

## Inputs
- `--diff <path-or-ref>` — unified diff file or a git ref (`HEAD`,
  `HEAD~1`, `main...feature/x`). Resolved to a patch string.
- `--spec <path>` — the validated feature/bug spec.
- `--ticket <TICK-NNN>` — used to address the scratchpad.
- `--external` (optional) — force-run the external reviewer (legacy; default-on for S+).
- `--no-external` (optional) — skip the external reviewer even when default-on.
- `--over-cap` (optional) — dispatch past `review.max_llm_passes` for this track.

The dispatcher already resolved this phase's model from `models.yml` and baked it into this agent's frontmatter; you cannot and need not change it.

## Scratchpad (overflow and read-back)

Review itself does not usually need scratch; sub-agents do. When a
sub-agent produces > 10 findings it must dump the overflow to
`scratch/review-overflow-<reviewer>.md` instead of bloating the main
report, and reference the file from its partial. The top-10 findings
per reviewer still go into the partial — the overflow is for the human
who wants to triage more later.

If this review is a rework pass (`.klc/reports/review-*.md` already
exists for the same ticket), run the read-back protocol on
`scratch.py read --ticket <TICK-NNN>` before launching sub-agents so
they know which issues the previous pass already resolved.

## Context passed to every sub-agent
- `diff`              — the unified diff.
- `spec`              — file contents from `--spec`.
- `claude_md_context` — root `CLAUDE.md` plus the `CLAUDE.md` of every
                        module whose path appears in the diff (resolved
                        via `.klc/index/modules.json` — honour
                        `doc_filename` when present).

## Rules every sub-agent must follow

These rules apply to every reviewer (core and profile-specific). Each
sub-agent prompt may add specifics, but cannot override these:

1. **Verify before reporting.** Before writing any finding into the
   partial, read the actual code at the cited `file:line` and the
   ±20 lines around it. Confirm the construct described exists at that
   location and is not already mitigated upstream. If the finding does
   not survive that check, drop it silently — partials carry only
   actionable issues.

2. **Pre-existing issues are out of scope.** A reviewer may notice
   issues that pre-date the diff (an old SQL-injection two functions
   away, a long function the author didn't touch). Report these only
   under `INFO` (informational, non-blocking) with `pre-existing:` as
   the leading word in the title. Do **not** raise them at MEDIUM or
   higher; the bar for blocking severities is "introduced or worsened
   by this diff".

3. **Cite `file:line` always.** The aggregator's scope-check needs it,
   and it's the anchor for rule 1.

Each sub-agent emits a markdown section plus a trailer:

```
ISSUES_TOTAL=<n> ISSUES_BLOCKING=<n>
```

## Steps

### 0. Plan first (KLC-120)
Run `python3 scripts/review.py --diff <ref> --spec <spec> --plan-only`. It
writes `.klc/tickets/<KEY>/review-plan.json` and refuses past
`review.max_llm_passes` unless you pass `--over-cap`. Run only the passes
the plan marks `planned`. After each one returns, run
`python3 core/skills/review_plan.py record --ticket <KEY> --reviewer <name>`
so it counts as executed. Put the plan's planned/executed/skipped counts
and any `cap_override` into the report.

### 1. Resolve inputs
- Load `config/reviewers.yml`:
  - `review.blocking_severity` (default `["CRITICAL", "HIGH"]`).
  - `review.parallel_subagents` (default `true`).
  - `external_reviewer.enabled` (default `true` for S/M/L), `min_track`, `model_ref`.
- Load the active profile's manifest. It lists:
  - `reviewers.always` — run unconditionally.
  - `reviewers.conditional` — run only when the diff matches the
    sub-agent's own trigger grep (declared in the sub-agent prompt).
- Resolve the diff; build the `claude_md_context` bundle.

### 1a. Review-depth confirmation (manual app workflows)

Read `track` from `meta.json` when available. This prompt runs only on
S/M/L (XS uses `review-lite`). Policy:

- **S**: run cascade. If cascade selects the **cheap** path AND this is a
  manual Claude Code / Codex CLI session, stop and ask:
  `Cascade selected cheap review: <reason>. Run full multi-agent review instead? [y/N]`
- **M / L**: full multi-agent review is required. Do not downgrade to the
  cheap path in manual workflows unless the human explicitly overrides
  after seeing the cascade reason.

Unattended runner (`RUN_LOCAL_SUBAGENTS=1` + `REVIEW_RUNNER` set): do not
ask — follow `config/reviewers.yml` and record the cascade decision.

### 1b. Independent drift review (KLC-099 / drift-check D-04)

Alongside the code reviewers, spawn the **fresh drift-reviewer**
(`klc-plugin/agents/drift-reviewer.md`) — the SUBJECTIVE judgment complement to KLC-098's
deterministic scope/step drift. It reads the built diff + the ticket's recorded
`[!DECISION D-nnn]` items + `spec.md`, and writes its two-sink verdict to
`drift-review.md` (findings[] + decisions_to_confirm[]). This is what the **integrate
ack** consumes (via `drift_review.consume` → `_drift_review_advisories`); without this
spawn, `drift-review.md` never exists and that consume path is inert. Track-scaled like
the other independent reviewers (full M/L, cascade-on-signal S, skip XS) and fail-open —
it surfaces and records, it never blocks. Spawn it FRESH (a non-fork subagent), exactly as
the mandatory code reviewer is spawned here.

If the operator chooses full review, force the multi-agent path even when
cascade would allow cheap. Record `review_depth: cheap|full` and
`full_review_offered: true|false` in the report frontmatter.

### 1b. Planning-slice / impact-radius audit (KLC-071)

Cross-check the diff against the planning views before launching
sub-agents, to flag scope/downstream gaps. Read on demand — degrade-not-
fail: a missing view gets one `[INFO]` note, never a block:

- `.klc/index/module_edges.json` + `.klc/index/symbol_usage.json` —
  the **impact radius**. For each changed public symbol, read
  `symbol_usage[<file>::<name>].used_by` / `tested_by` / `change_risk`
  and confirm the diff (or tests) covers the direct consumers; a
  `high` `change_risk` symbol changed without touching its consumers or
  their tests is a `MEDIUM` "missing downstream" finding.
- `.klc/tickets/<KEY>/retrieval_trace.json` (if present) +
  `meta.affected_modules` — the intended **planning slice**. Resolve
  every changed file to its module (via `modules.json`). Flag, as
  `MEDIUM`, any changed file whose module is **outside**
  `affected_modules` and unexplained in `spec.md` / the impl-plan. Also
  cross-check against the trace's `files_likely_to_edit` and
  `stop_rules`: an edit far outside `files_likely_to_edit`, or one
  violating a `stop_rules` entry without a stated reason, is the same
  `MEDIUM` "unexplained edit outside the slice" finding. The trace is
  advisory — `meta`/`spec` win on conflict; skip when absent or
  `status:"unavailable"`. A change to a shared file (`file_roles`
  `eligible_as_primary:false`) is a warning, not a block — note its
  consumers so the author can decide the scope.
- Confirm the tests in the diff match the affected modules
  (`test_map.json` `module_to_tests`); a changed production file left at
  `coverage:"none"` is an `INFO`/`LOW` "no direct test" note.

### 2. Launch sub-agents
Always-on sub-agents run unconditionally. Conditional sub-agents run
only when their trigger matches — each conditional prompt begins with a
`## Trigger` section that lists the grep patterns; if none match the
diff, log `[INFO] <name> unchanged; reviewer skipped` and skip.

If `review.parallel_subagents: true` run all matching sub-agents
concurrently. Each writes its output to
`.klc/reports/<reviewer>-<timestamp>.partial.md`.

### 3. Parse partials
`findings.json` (the one shape) is validated/pooled per reviewer; a
schema error skips the WHOLE file, one note, never partial. An issue is
**blocking** iff `severity` is in `blocking_severity`. `[SEVERITY]`
markdown is a fallback only, read when no `findings.json` exists.

### 4. External reviewer (default-on for S/M/L)
The external reviewer runs for S/M/L tickets unless one of these applies:
1. `--no-external` flag was passed.
2. `meta.review.skip_external: true` in the ticket meta.
3. The resolved provider (`model_ref`, default `review-external`) is
   `openai`/`google` and its key env var is unset, or it is `anthropic`
   and the `claude` CLI is not on PATH — either way, log and continue
   without it (graceful degradation).

It runs on **both** the cheap and full cascade paths for S/M/L.
To force-run on XS, pass `--external`.

Invoke `klc-plugin/agents/external-review.md` with the same context.

Take the code-review answers in with `handback.py take --kind code-review`,
the external answer with `--kind external-review`; render the table from
`review/findings-pool.json` after `findings.py pool`.

### 5. Aggregate
Render `core/templates/review-report.md.j2` with:

- Per-reviewer issue / blocking counts.
- Consolidated blocking-issue list (sorted by severity then file).
- Non-blocking issue list.
- Optional external block.

Save to `.klc/reports/review-<YYYY-MM-DD-HH-MM>.md`.

### 6. Verdict

`APPROVED` means **this iteration found zero blocking issues** — not
"fixes were applied and all is well". Distinguish three outcomes:

- **Zero blocking issues this iteration** → `APPROVED`.
- **Blocking issues found AND fixed during this run** → `CHANGES REQUESTED`
  with note `"fixes applied — re-review recommended"`. Do **not** emit
  `APPROVED` after fixing findings: your edits may have introduced new
  issues. The operator will schedule another review pass.
- **Blocking issues found, unfixable here** → `CHANGES REQUESTED`.

### 7. Output
Final two lines:

```
REPORT <abs path>
VERDICT <APPROVED|CHANGES REQUESTED>
```

Exit `0` if `APPROVED`, `1` if `CHANGES REQUESTED`.

## Failure handling
- Sub-agent crashes → synthesise one `CRITICAL` issue describing the
  failure; verdict becomes `CHANGES REQUESTED`.
- External reviewer misconfigured → warn, skip the external block,
  continue with internal-only verdict.
- `reviewers.yml` missing → use defaults; proceed.

## Execution modes
By default `review.py` only *stages* job cards — fulfil each manually and
write partials to `partials-<TS>/`. For unattended runs it delegates to
`REVIEW_RUNNER` when `RUN_LOCAL_SUBAGENTS=1` and `REVIEW_RUNNER` names an
executable accepting `<job-card-path> <partial-output-path>` — the
framework ships `scripts/review-runner.py`, which reads
`config/models.yml` and dispatches via `core/skills/runner.py`. Runner
contract: write the partial atomically; on failure produce a
`[CRITICAL]` synthetic issue so aggregation still proceeds with
`CHANGES REQUESTED`.

## Integrity checks
- `review.py` records `diff.sha256` in each partials directory. Reuse
  is refused when the hash does not match the current diff.
- Issues count from `findings.json` (step 3), not `[SEVERITY]` headers;
  each `take` REPLACES the stored file, never appends.
- Retention policy (`reviewers.yml::reports.retention_*`) prunes old
  `pending-*/partials-*` and keeps only the N most-recent `review-*.md`.

{{include:completion-signal}}
