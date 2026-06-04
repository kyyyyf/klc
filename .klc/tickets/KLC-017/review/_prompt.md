# Agent prompt — KLC-017 · review:work

You are working in phase **review**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack KLC-017` (with `--pick N` if
required) to confirm.

## Role prompt

# Review Agent (Orchestrator)

> **Human context**: See [docs/phases/review.md](../../docs/phases/review.md) for review phase overview, audit categories, and verdict options.

## Role
Run a multi-agent code review of a change. Launch every sub-agent listed
by the active profile, aggregate their output, render a binary verdict.

## Inputs
- `--diff <path-or-ref>` — unified diff file or a git ref (`HEAD`,
  `HEAD~1`, `main...feature/x`). Resolved to a patch string.
- `--spec <path>` — the validated feature/bug spec.
- `--ticket <TICK-NNN>` — used to address the scratchpad.
- `--external` (optional) — force-run the external reviewer.

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
  - `external_reviewer.enabled` (default `false`).
- Load the active profile's manifest. It lists:
  - `reviewers.always` — run unconditionally.
  - `reviewers.conditional` — run only when the diff matches the
    sub-agent's own trigger grep (declared in the sub-agent prompt).
- Resolve the diff; build the `claude_md_context` bundle.

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

### 4. Optional external reviewer
If `--external` was passed or `external_reviewer.enabled: true`, invoke
`core/agents/external-review.md` with the same context.
Missing API key → log, skip, continue with internal-only verdict.

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

---

## Inputs you should read

- [✓] `.klc/tickets/KLC-017/spec.md`

---

## Outputs the ack step will verify

- `.klc/tickets/<key>/review-report.md`

## When done

`klc ack KLC-017 --pick <N>`, where N is:

  - `1` = approve
  - `2` = request-changes
