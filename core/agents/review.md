# Review Agent (Orchestrator)

> **Human context**: See [docs/phases/review.md](../../docs/phases/review.md) for review phase overview, audit categories, and verdict options.

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

## Model note

This phase expects the coding-tier model, not Opus. Resolve it from
`models.yml` (`per_track.<track>.<phase>` → `phase_roles.<phase>` →
`defaults`) and, if you just came from a heavy-reasoning phase, switch
**down** before working. This is a cost note, not a gate — do not stop or
ask; just print one line if a downgrade is warranted:

```text
MODEL_NOTE <KEY> phase=<phase-id> expects=<provider:model> (downgrade from design/discovery Opus)
```

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

### 1. Resolve inputs
- Load `config/reviewers.yml`:
  - `review.blocking_severity` (default `["CRITICAL", "HIGH"]`).
  - `review.parallel_subagents` (default `true`).
  - `external_reviewer.enabled` (default `true` for S/M/L), `min_track`, `api_key_env`.
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

If the operator chooses full review, force the multi-agent path even when
cascade would allow cheap. Record `review_depth: cheap|full` and
`full_review_offered: true|false` in the report frontmatter.

### 2. Launch sub-agents
Always-on sub-agents run unconditionally. Conditional sub-agents run
only when their trigger matches — each conditional prompt begins with a
`## Trigger` section that lists the grep patterns; if none match the
diff, log `[INFO] <name> unchanged; reviewer skipped` and skip.

If `review.parallel_subagents: true` run all matching sub-agents
concurrently. Each writes its output to
`.klc/reports/<reviewer>-<timestamp>.partial.md`.

### 3. Parse partials
Extract every issue tagged `[SEVERITY]`. An issue is **blocking** iff
its severity is in `blocking_severity`. The aggregator counts from the
headers and ignores the manual trailer; mismatches warn to stderr.

### 4. External reviewer (default-on for S/M/L)
The external reviewer runs for S/M/L tickets unless one of these three
conditions applies:
1. `--no-external` flag was passed.
2. `meta.review.skip_external: true` in the ticket meta.
3. The environment variable named in `external_reviewer.api_key_env`
   is not set (graceful degradation — log and continue without it).

It runs on **both** the cheap and full cascade paths for S/M/L.
To force-run on XS, pass `--external`.

Invoke `core/agents/external-review.md` with the same context.

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
By default `review.py` only *stages* job cards — an operator (or Claude
Code) fulfils each card manually and writes partials to
`partials-<TS>/`.

For unattended runs, the script delegates each job card to an external
runner when both conditions hold:

- `RUN_LOCAL_SUBAGENTS=1`
- `REVIEW_RUNNER` points to an executable that accepts
  `<job-card-path> <partial-output-path>` and produces the partial.

The framework-shipped runner is `scripts/review-runner.py`. It reads
`config/models.yml` to decide the provider / model (anthropic / openai /
ollama / google), composes the combined prompt, and dispatches via
`core/skills/runner.py`. Usage:

```bash
RUN_LOCAL_SUBAGENTS=1 \
REVIEW_RUNNER="$PWD/scripts/review-runner.py" \
python scripts/review.py --diff HEAD --spec .klc/index/pending-feature.md
```

Runner contract: write the partial atomically (move-into-place); on
failure, produce a partial with a `[CRITICAL]` synthetic issue so
aggregation still proceeds with `CHANGES REQUESTED`.

## Integrity checks
- `review.py` records `diff.sha256` in each partials directory. Reuse
  is refused when the hash does not match the current diff.
- Issues are counted from `[SEVERITY]` headers only; the human-readable
  trailer cannot distort the verdict.
- Retention policy (`reviewers.yml::reports.retention_*`) prunes old
  `pending-*/partials-*` and keeps only the N most-recent `review-*.md`.

## Completion signal (orchestrator)

In addition to any phase-specific signal above, end your final output
with exactly one fenced JSON object, as the LAST block in your response:

```json
{"phase":"<phase-id>","signal":"done","artifacts":["path/relative/to/ticket/dir.md"],"blocking_questions":[],"next_action":"ack"}
```

- `phase` — the phase id you were dispatched for (your agent name after
  the `klc-` prefix, e.g. `klc-design` -> `"design"`).
- `signal` — `"done"` | `"blocked"` | `"failed"`.
- `artifacts` — paths you wrote, relative to the ticket directory.
- `blocking_questions` — string[]; leave `[]` if none. Blank/empty
  entries are ignored by the orchestrator.
- `next_action` — `"ack"` | `"clarify"` | `"stop"`.
- Optional: `"tokens":{"in":N,"out":N}`.

This is consumed by the `/klc:run` orchestrator (KLC-052) to decide the
next step without re-reading your artifacts. It does not replace any
phase-specific signal line above — both are expected.
