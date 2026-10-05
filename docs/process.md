# klc process & detailed usage

This is doc #2 of three: the **how**. It is the single process-and-usage
reference — phases, gates, tracks, verbs, artifacts, roles, metrics, and the epic
and dual-remote workflows. For key decisions and cross-cutting invariants see
[`architecture.md`](architecture.md); for install and end-to-end scenarios see the
root [`README.md`](../README.md).

The authoritative source for phases and transitions is
[`config/phases.yml`](../config/phases.yml); this doc explains it.

---

## Principles

1. **Kanban, not waterfall.** Work flows through phases by pull.
2. **Agents draft, humans gate.** LLMs produce every artefact; humans confirm at
   obligatory picks. Spec is sealed after discovery ack.
3. **Multi-dimensional estimate → track.** Four axes (complexity / uncertainty /
   risk / manual), each 0–3. Total → XS / S / M / L. Downgrades forbidden;
   upgrades always allowed.
4. **Facts tagged in every artefact.** `[!FACT src=…]`, `[!ASSUMPTION if-false=…]`,
   `[!DECISION D-NNN]`. Enables retrospective verification and cuts hallucination.
5. **Short XS path.** XS skips acceptance-test-plan, design, and observe. Uses
   discovery-lite instead of full discovery. One build agent call + review-lite.
6. **Conditional phases.** `observe` runs only when `risk_tags` contains
   `user-facing`, `data`, `security`, or `migration`. `learn` always runs for M/L;
   for XS/S it runs only when rework occurred or budgets were overrun. Discovery
   agents set `risk_tags` in meta.json; skipped phases are recorded in
   `phase_history` with `event=skipped`.

---

## Tracks

The multi-dimensional estimate maps a ticket to a track that decides which phases
it visits. The full XS/S/M/L decision rubric is its own single source in
[`tracks.md`](tracks.md) (generated, lockstep-tested); the summary:

| Track | Score | Typical scope            |
|-------|-------|--------------------------|
| XS    | 0–2   | one-line change or typo  |
| S     | 3–5   | local fix / refactor     |
| M     | 6–8   | feature in one module    |
| L     | 9–12  | cross-module / new dep   |

Guard invariants: any axis = 3 floors at M; uncertainty = 3 + total ≥ 7 forces L.

**XS path**: intake → discovery-lite → xs-build → review-lite → integrate → learn

**S path**: intake → discovery-lite (spec+test-plan+impl-plan) → build → review →
integrate → observe → learn

**M path**: intake → discovery → acceptance-test-plan → design (impl-plan w/ tests)
→ build → review → manual → integrate → observe → learn

**L path**: as M, plus a `detailed-test-plan` gate after design.

---

## Phase map

All phases are defined in `config/phases.yml`. `klc next` advances from `:ack` →
the next phase's `:work`; `klc ack --pick N` closes `:ack-needed`.

| Phase id               | Tracks      | Agent prompt                      | Picks at `:ack-needed`                                    |
|------------------------|-------------|-----------------------------------|------------------------------------------------------------|
| `intake`               | XS S M L    | _(no agent; `klc intake` is deterministic — optional `intake-triage.md`)_ | 1 = confirm-route · 2 = force-full-discovery · 3 = force-xs-skip (XS only) |
| `discovery-lite`       | XS S        | `core/agents/discovery-lite.md`   | 1 = approve · 2 = needs-rework · 3 = upgrade-to-full      |
| `discovery`            | M L         | `core/agents/discovery.md`        | 1 = approve · 2 = needs-rework                            |
| `acceptance-test-plan` | M L         | `core/agents/test-planner.md`     | 1 = approve · 2 = needs-rework                            |
| `design`               | M L         | `core/agents/design.md`           | 1 = option-A · 2 = option-B · 3 = option-C · 4 = rework · 5 = revise-impl-plan |
| `detailed-test-plan`   | L           | `core/agents/test-planner.md`     | 1 = approve · 2 = needs-rework (M: tests folded into impl-plan steps) |
| `xs-build`             | XS          | `core/agents/xs-fasttrack.md`     | 1 = approve · 2 = upgrade-to-S                            |
| `build`                | S M L       | `core/agents/impl.md`             | 1 = approve                                                |
| `review-lite`          | XS          | `core/agents/review-lite.md`      | 1 = approve · 2 = request-changes · 3 = override          |
| `review`               | S M L       | `core/agents/review.md`           | 1 = approve · 2 = request-changes (→ build:work)          |
| `manual`               | M L         | `core/agents/manual-check.md`     | 1 = passed · 2 = failed (→ build:work)                    |
| `integrate`            | XS S M L    | _(checklist, no agent)_           | 1 = merged                                                 |
| `observe`              | S M L       | _(monitoring checklist)_          | 1 = clean · 2 = regression · 3 = rollback                 |
| `learn`                | XS S M L    | `core/agents/retrospective.md`    | 1 = archive · 2 = extract-to-CLAUDE.md                    |

The per-phase sections below give the human context (purpose, inputs, outputs, ack
options, pitfalls) that the agent prompts link to.

---

## Intake

**Purpose.** Accept a new ticket and validate raw input. `klc intake` is
deterministic (no LLM); a short, low-confidence ticket may be routed through the
cheap `intake-triage` agent.

- **Inputs:** `raw.md` (initial description, Goals/Problem or Context). Human runs
  `klc intake <KEY> [--kind feature|bug|tech] "<desc>"`.
- **Outputs:** `.klc/tickets/<KEY>/meta.json`, stored `raw.md`, state
  `intake:ack-needed`. Intake prints `route=<track> confidence=<low|medium|high>`
  (from `route_heuristic.py`) — the track is a **provisional floor**.
- **Ack options:** `--pick 1` confirm-route → discovery(-lite):work · `--pick 2`
  force-full-discovery · `--pick 3` force-xs-skip (XS only).
- **Pitfalls:** missing Goals/Problem section in raw.md → validation failure;
  ambiguous requirements → rework in discovery. A short description means
  under-specified, not necessarily simple.

## Discovery

**Purpose.** Transform raw input into a formal spec with ACs, an estimate, and a
track assignment. On S/XS this is `discovery-lite`, which also writes
`impl-plan.md` in the same call, with the approaches in the `## Approaches` section of `spec.md`.

- **Inputs:** `raw.md`, the root `CLAUDE.md`, `.klc/scratch/<KEY>/retrieval_trace.json`
  and `.klc/index/modules.json` (below).
- **Outputs:** `spec.md` (Goals, Problem/Context, ACs, Non-goals, Constraints,
  Affected modules, Open questions, Estimate); `meta.json` updated with track,
  estimate, layer, `affected_modules`, and `risk_tags`.
- **Completion criteria:** spec.md has all required sections; every AC is testable;
  the estimate total matches the track.
- **Ack options:** `--pick 1` approve (seals spec.md; XS → xs-build, S/M/L →
  acceptance-test-plan or, on S, build) · `--pick 2` needs-rework · (lite) `--pick
  3` upgrade-to-full.
- **Pitfalls:** non-testable ACs ("improve performance" with no metric); wrong
  track; scope creep (`affected_modules` too broad).

**Socratic protocol (KLC-034).** Both discovery prompts use the `AskUserQuestion`
tool — exactly one question per call, waiting for the answer before the next. If
context already answers every material unknown, the agent skips questioning and
goes straight to approaches. Two non-blocking re-route signals may be emitted in
`spec.md`: `DISCOVERY_DECOMPOSE` (ticket spans ≥ 3 independent subsystems) and
`DISCOVERY_LITE_UPGRADE_M` (S scope exceeds the S ceiling). Both leave
`can_complete_discovery_lite` returning `(True, advisory)`.

**Degraded trace.** The trace is degraded when it is absent, `status:"unavailable"`,
`confidence:"low"`, `mode:"name-match-only"`, or its `degraded_inputs` is non-empty.
The agent then quotes those fields in `spec.md` «Problem / Context», opens at most
3 modules from the `modules.json` table by name/path overlap with `raw.md`; do not
scan the repository. Related-ticket lessons come from the `retrospective.md` of at
most 5 archived tickets that share the ticket's kind or a module.

Symbols are **not** pre-loaded — the agent uses LSP `workspaceSymbol` on demand,
cheaper than a static dump and always current.

## Acceptance-test-plan

**Purpose (M/L).** Map every AC to a concrete acceptance/e2e test — no
implementation detail yet.

- **Inputs:** `spec.md`.
- **Outputs:** `test-plan.md` — acceptance coverage table (AC → e2e/acceptance/
  manual test + location), edge cases, regression scenarios, and a manual checklist
  when `estimate.manual ≥ 2`.
- **Completion criteria:** every AC has a row; test types are e2e/acceptance/manual
  (no unit/integration yet); manual checklist populated when needed.
- **Ack options:** `--pick 1` approve (S → build, M/L → design) · `--pick 2`
  needs-rework.
- **Pitfalls:** a missing AC in the table is a phase failure; using unit/
  integration types too early.

An **independent coverage review** (KLC-085) runs before the phase completes —
see [Independent spec/test-plan/impl-plan review](#independent-spectest-planimpl-plan-review).

## Design

**Purpose (M/L).** Generate design options, choose one, and author `impl-plan.md`
(the decision record is part of `design.md`).

- **Inputs:** `spec.md`, `test-plan.md`.
- **Outputs:** one `design.md` (`## Options` with 2–4 labelled approaches and a
  `Picked:` line, then `## Consequences`); `impl-plan.md` authored to the
  executable step contract.
- **Completion criteria:** `design.md` lists 2–4 distinct feasible approaches (no
  hallucinated APIs) and names the pick with its rationale; `impl-plan.md` passes
  the plan-completeness gate.
- **Ack options:** `--pick 1/2/3` option-A/B/C · `--pick 4` needs-rework · `--pick
  5` revise-impl-plan. Approving seals the design and advances to detailed-test-plan
  (L) or build (M).
- **Pitfalls:** only one option (not enough exploration); a chosen option that
  depends on a nonexistent library/API; a missing rationale.

An **independent impl-plan review** (KLC-094) runs at the ack that finalizes
`impl-plan.md` — see
[Independent spec/test-plan/impl-plan review](#independent-spectest-planimpl-plan-review).

## Detailed-test-plan

**Purpose (L only; M folds it into impl-plan steps).** Add unit/integration tests
keyed to impl-plan steps, extending `test-plan.md`.

- **Inputs:** existing `test-plan.md` (acceptance section), `impl-plan.md`,
  `design.md`.
- **Outputs:** `test-plan.md` with a `## Detailed coverage` table (step → unit/
  integration/characterisation test → location → target symbol(s)).
- **Completion criteria:** every impl-plan step has a row or a `covered-by: AC-N`
  note; target symbols verified via LSP (no hallucinated names).
- **Ack options:** `--pick 1` approve → build · `--pick 2` needs-rework.
- **Pitfalls:** a missing step with no covered-by note; a hallucinated target
  symbol; duplicating acceptance tests at the detailed level.

## XS-build

**Purpose (XS).** Fast path that combines test writing and implementation in a
single agent call. No `impl-plan.md`, no TDD loop.

- **Inputs:** `spec.md` + `raw.md` + root `CLAUDE.md`.
- **Outputs:** code + tests + a git commit. The agent locates code via LSP, writes
  the fix and test, commits, and emits `XS_IMPL_DONE` or `XS_BLOCKED`.
- **Ack options:** `--pick 1` approve → review-lite · `--pick 2` upgrade-to-S.
- **Pitfalls:** over-complicating a trivial change; skipping the test (even XS needs
  coverage). If scope expands beyond `affected_modules` the agent emits
  `XS_BLOCKED`; the human runs `klc jump acceptance-test-plan:work --yes` to upgrade
  (discovery is already done).

## Build

**Purpose (S/M/L).** Implement code via a TDD loop — make failing tests pass, one
step at a time. `build:work` is driven by `impl-plan.md` (S works from `spec.md`
directly; M/L follow the plan steps).

- **Inputs:** `spec.md`, `test-plan.md`, `impl-plan.md` (M/L).
- **Outputs:** code changes; `build/steps.json` (the recorded VERIFY result per plan
  step, KLC-174); git commits (one RED and one GREEN commit per step);
  `build-log.md` is optional free notes.
  A rebase or amend of a step's commits invalidates its recorded verify (the green commit must be an ancestor of the recorded HEAD), so re-run `klc step verify` after rewriting history.
- **Completion criteria:** all tests green; every AC has a passing test; impl-plan
  fully ticked (M/L). For each plan step the agent commits RED, commits GREEN, then
  runs `klc step verify <KEY> N`, which executes the step's allowlisted `VERIFY:`
  once and records the result in `build/steps.json`. `klc ack` only READS that file
  and re-executes nothing: it blocks a step whose recorded verify is missing, failed,
  differs from the plan's `VERIFY:` or predates the latest commit on the step. The file
  is untrusted input — commits, TDD order and state are recomputed from git
  (`core/skills/step_state.py`). A recorded verify also carries the `head` it ran at and
  a `dirty` flag, and counts only when the tree was clean, the step's green commit is at
  or below that `head`, and `ran_at` is not in the future. A hand-written steps.json
  claiming green is therefore trusted only up to those derived checks (commit ancestry,
  head, dirty flag, `ran_at` bounds): it proves a verify was recorded, not that it ran,
  which is a deliberate trust shift from the removed replay. The VERIFY allowlist is not
  a sandbox, because the test code itself still runs (a committed `conftest.py` can
  execute anything); git history must show a
  failing-test commit before the implementation commit for each behaviour step
  (verified mechanically by `klc ack` via `core/skills/tdd_order.py`; steps marked
  `RED: not applicable` are exempt). A FACT item in `spec.md`, `design.md`
  or `impl-plan.md` must cite a real project code or config file as `src=<path>:<line>`;
  for a ticket created on or after `items_verify.FACT_SOURCE_RULE_EPOCH`, or any item
  carrying `evidence=read`, a bad source fails consistency — for an older ticket it
  is warned, not failed (`consistency_check.py`, `items_verify.py`).
- **A gate that misfires is fixed in the framework, never waived per project.**
  KLC-109 is the worked example: the red-before-green ordering gate
  (`core/skills/tdd_order.py`) recognised only a `tests/` path segment, so every
  colocated-test project (`Foo.test.tsx`, `foo_test.go`, `FooTest.java`,
  `foo_spec.rb`) was blocked, and the observed response was a standing
  per-project waiver that took five tickets through integrate with no review.
  A new language layout is added in ONE place: `core/skills/test_conventions.py`,
  or a profile's `test_conventions:` manifest key — never a per-project
  workaround. A basename match outside any declared test directory is trusted
  only when the caller supplies `exists=`, a predicate confirming its derived
  sibling production file — the review-fix that closed a self-referential
  collision where the shared module's own filename (`test_conventions.py`,
  `test_map.py`) satisfied the bare python `test_*.py` glob with no sibling
  beside it. **Conservative default (KLC-109 review round 2, D-109-9):**
  calling `is_test_path`/`test_signal` with NO `exists=` at all is NOT the
  same as "trust the name" — it is the safe failure mode, treating a
  basename-only match outside a test directory as NOT a test. Every real
  consumer opts in: a hard GATE (`tdd_order.classify`, `ac_test_coverage`)
  passes a predicate backed by a git tree, never today's working-tree
  checkout (an already-acked step's verdict must not depend on what an
  unrelated LATER commit does to the sibling); an INDEX builder (`test_map`,
  `file_roles`, `module_edges`, `symbol_usage`, `import-graph`, `scope_delta`,
  `test-writer`) passes membership in the KLC-105 file universe it already
  holds — a pure set lookup, no filesystem I/O. The directory signal and a
  "sibling: none" layout (`conftest.py`, `tests.rs`, `test.rs`) never depend
  on `exists=` at all. **Per-commit new-file rule (KLC-109 review round 4,
  D-109-12):** `tdd_order.classify` looks at ONE commit and its immediate
  parent only — never a step's tip, never the whole step's commit list. A
  basename match that is freshly ADDED in that commit (absent from its
  parent tree) is a test with no sibling required yet, because an honest
  RED commit is, by construction, added before its GREEN sibling exists; a
  PRE-EXISTING path (already in the parent tree) still needs a confirmed
  sibling. This closes a false sanction the ticket's own round-2 fix
  introduced: a step whose only landed commit was its RED test, with the
  GREEN commit not yet committed, was misclassified `impl` because its own
  tip had no confirmed sibling — the ordinary window between committing a
  failing test and committing the fix that makes it pass. Because both a
  commit's own tree and its parent's tree are immutable once made, this
  answer is stable forever without anchoring to any moving "tip".
  **Git-status-aware classification (KLC-126):** the per-path status this
  rule reads is real git status (`A`/`M`/`D`/`R###`/`C###`, via `git show
  --first-parent -M -C --name-status`), not a bare name-only file list — a
  pure rename or copy of a production file to a test-shaped basename no
  longer grants a free `added=` pass (it still needs a confirmed sibling),
  and a non-conflicting merge commit is classified from its
  first-parent diff instead of the empty file list `git show --name-only`
  produces for a clean merge.
- **Ack options:** `--pick 1` approve → review · (block when a budget limit is hit
  or the plan is invalid).
- **Pitfalls:** a red-test loop over the budget; scope creep; silent plan changes
  (must be recorded as `[!DECISION]` items).
- **Nested full-suite check.** `tests/integration/test_klc105_no_regression.py::test_full_suite_passes_unchanged`
  spawns the entire `tests/` suite as a child process and is skipped by default;
  run it explicitly with `KLC_RUN_NESTED_FULL_SUITE=1` (e.g. as a separate CI step).

**TDD loop.**

1. **Test agent** (`core/agents/test.md`) writes a failing test for the current
   step.
2. **Impl agent** (`core/agents/impl.md`) makes it pass, navigating symbols via LSP
   (`workspaceSymbol`, `goToDefinition`, `findReferences`) — no speculative reads.
   Each step gets a dependency-resolved brief via `klc task-brief <key> N` written to
   `build/step-N-brief.md`; a `step-N-impl-report.md` skeleton is scaffolded. By
   default the step card **references** `core/agents/impl.md` by path rather than
   embedding it (~7.5 KB saved/step); set `KLC_CARD_INLINE=1` for paste-only
   workflows. A lightweight minimal card is `klc step <key> N`.
3. **Per-step review** (M/L always; S only with `risk_tags`; XS never): after each
   green step an independent reviewer reads only the step package
   (`step-N-brief.md` + `step-N-impl-report.md` + step diff) and routes findings by
   severity. CRITICAL/HIGH are blocking — a fix subagent is dispatched and the step
   re-reviewed (capped at `PER_STEP_REREVIEW_CAP`); MEDIUM/LOW are logged to
   `step-N-review.md` without blocking. Runs as a post-green hook in the
   `klc build-run` orchestrator (`core/skills/per_step_review.py`).
4. Repeat until all steps are green, then `klc ack <key> --pick 1`.

**`build-log.md`** is optional free notes from the impl agent (decisions, deviations,
finding assessments). Nothing gates on it; `klc ack` does not read it. The reviewer and
the retrospective agent may use it as context.

**Review signal rule.** `APPROVED` / `REVIEW_LITE_PASS` means "this iteration found
zero issues". If the reviewer finds and fixes something during a pass, it emits
`CHANGES REQUESTED` / `REVIEW_LITE_CRITICAL` so the operator can schedule another
pass to confirm the fix introduced no new problems.

**Build orchestrator.** `klc build-run <KEY>` dispatches each impl-plan step that
`step_state.derive` reports as not green to a fresh Claude subprocess with a
dependency-resolved brief, then runs `record_verify` for it and reads the state back.
It exits 0 when all steps are green and non-zero on the first step that is not; resume
by re-running. There is no separate ledger: progress is derived from git plus
`build/steps.json`, so it cannot drift from the truth. Two cases avoid a full re-dispatch:

- A step that is non-green ONLY because its recorded verify is older than a later
  commit gets `record_verify` again, not a new step agent.
- After the per-step review (`core/skills/per_step_review.py`) the orchestrator writes
  `review: {state: "blocked"|"passed", at, round, commit}` into the step's `steps.json` record.
  A `blocked` marker keeps the step non-green until a NEW commit lands on it; the marker
  is then stale and is cleared on read. A `passed` marker whose `commit` is the step's
  current green commit means that commit is never reviewed again, and
  `build.max_reviews_per_step` (default 3) caps the review gates per step in one run.

The inline TDD loop stays the primary interactive workflow; `build-run` is the
hands-off path. `build.per_step_review_on_verify: true` additionally dispatches the
per-step reviewer (`core/agents/review/per-step.md`) whenever a step is non-green after
its verify.

**Budget counters** in `meta.json:budgets` (limits in `config/budgets.yml`):

| Counter               | Limit | Bumped when                              |
|-----------------------|-------|------------------------------------------|
| `red_test_fix_attempts` | 3   | test still red after impl change         |
| `mutation_fix_attempts` | 3   | mutation score below threshold           |
| `regenerate_impl_plan`  | 3   | human requests a fresh plan              |
| `rework_review_cycles`  | 3   | review sends back to build               |
| `xs_fix_attempts`       | 3   | XS fast-track: test still failing        |

Hitting a limit writes `meta.json:blocked_reason` and halts; the agent emits
`[!QUESTION]` or `[!CONFLICT]` and the human decides.

## Review

**Purpose (S/M/L).** Audit the implementation against spec/ADR — correctness,
completeness, quality, security, and scope.

- **Inputs:** the build diff, `spec.md`, `test-plan.md`, `design.md` (M/L),
  `impl-plan.md` (M/L), `build-log.md`.
- **Outputs:** `review-report.md` (findings + verdict).
- **Completion criteria:** `review-report.md` exists with a verdict; all critical
  findings resolved or accepted.
- **Ack options:** `--pick 1` approve (S → integrate, M/L → manual) · `--pick 2`
  request-changes → build:work.
- **Pitfalls:** scope creep not caught; a missing AC test; a security issue missed.

Findings are ranked using the four levels in [`severity-rubric.md`](../config/severity-rubric.md)
(the single source every review agent cites — not repeated here). A mandatory
external code-reviewer subagent runs before `review-report.md` is written, to catch
cross-file gaps internal review misses.

**Review cascade (KLC-175).** A review is three layers, so a typical S/M change
costs about one model pass instead of five. The cheap/full split is gone.

```text
layer 0  deterministic checks (AC test coverage, TDD order, drift, scope, sentinels)
         -> findings with kind "layer0"; never a model pass
layer 1  exactly one structured code-review reviewer
layer 2  specialists, each only on its signal:
         security      sentinel hit or a critical-tier file
         architecture  an added top-level public def/class (no leading `_`, not in tests or prose), or an added dependency edge
         performance   hot-path file (hot_path_globs or a trailing `# perf:hot` comment on a code line)
         deep-impact   as before
external reviewer: default-on for track L only; S/M opt in via reviewers.yml
```

Why: one reviewer reading one shared context finds most defects; specialists add
cost only when the diff gives a reason. Signals live in `core/skills/review_signals.py`.

**Fail-closed:** every signal is True, False or None (unevaluable: the sentinel
scanner or the classifier failed). A None signal plans its specialist (security for
`sentinel_hit`/`critical_tier`, architecture, performance, deep-impact) with
`planned_reason: "signal unevaluable"`, and the plan and the `review.py` output name
the signals concerned. If the whole signal evaluation raises, ALL specialists are
planned, because "unavailable" is not "no risk". On S/M that can exceed the pass cap
and need `--over-cap`. An unreadable manifest is not fail-closed: the plan carries the
note `manifest unreadable: ...; specialists not planned`. The report frontmatter
`review_depth` records the layers that EXECUTED (`L1` or `L1+L2`); older reports say
`cheap`/`lite`/`full`. Layer 1 covers correctness and baseline security itself; the
security specialist is the deep pass.

`scripts/review.py --diff` takes a patch file, `A..B`, `A...B` or `recorded` (the
ticket's pre-merge range, checked for ancestry and used only while HEAD is still its
head, else the live merge-base..HEAD); an unresolvable or empty range end exits 2.
For the in-client path `scripts/review.py --report --spec <spec>` renders the
ticket's `review-report.md` without a model (see the review agent, step 5).

**Shared context.** Each run writes `.klc/scratch/<KEY>/review/context.md` once
(diff, spec goals and ACs, test-plan table, decisions, module docs). Job cards
carry only its path plus an addendum of at most 1 KB; root CLAUDE.md and the
rule catalog are never inlined, and the severity rubric is named by path. Unusual
but deliberate: a headless dispatch cannot follow a path, so the runner inlines
`context.md` into every card, and the card's addendum (file filter and focus, at most
1 KB) as a text block: a headless specialist gets its filter as an instruction, not
as a filtered diff. The saving is therefore large in a client and in fewer passes,
and smaller headless. The report records both figures
(`inlined_bytes_in_client`, `inlined_bytes_headless`, both counting `adr_context`)
next to `planned_passes`, `executed_passes` and `review_duplicate_rate` (this run's
raw findings against their deduped pool; `n/a` when fewer than two reviewers
contributed).

**Where to look.** `review-report.md` ends its summary with a `## Where to look`
list built without a model (`core/skills/review_map.py`), and the GitHub summary
comment copies it. Each file appears once, under the first rule that fires:

| Tier | Rules |
|------|-------|
| critical | files named (as whole paths) by a `[!DECISION]` item or an ADR; plan steps addressing an AC when the spec has `risk_tags`; migrations and schemas; added public API; the critical tier of `config/tiers.yml` |
| important | MEDIUM findings assessed won't-fix (only when `--report --assessments` is given); plan steps carrying a DECISION; `core/agents/**`; git hotspots of the diff's own files (`where_to_look.hotspot_min_commits` commits in 90 days) |
| optional | generated files (`klc-plugin/**`, goldens, fixtures: never critical); service artefacts; files a layer-0 finding named |

A missing input only empties a tier; it never fails the report.

`cheap_escape_rate` (below) still reads older tickets that were cheap-reviewed.

**Review plan (KLC-120).** Before any job card or dispatch, `scripts/review.py`
(both the headless path and the in-client path via `--plan-only`) writes
`.klc/tickets/<KEY>/review/review-plan-r<N>.json` (one plan per review round; a
new diff starts round N+1 and carries the executed passes over): every pass it would run, with its source,
selecting rule, provider, model and status (`planned` / `executed` / `skipped`,
always with a reason when skipped). The manifest's layer-1 and layer-2 reviewers are listed, with `skipped` and a reason
when no signal fired. A fixed `per_step_build_review: "not
counted"` field states that the automatic per-step build review is outside this
inventory.

**Per-track cap.** `review.max_llm_passes` (`config/reviewers.yml`, default
`{S: 3, M: 4, L: 6}`) bounds the number of `planned`+`executed` passes; a missing
track key means no cap, and skipped passes never count. Over the cap,
`scripts/review.py` refuses whole — exit 2, the plan printed, no job card, no
dispatch — unless `--over-cap` is given, in which case it proceeds and the
rendered report frontmatter carries `cap_override: true` and the cap value,
alongside `planned_passes`, `executed_passes` and every skipped pass with its
reason.

**External reviewer** (default-on for track L; S/M opt in, `external_reviewer.enabled: true`):
runs on the model `config/models.yml`'s
`review-external` pseudo-phase resolves (anthropic by default; `model_ref` in
`config/reviewers.yml` names the phase, an explicit `provider`/`model` there
overrides it). Skip conditions (first match wins): `--no-external`,
`meta.review.skip_external: true`, or the resolved route needs something this
host lacks — an unset API key for `openai`/`google`, or a missing `claude` CLI
for `anthropic` (graceful; `klc doctor`'s `external-reviewer-key` check warns on
the same two conditions).

## Review-lite

**Purpose (XS).** Fast sanity check — ACs met, tests pass, no obvious issue. Blocks
only on CRITICAL (security, API break, data corruption).

- **Inputs:** the xs-build diff, `spec.md`. **Outputs:** a review decision; emits
  `REVIEW_LITE_PASS` or `REVIEW_LITE_CRITICAL`.
- **Ack options:** `--pick 1` approve → integrate · `--pick 2` request-changes →
  xs-build:work · `--pick 3` override.
- **Pitfalls:** over-analysing an XS ticket defeats the fast path.

## Manual

**Purpose (M/L, high manual estimate).** Human manual validation before
integration.

- **Inputs:** the build+review diff, the `test-plan.md` manual checklist, `spec.md`.
- **Outputs:** none as a file. `klc ack --note` records the verdict, note and time
  in `meta.json` under `manual`.
- **Ack options:** `--pick 1` passed → integrate · `--pick 2` failed → build:work.
- **Pitfalls:** skipping validation; a vague checklist; no rollback plan.

## Integrate

**Purpose.** Merge the feature branch to main, resolving conflicts if needed.
Integrate is the only merge/push phase — merge is always human (see the runner
guardrails).

- **Process:** rebase on the latest upstream main, resolve conflicts, push; the ack
  records two heads in `meta.json` under `integrate`: `branch_head` (project HEAD at
  the ack, usually the feature-branch tip) and `main_head` (local `main`, null when it
  does not resolve). A squash merge puts neither of them on main, so neither is called
  "the merge commit".
- **Ack options:** `--pick 1` merged (XS → learn, S/M/L → observe) · `--pick 2`
  conflict (human resolves, retry).
- **What the integrate ack scores.** The drift check, the retrieval evaluator and
  the integrate scope guard share one ground truth, resolved once per `klc ack`
  run in this order: `live-merge-base` (the branch diff against origin/main, used
  whenever it is non-empty), then `recorded-range` (the `pre_merge_range` that the
  build, review and manual acks record while the branch is unmerged; the latest
  non-empty range wins), then `none` (drift is skipped and retrieval is
  unavailable, with the reason named). The integrate ack is acked after the merge,
  so the recorded range is what it normally scores.
  Caveat: the range is exact only if no commit lands on the ticket branch after
  the last recording ack. A commit added after it is missed. An amend or rebase
  that removes a recorded commit can make the range over-count and trigger an
  integrate expansion block; update `meta.json:affected_modules` if that happens.
- **Pitfalls:** not rebasing before push → fast-forward rejection; force-pushing a
  shared branch. The two-remote publish flow is in
  [Dual-remote workflow](#dual-remote-workflow).

## Observe

**Purpose (S/M/L).** Monitor metrics and stability for a 24h window post-merge to
catch regressions early.

- **Inputs:** merged code + baseline metrics. **Outputs:** `observe.md` (metrics,
  alerts, rollback assessment).
- **Ack options:** `--pick 1` stable → learn · `--pick 2`/`3` regression/rollback →
  build:work.
- **Pitfalls:** ignoring an error-rate spike; no rollback plan; too short a window.

## Learn

**Purpose.** Write the retrospective — what went well, what could improve, lessons
learned, recommendations, action items — and archive.

- **Inputs:** all ticket artefacts + `phase_history`. **Outputs:**
  `retrospective.md`, at most 40 lines, with three fixed headings:
  `## What the gates missed`, `## Token cost by phase` (measured attempts only,
  `n/a` when none) and `## One process change`. A longer file or a missing heading
  raises a surface-only advisory at the learn ack. Discovery reads the same
  headings when it looks at related tickets.
- **Ack options:** `--pick 1` archive · `--pick 2` extract-to-CLAUDE.md.
- **Pitfalls:** a generic retro ("everything was good"); no process change; blaming
  instead of learning. If one lesson shows up in five retros in a row, promote it
  from a retro note to a rule in this doc.

---

## Verbs

```
klc intake <key> [--kind feature|bug|tech] "<desc>"
klc status <key>               # vertical path view
klc next   <key>               # :ack → next phase :work
klc ack    <key> [--pick N]    # :ack-needed → :ack
klc ship   <key> [--pick N]    # ack + next in one step
klc step   <key> <N>           # regenerate minimal TDD step card (build only)
klc work   <key>               # read-only: the next action (card/outputs/verify)
klc jump   <phase> <key> [--yes]   # cross-cut to any phase :work
klc abort  <key>               # cancel current :work → previous :ack
klc abort  <key> --cancel --reason "<why>"   # terminate to the `cancelled` terminal
klc run    <key> [--cap N] [--json]   # autonomous runner (single-user / feature-off)
klc publish <key> [--branch B] # read-only: push the review verdict to the ticket's GitHub PR
klc steal  <key> [--ttl-minutes M]    # take over a stale holder slot (TTL-gated)
klc retrack <key> <XS|S|M|L> --reason "..."   # operator-only track change, audited
```

`klc abort --cancel` moves a ticket that will never ship to the terminal
`cancelled` state (parallel to `archived` but NOT counted as completed work by
metrics); `--reason` is required. `klc run` walks a ticket through the state machine
on its own, auto-acking clean conditional gates and pausing at every decision gate
/ guardrail (see [Autonomous runner](#autonomous-runner-klc-run)); it refuses when
the multi-user state feature is ON. `klc publish` and `klc work` are strictly
read-only (no phase advance, no meta write, no Jira drain).

Operational (non-phase):

```
klc board                      # kanban view across tickets
klc board --epic <ROOT>        # epic-scoped view (state / ready set) — see Epics
klc doctor                     # install health check
klc metrics <key>              # per-ticket JSON
klc metrics --rollup           # 30-day aggregate
klc init [--scan-only|--auto|--finalize]
klc update [--regen] [--force]
klc state init [<remote>]      # materialize the klc-state branch as a .klc/ worktree
klc jira-sync [--dry-run]      # flush Jira push queue
klc jira-sync status           # queue size + oldest entry age
klc scope-fix <key> (--modules a,b,c | --add a,b | --remove a,b) [--reason ...]
klc scope-fix --migrate-vocabulary [--dry-run] [--json]   # batch: rewrite every
                                          # archived ticket's affected_modules to
                                          # the module vocabulary (see below)
klc migrate-notes [--dry-run] [--json]   # one-time: cap over-long phase-history
                                          # notes to a pointer at their ack
                                          # advisory artifact (see below)
```

**Happy path (clean S ticket).** Every forward `klc ack --pick 1` also advances to
the next phase's `:work` (the pick's `goto` is `next`), so the happy path is
**ack-only** — you never run `klc next` from a `:work` state:

```text
klc intake <KEY> "one-line description"   # → intake:ack-needed
klc ack    <KEY> --pick 1                 # confirm-route → discovery-lite:work
   # agent writes spec.md (## Approaches: >=2 approaches + a recorded "Picked:"), impl-plan.md
klc ack    <KEY> --pick 1                 # approve → build:work
   # on a feature branch: write code. Commit the failing test BEFORE the fix for each step,
   # then run `klc step verify <KEY> N` — build ack enforces red-before-green from git history
   # and reads the recorded verify from build/steps.json.
klc ack    <KEY> --pick 1                 # approve → review:work   (agent writes review-report.md)
klc ack    <KEY> --pick 1                 # approve → integrate:work ; merge the feature branch
klc ack    <KEY>                          # merged → archived (observe + learn condition-skipped for a clean S)
```

### Post-archive scope correction — `klc scope-fix`

`meta.affected_modules` records a ticket's planning slice. During work it is
corrected at `ack` (each `ack` runs a `state_tx` that commits and CAS-pushes the
ticket subtree). Once a ticket is **archived** no further `ack` runs, so an edit to
the slice has no `state_tx` to sweep it. `klc scope-fix` is the first-class durable
path: it edits `affected_modules` inside the same `acquire_lock → state_tx` envelope
every state write uses. It **refuses any non-archived ticket** (correct those at
`ack` — update `affected_modules` rather than fighting it, since it drives the
scope-expansion hard-fail). Three mutually-exclusive modes: `--modules a,b,c`
(replace), `--add a,b` (union), `--remove a,b` (drop). Malformed lists are rejected
before any write; unknown module names are a non-fatal advisory; each correction is
a `scope-fix` entry in `meta.phase_history`.

### One-time vocabulary migration — `klc scope-fix --migrate-vocabulary`

A fourth mode on the same verb (KLC-111), for the one-time cut-over from the
pre-KLC-074 file-stem `modules.json` to the deterministic directory-level one. It
takes NO ticket argument — it batch-rewrites `meta.affected_modules` of every
**archived** ticket whose entries fall outside the module vocabulary (the `name`
set of `.klc/index/modules.json` plus the configured `scope.infra_paths` list),
mapping a legacy name by exact module name, tracked file path, or basename stem.
A name matching only as a directory prefix of other module names is reported
**ambiguous** and never auto-expanded; a name matching none of the three rules is
reported **unmappable**. Both lists are printed, never silently dropped. Each
rewritten ticket is corrected inside its own `acquire_lock → state_tx`, exactly
like the three ticket-scoped modes, and gets exactly one `vocabulary-migration`
entry in `meta.phase_history`; a re-run over an already-migrated ticket is a true
no-op (the audit entry is the sentinel). A live (non-archived) ticket is refused,
same as the three ticket-scoped modes.

The operator sequence, run once, from `/home/ek/projects/klc` (or your
`PROJECT_ROOT`):

```text
# 1. rebuild the deterministic index in the .klc worktree (bound to klc-state).
#    This replaces the STALE, pre-KLC-074, 29-name file-stem modules.json with
#    the current directory-level module set — review this step on its own
#    before any archived ticket is rewritten against it.
klc init --scan-only

# 2. commit the rebuilt index on klc-state
git -C .klc add index/
git -C .klc commit -m "KLC-111: rebuild modules.json at directory granularity"

# 3. dry-run the migration first — read the unmappable and ambiguous lists,
#    and confirm the projected in-vocabulary share, before applying
klc scope-fix --migrate-vocabulary --dry-run --json
klc scope-fix --migrate-vocabulary
```

---

## Human gates

Every phase with `pick_required: true` is a gate — the human must choose a pick
before `next` proceeds.

| Gate              | Phase                          | Tracks  |
|-------------------|--------------------------------|---------|
| confirm intake    | `intake:ack-needed`            | all     |
| pull-ready        | `discovery:ack-needed`         | XS S M L |
| accept test plan  | `acceptance-test-plan:ack-needed` | S M L |
| direction         | `design:ack-needed`            | M L     |
| detail test plan  | `detailed-test-plan:ack-needed`| M L     |
| xs build          | `xs-build:ack-needed`          | XS      |
| build             | `build:ack-needed`             | S M L   |
| review-lite       | `review-lite:ack-needed`       | XS      |
| merge approval    | `review:ack-needed`            | S M L   |
| manual check      | `manual:ack-needed`            | M L     |
| observe outcome   | `observe:ack-needed`           | S M L   |
| learn outcome     | `learn:ack-needed`             | all     |

Mechanical pre-conditions block `ack` before the human pick is offered:
- **discovery-lite ack (S)**: spec self-review clean; ≥2 approaches + pick in
  the `## Approaches` section of `spec.md`; `impl-plan.md` required and must pass `impl_plan_violations()`.
- **design ack (M/L)**: `design.md` (with `## Options` and a `Picked:` line) and `impl-plan.md` must exist, be
  non-empty, and pass the plan-completeness gate.
- **build ack (S/M/L)**: every plan step must be green in `step_state` — RED then
  GREEN commits, and a valid `klc step verify` result in `build/steps.json`.

The design agent and test-planner (M detailed mode) self-review `impl-plan.md`
before emitting their completion signal — scanning every `## step-N` for missing
`REQUIRED_STEP_FIELDS`, placeholder tokens, and empty fences — a first line of
defence before the mechanical gate at ack.

### Ack advisories

Every completion gate's non-blocking observations (a coverage hint, a routed
review decision, a drift note, …) are **advisory records**, not a joined string
(KLC-117). One aggregator, `core/skills/advisories.py`, owns the schema:

| Field      | Meaning                                                        |
|------------|-----------------------------------------------------------------|
| `source`   | the producer that emitted the record (`ac-coverage`, `spec-review`, …) |
| `severity` | `high` \| `medium` \| `low` \| `info`                          |
| `code`     | a stable identifier for the kind of finding (`<source>.<condition>`) |
| `message`  | the human-readable sentence                                    |
| `ref`      | what the record points at (an AC id, a module name, …), or empty |

A record with an unknown or missing severity normalises to `info` and raises a
companion flag naming the offender — severity is always declared by the producer
that knows the condition, never inferred downstream. On the **persisting** ack
path the collected records are written to
`<ticket-dir>/advisories.json`, one file per ticket keyed by phase id (per phase
the generation timestamp and the record list; a clean ack writes no key). A
missing key reads as clean only when the ticket history records the phase
reaching `ack-needed` and that entry does not say `advisories: write-failed`; an
unreadable `advisories.json` is moved aside to `advisories.corrupt-<ts>.json`
and, while that file exists, every phase of the ticket reads dirty; the sibling is local evidence (never committed to klc-state), and the operator deletes it after inspection, which returns the gate to normal. A **read-only probe**
(`persist=False` — `klc remind`, gate-policy signal collection) writes nothing.
The gate's return value is a one-line **summary** in place of the old joined
prose — `2 high · 3 medium · 11 info — see <path>`, or the empty string when no
producer emitted anything; `high`/`medium` counts always render, `low`/`info`
only when non-zero.

The phase-history note built at ack stays within **200 characters** including
that summary (`advisories.cap_note`) — `lifecycle.set_state` itself is untouched
and keeps storing whatever note it is handed, verbatim; the cap is enforced by
the caller that builds the note. The **severity threshold** at or above which
the gate-policy `advisory` signal is dirty is an operator-settable knob,
`advisory.threshold` (default `medium`), resolved through the same
project-over-framework `settings.yml` ladder as every other knob (see
`config/settings.yml`; validated by `klc doctor`). `klc status` and
`klc work` print every `high`/`medium` record in full and a bare count of the
rest, reading the artifact only (never the gate, so neither verb spawns a git
subprocess on a routine call). A one-time, operator-invoked verb,
`klc migrate-notes`, replaces every already-stored note over the cap with a
truncated note plus a pointer to its phase's artifact — idempotent (a second run
is byte-identical) and archive-aware (an archived ticket is migrated exactly
like an active one, since it lives in the same `.klc/tickets/<KEY>/` tree).

---

## Conditional phases

Some phases are skipped automatically based on `meta.json` fields set by discovery
agents. Skipped phases are recorded in `phase_history` as `event: skipped`.

| Phase     | Runs when                                                              |
|-----------|------------------------------------------------------------------------|
| `observe` | `meta.risk_tags` contains any of: `user-facing`, `data`, `security`, `migration` |
| `learn`   | Always for M/L. For XS/S: when `meta.rework_count` > 0, OR `meta.regression_observed == 1`, OR `meta.budgets` any overrun |

Discovery agents must set `risk_tags: [...]` in `meta.json` (use `[]` for pure
tooling/config changes). The `phases.yml condition:` expression language:

```
meta.<path> in ['v1', 'v2']      # true if value or any list element matches
meta.<path> not in ['v1', 'v2']
meta.<path> > N   |   >= N   |   == N
meta.<path> any_overrun           # true if any dict value > 0
<expr> OR <expr>                  # short-circuit or
```

---

## Signals that escalate to human

- `CONFLICT` item in any artefact.
- A budget counter at limit (`blocked_reason` in `meta.json`).
- `rework_count[phase] ≥ 3` — recommend escalation to lead.
- Scope creep: the diff touches modules outside `affected_modules`, or files outside
  all known module prefixes (`unknown_files` in scope_delta). At `review:ack`,
  missing `modules.json` is a hard failure — run `klc init --scan-only`.
- XS: `XS_BLOCKED` from xs-fasttrack or review-lite.

---

## Inline item format

All artefacts share a markup for facts, assumptions, decisions, and open questions.
Items are indexed by `core/skills/items.py` into `.index.json` and checked by the
consistency gate before integrate.

```
[!FACT F-001]       src=path/to/file:42  verified=2026-05-21  evidence=observed
[!ASSUMPTION A-001] if-false=rollback-to-option-B  evidence=assumed
[!DECISION D-001]   owner=impl-agent  date=2026-05-21  refs=step-3  evidence=read src=core/skills/items.py:133
[!QUESTION Q-001]   blocks=discovery
[!CONSTRAINT C-001] source=security-review
[!CONFLICT C-001]   (scope creep / infeasible option / broken assumption)
```

`CONFLICT` always halts the agent and requires human resolution. `QUESTION` with
`blocks=<phase>` prevents phase advance until answered.

### Provenance (`evidence=`, KLC-116)

A FACT, ASSUMPTION or DECISION may declare `evidence=observed|read|assumed` — how the
claim was established, not just what it says. Each label brings its own companion, and
the consistency gate blocks a DECLARED label that arrives without it:

- `evidence=observed` — the author ran something against the real system. Companion: a
  fenced block holding the command and its output, in the item's own quoted body or
  immediately after it (no other item header in between).
- `evidence=read` — the author took the claim from a source that can be reopened.
  Companion: `src=<file>:<line>` that resolves to a real path in the repository (the line
  number itself is not re-verified — see the periodic verification pass for staleness).
- `evidence=assumed` — the author does not know; the claim stands until contradicted.
  Companion: a non-empty `if-false=<consequence>`.

**Migration rule**: an item written before this attribute existed carries no `evidence=`
at all, and that is fine — absence predates the rule and is never retroactively enforced.
The consistency gate only warns (naming the artefact and the count) on absence; it blocks
only when a label IS declared but its companion is missing, or when a load-bearing design
decision (the recommended option's decisions, plus any item a plan step's `Depends on:`
names) is `assumed` or undeclared at the M/L design acceptance gate.

---

## Independent spec/test-plan/impl-plan review

The mandatory code reviewer validates code against the spec **as written**, so a
flawed spec is a structural blind spot — "correctly built the wrong thing" is never
caught. KLC-084 shifts that discipline LEFT: at the **spec phase** an **independent**
reviewer (fresh, no build context, `klc-plugin/agents/spec-reviewer.md`) reviews `spec.md`
before the phase completes, exactly as the code reviewer runs before
`review-report.md`. The orchestrator/autorunner spawns it (not a hard-coded LLM call
in the state machine); the plumbing is `core/skills/spec_review.py`.

Like the code reviewer it is **fail-open**: it surfaces and records, it does not
block the ack. It emits **two** classes, and keeping them apart is what makes it
low-noise:

```text
findings[]              OBJECTIVE, the reviewer decides -> to be fixed:
                        infidelity to raw.md · code-contradiction · constitution
                        violation · untestable/ambiguous AC · internal contradiction.
                        Recorded to findings.json (kind spec-review) AND surfaced at the
                        ack as a collapsed count ("N finding(s) recorded (M high)
                        — assess before build"). The BUILD agent (core/agents/
                        impl.md) reads that file and assesses each (fix/won't-fix)
                        before writing code, exactly as review-report assesses the
                        code reviewer's findings.
decisions_to_confirm[]  SUBJECTIVE, the HUMAN decides -> scope · tradeoff ·
                        ambiguous-intent. Each carries a RECOMMENDED answer. The
                        reviewer NEVER adjudicates these; the plumbing ROUTES them
                        into the discovery/design ack's advisory records — the
                        EXISTING `decision`-level gate — so the operator resolves
                        them there. No new human gate is introduced. A routed
                        decision (and a findings summary carrying any high
                        finding) arrives as a `high` advisory record (KLC-117);
                        see [Ack advisories](#ack-advisories).
```

Anchors the reviewer checks against (reused single sources): the **constitution**
via the KLC-082 reader (`core/skills/constitution.py`), the **KLC-083 self-check**
findings (`spec_selfcheck.py`), and the **current code** (LSP) for feasibility /
non-contradiction. Only correctness of intent has no anchor → it becomes a
`decisions_to_confirm[]`.

**Track scaling** (`spec_review.should_run`): full on M/L, cascade on S, skipped on
XS. At the spec phase the only escalation signal available is a **risk tag** — there
is no diff yet, so the sentinel / scope-expansion signals do not fire here.
**Read-only safety**: the advisory probe (`persist=False`) surfaces the same lines
WITHOUT writing the spec-review records to `findings.json`; only the persisting ack path records.
**Degrade-not-fail**: absent constitution / self-check / reviewer output — or a
valid-JSON-but-wrong-shape verdict — degrades to a surfaced note; the phase still
completes.

**Generic seam (KLC-085 reuse)**: `spec_review.py` is parameterised by a
`ReviewKind` descriptor — reviewer prompt · artifact · output file **and its own
`finding_categories` / `decision_topics`**. `validate()` reads the vocabulary FROM
the active kind and `route_decisions()` labels advisories with `kind.name`, so the
test-plan reviewer reuses the same parse / validate / route / record / track-scale
plumbing with its OWN classes (uncovered-ac, weak-assertion, missing-edge-case) and
a `test-plan-review[…]` label — no second copy, no validator fork.

**Build-time assessment of test-plan-review findings (KLC-093)**: the test-plan
reviewer's OBJECTIVE `findings[]` are recorded to `findings.json` (kind `test-plan-review`)
via the same seam. The BUILD agent (`core/agents/impl.md`) reads that file too —
right beside the spec-review records — and assesses each finding (fix/won't-fix)
in `build-log.md` before writing code, with the same high-severity-unaddressed →
stop-and-ask rule and the same degrade-when-absent behaviour. The schema is
identical — `findings.Finding` (`kind · round · rule_name · severity · file · line · title ·
body · fix`) — so it is the same assess logic for both kinds, symmetric with how
`review-report` assesses the code reviewer's findings.

**Independent impl-plan review (KLC-094 · V-01)**: the trilogy's third reviewer, one
artifact further LEFT again — onto `impl-plan.md`. A fresh, adversarial reviewer
(`klc-plugin/agents/impl-plan-reviewer.md`) reads the plan against the spec's SAOC ACs
**and** the recorded `kind: spec-review` records in `findings.json`, and emits the same two output
classes through the SAME generic seam bound to a new descriptor
(`implplan_review.IMPL_PLAN_REVIEW`) — OBJECTIVE `findings[]` (`missing-step` ·
`wrong-sequencing` · `untestable-step` · `unaddressed-ac` · `infeasible-red-green`)
and SUBJECTIVE `decisions_to_confirm[]` (`sequencing-tradeoff` · `scope`). No forked
parser, validator, or gate: `implplan_review.py` carries only the descriptor and a
thin `consume` wrapper (the impl-plan already has a DETERMINISTIC gate —
`impl_plan_check` + `plan_quality` — that blocks on mechanical defects at the ack;
this adds only the independent JUDGMENT above it). The seam is wired at the ack that
FINALIZES `impl-plan.md` — `can_complete_discovery_lite` on S, the design phase on
M/L — and threads `persist` so a read-only probe surfaces the advisories without
writing. The BUILD agent (`core/agents/impl.md`) reads the `kind: impl-plan-review` records of `findings.json`
right beside the spec-review and test-plan-review records and assesses each finding
(fix/won't-fix) in `build-log.md`, with the same high-severity-unaddressed →
stop-and-ask rule and the same degrade-when-absent behaviour — one symmetric
discipline for THREE reviewers.

**One Finding shape, validated intake, one pool (KLC-127).** Every reviewer —
the three above, the code reviewer and the external reviewer — returns ONE
Finding shape. `python3 core/skills/handback.py take --kind <kind> --ticket
<KEY> --file <verdict>` is the single intake: it validates the shape, refuses
anything else with the error list, appends the verdict's records, tagged with `kind` and `round`, to the ticket's one
`findings.json`, and counts the pass. `python3
core/skills/findings.py pool --ticket <KEY>` merges every record of `findings.json` into
`review/findings-pool.json` (`raw_count`/`pooled_count`/`duplicate_rate`),
which the report renders its table from. The one-off migration of the
pre-KLC-127 findings files and verdict blocks is KLC-154.

---

## Gate-policy layer

Every pick in `phases.yml` carries an explicit `gate` level that classifies how much
human judgment it needs; the classification drives `klc ack --auto`.

| Level | Meaning | Auto-proceed? |
|-------|---------|---------------|
| `auto` | Mechanical transition — no judgment needed | Always |
| `conditional` | Proceed only when all safety signals are clean | When clean |
| `decision` | Irreducibly human — spec approval, design pick, manual sign-off, merge | Never |

**Decision gates** (always pause, even with clean signals): discovery-lite/discovery
approve (spec sign-off); design (all option picks + rework + revise-impl-plan);
manual (passed/failed); integrate (merge is always human). All other picks are
`conditional`.

`klc ack <KEY> --auto` applies the gate policy to the unambiguous forward pick: an
`auto` pick always proceeds; a `decision` pick always pauses (exits non-zero naming
the gate); a `conditional` pick proceeds only when all seven signals are clean.
Plain `klc ack <KEY> [--pick N]` consults no policy.

**Seven signals** (`gate_policy.collect_signals`):

| Signal | Source | Clean when |
|--------|--------|-----------|
| `advisory` | `advisories.read(ticket, phase_id)` (the persisted artifact) | no record at or above `advisory.threshold` (default `medium`); absent/unreadable artifact is dirty |
| `scope_expansion` | `scope_delta.compare` | no expansion, no skipped |
| `sentinels` | `scan_sentinels.scan_diff(git diff main..HEAD)` | no hits |
| `mutation` | `meta.budgets.mutation_fix_attempts` vs limit | below limit |
| `budget_overrun` | all budget counters vs limits | all below limit |
| `verdict` | `## Verdict` of `review-report.md` | APPROVED / PASS, no changes-requested |
| `route_confidence` | `meta.route_confidence` | "high" or "medium" |

**Fail-closed**: any signal absent from the dict is treated as dirty; any source
failure (no git, no `modules.json`, no `review-report.md`) also yields a dirty value.

---

## Autonomous runner (`klc run`)

`klc run <KEY>` is a headless, single-user Python driver that walks a ticket through
the state machine on its own, reusing the gate-policy through the SAME
`klc ack --auto` path a human takes. Each iteration reads `meta.json:phase`, and at
a `:work` state dispatches the phase agent (build via the orchestrator, others via
`runner.run_agent`), then calls `klc ack --auto` — which auto-detects completion,
walks `:work → :ack-needed`, and applies the gate policy in one call.

**Guardrails (the loop PAUSES, never proceeds):**

| Guardrail | Fires when |
|-----------|-----------|
| outward-facing / irreversible | the next phase is `integrate` (the only merge/push phase) |
| budget ceiling | any `meta.budgets` counter is at/over its limit |
| consecutive-auto cap | `N` consecutive auto-transitions (`--cap`, default 20, `KLC_AUTORUN_CAP`) |
| decision gate | the forward pick's gate is `decision` |
| dirty conditional gate | a `conditional` gate has a dirty signal |

Every pause names the guardrail/gate, notifies on stderr, and is recorded in
`.klc/tickets/<KEY>/run-log.md`. **It never merges or pushes** — it pauses at
`integrate:work` and hands off. rc `0` = terminal/clean stop (archived); rc `2` =
paused (human must act); rc `1` = refusal. It runs only when the multi-user state
feature is OFF; if ON, `klc run` refuses (rc 1). The consecutive-auto cap is a
runaway backstop kept in the framework `config/budgets.yml`, deliberately out of
`meta.json:budgets`.

---

## Orchestrator (`/klc:run`)

`/klc:run <KEY>` runs a ticket through its lifecycle without a human re-reading every
phase's artifacts. It is **prompt-driven main-loop instructions**
(`klc-plugin/skills/run/SKILL.md`), not a hidden Python driver — interactive phases
(clarify / human gates) can only be run from the CC main-loop or Task-tool;
`runner.py` (headless) is forbidden from touching them.

Each iteration: `klc status <KEY> --json` → `phase_resolver.resolve_phase` (the
single phase→agent source of truth: prompt, model, `agent_type`, `runs_inline`,
`interactive`, derived from `phases.yml` + `models.yml` + `meta.json:track`). If
`resolved.interactive`, stop and hand to the human; otherwise dispatch (inline for
XS fast-track, else `Task(subagent_type=resolved.agent_type, …)`), parse the
subagent's structured completion signal, and on a clean `"done"` with no blocking
questions run `klc ack --auto` + `klc next`.

**Completion signal.** Every `klc-<phase>` subagent ends with one fenced JSON block:

```json
{"phase":"design","signal":"done","artifacts":["design.md","impl-plan.md"],"blocking_questions":[],"next_action":"ack"}
```

`core/skills/run_signal.py` parses it (`parse_signal`) and applies the retry policy
(`should_retry`): an unparseable/mismatched signal retries the same phase once; a
second consecutive failure stops the loop.

**Regenerating the plugin delivery layer.** The whole `klc-plugin/` tree — agents,
the passthrough skills, the command stubs, `.claude-plugin/plugin.json` — is derived
from source by `plugin_gen.py`; nothing under `klc-plugin/` is hand-maintained.
After editing any `core/agents/*.md` prompt or the `VERB_SPECS` verb dictionary in
`core/skills/plugin_gen.py`, run `python3 core/skills/plugin_gen.py` and commit the
regenerated files. The drift-guard `tests/test_plugin_agents_in_sync.py` reddens on
any stale artifact, and `hooks/pre-commit` runs `plugin_gen.py --check-if-staged`
and hard-fails the commit on drift.

**Mandatory intake clarify gate.** `core/phases/intake.py` stamps
`meta.json:clarify_required = true` whenever `route_confidence == "low"`. The
orchestrator loop is the only place with an interactive channel, so it owns firing
the clarify pass (one `AskUserQuestion`, style from `config/clarify.yml`, fail-closed).
"Nothing to add" is a valid, complete answer — mandatory means the gate always
*fires*, not that the human must produce content. Answers are written back into
`raw.md`, the route is recomputed, and the stamp cleared before discovery runs.

---

## Token telemetry & budget guard

**Warn-only real-spend check (KLC-174).** The old card-size gate (an estimate of
the prompt, bytes / 4, against fixed soft and hard limits) is gone: an estimate
of the card says little about what a ticket really costs, and a hard limit could
stop a dispatch for no real reason. In its place `budget_guard.real_spend_warning
(track, ticket)` looks at REAL spend. It sums the measured input of the current
ticket (`provider` and `transcript` attempts) and compares it with 1.5 times the
median per-ticket total of the last 10 archived tickets on the same track. If the
ticket is above that line, the `/klc:run` orchestrator shows one warning line and
carries on. With no measured data the check says nothing. It never blocks. The
window and the factor live in `config/budgets.yml` under `real_spend_warn`.

No writer produces an `estimated` attempt any more (card renders, the headless
runner without usage, the signal fallback and review-pass records all record
nothing without real usage). Archived metas keep their old `estimated` records,
and the rollup still reads them into the `estimated` bucket, so the rows below
describe both the historical corpus and what is written today: only `provider`,
`transcript` and `signal` are written now.

`meta.json:metrics.tokens.<phase_id>` is an append-only **attempts list**
(`{"attempts": [...], "legacy": <pre-KLC-119 record, if one existed>}`), not a
single overwritten record: a rework or retry pass is counted, never erased.
Each attempt carries an id (assigned by the writer), `in`/`out`/`cache_hit`,
`source`, and the measured card size where one exists. `write_token_metrics`
is the single writer of this key; nothing else in the codebase assigns into
it (`budget_guard.find_second_writers` is the source-level gate). KLC-120
adds one more optional field, `reviewer`: present (never null) on an attempt
that recorded an executed review pass, absent on every other attempt.
KLC-133: the headless `scripts/review-runner.py` no longer writes an attempt
of its own — it delegates the ticket, the `reviewer` tag and its job card's
size to `run_agent`, which writes exactly one attempt per dispatch (see
"Measured headless runs" below); the in-client path still writes it via
`python3 core/skills/review_plan.py record --ticket <KEY> --reviewer <name>`
(idempotent — a repeated `record` for the same pass of the same run
collapses to one attempt).

**Attempts, the journal and the drain.** A telemetry write must never modify
`meta.json` — a tracked file on the shared `klc-state` branch — outside an
open `state_tx` transaction (that exact mistake shipped once, in KLC-118, and
was caught only by the soak/fuzz concurrency suites). So the writer is
transaction-aware: when a transaction is open for the ticket it appends
directly into `meta.json`; otherwise it buffers the attempt into a derived,
untracked per-ticket journal (`<card root>/<KEY>/telemetry.jsonl`). The next
`state_tx` for that ticket drains the journal into `meta.json` before its own
body runs, on BOTH of its branches (feature-ON and the headless runner's
feature-OFF path) and inside the same rollback protection as the rest of the
transaction — a drain failure is restored and swallowed, never taking the
verb down, and the journal simply keeps the attempt for a later retry.

**What each dispatch path can honestly report:**

| path | what produces the number | honest `source` |
|---|---|---|
| headless runner, envelope with input and output tokens | the CLI's own `usage` and `total_cost_usd` | `provider` |
| headless runner, failed run that still reported usage | the same, with `failed: true` | `provider` |
| headless runner, no or malformed envelope | the prompt's measured size | `estimated` |
| `/klc:run` Task dispatch | the dispatch card's measured size | `estimated` |
| a subagent whose host reports its own usage | the completion signal's `tokens` | `signal` |
| human copy-paste (`klc next` / `klc step` / `klc jump`) | the paste card's measured size | `estimated` |
| in-session agents, the hand-run external reviewer (F-009), the ticketless indexing agents of `scripts/init.py` | no envelope exists at all | `estimated`, or nothing (no ticket to attribute to) |

The `provider` row lands in `meta.json` only on the ticket's *next*
`state_tx` — `runner.py` opens no transaction of its own, so a headless
`provider` attempt is buffered in the journal first and promoted by the
following transition (in practice, `autorunner`'s own `ack --auto` right
after the dispatch).

**Measured headless runs (KLC-133).** `run_agent` parses the WHOLE headless
envelope the CLI prints (`claude -p --output-format json`, single object or
`--verbose` array — the last `type: "result"` element's own `usage`/
`total_cost_usd`/`is_error` win) and writes ONE attempt per dispatch,
whether the caller passed `ticket=` or the separate
`telemetry_ticket=`/`telemetry_phase=` tags (the review runner and the build
orchestrator's default dispatch use the latter, so telemetry attribution
never triggers the C-005 interactive-park guard, which keys on `ticket=`
alone). A measured (`source="provider"`) attempt carries `cache_write`
(the CLI's `cache_creation_input_tokens`), `cost_usd` and `num_turns`/
`duration_ms`; `run_pass` (`"step"` / `"per-step-review"` /
`"per-step-fix"`) tags a build-orchestrator dispatch, `step` its impl-plan
step number, and `failed: true` marks a dispatch that returned a non-zero
rc, whose envelope's own `is_error` was `true`, or whose dispatch
succeeded (rc 0) but reported `is_error: true` with no usable token counts
at all — the same measured fields are copied in either way, so a rollup
can tell "this run cost real money and still failed" from "nothing ran",
and an `is_error` run never counts as an executed, successful review pass
either way. A dispatch that returns no parseable envelope (plain text, or
a genuinely failed run with no usable stdout) falls back to
`source="estimated"` (byte-measured) or records nothing at all, exactly as
it always could.

**One basis per attempt (step-10 review-fix).** The four token fields
come from the LAST result element's `modelUsage` sum when every model
entry there is internally consistent (one wrong-typed or renamed field on
ANY model makes the whole block unusable, never a partial/undercounted
sum — the parser falls back to that element's raw `usage` block instead).
Because `modelUsage` is already whole-run cumulative (Q-009), `num_turns`
and `duration_ms` are summed across EVERY result element of a `--verbose`
array — not just the last segment's — so they share that same
whole-run basis instead of understating a multi-segment or async-subagent
run. `cost_usd` is cross-checked the same way: when the modelUsage-derived
cost disagrees with the element's own `total_cost_usd`, the modelUsage
figure is recorded — **still copied verbatim from the CLI's own reported
costUSD figures, never recomputed from a token count and a price table** —
and the optional `cost_basis` key (currently always `"modelUsage"` when
present) names why; absent when the two already agreed, or when
`total_cost_usd` was absent from the envelope in the first place (nothing
to cross-check, so nothing to correct).

**Which runs are measured, which stay estimated.** Measured
(`source="provider"`): every runner-dispatched headless call — a build step,
a per-step review or fix pass, a headless reviewer dispatch, and the
autorunner's own non-build phase dispatch. Estimated, by construction, not
by omission: a rendered prompt card's own `render_card` attempt (a SEPARATE
attempt from the run it precedes, never merged with it); an in-session
Claude Code Task subagent (no envelope reaches it — see below); the hand-run
external reviewer of F-009, who pastes a card into a chat outside any
runner; and the ticketless indexing agents of `scripts/init.py`, which have
no ticket to attribute a `provider` attempt to in the first place.

**`in` versus total input.** A provider attempt's `in` is only the
UNCACHED input tokens the CLI billed for that turn; the run's REAL total
input is `in + cache_hit + cache_write` (cache reads plus cache writes are
still input the model processed). An `estimated` attempt's `in` measures the
WHOLE rendered card, so the honest comparison — used by both
`estimator_calibration` and `measured_per_ticket` below — is the estimate's
`in` against a provider attempt's total input, never against its bare `in`.

**A measured before/after, from the command line.** A review normally runs
in-session (estimated). To get MEASURED before/after numbers for a review
change, run it headlessly: `RUN_LOCAL_SUBAGENTS=1 REVIEW_RUNNER=scripts/review-runner.py`
dispatches every reviewer card through `scripts/review-runner.py` (see
"Prompt cards" and `core/agents/review.md` for the full recipe), which now
writes a real `provider` attempt per dispatch instead of a byte estimate.

A Claude Code Task subagent is not shown its own token usage, so on this host
the interactive `/klc:run` path is **`estimated`-only** — the completion
signal's `tokens` field is a forward-compatible channel for a host that DOES
expose usage to the agent (the shared `completion-signal.md` include asks for
it only conditionally, exactly for this reason), and it is expected to record
**zero** `signal` attempts on this host today. That is a host property, not a
bug, and a reader of the rollup should not mistake the resulting large
`estimated` share for something the framework could trivially "fix" — the
next honest number needs a host that shows an agent its own usage.

**The rollup.** `klc metrics --rollup` aggregates attempts (committed
`meta.json` UNION any still-undrained journal entries, de-duplicated by id)
by phase per track into `.klc/knowledge/process-metrics.json`, with a
per-phase `source_counts` split three ways (`provider`/`signal`/`estimated`)
so an estimate is never presented as a measurement. KLC-133: no figure in a
phase entry is ever averaged over more than one source — the old mixed
`avg_in`/`avg_out`/`avg_cache_hit` is gone, replaced by a `by_source` object
keyed `provider`/`signal`/`estimated`, each with its own `samples`,
`avg_in`, `avg_out`, `avg_cache_hit`, and `provider` additionally with
`avg_cache_write`, `avg_num_turns`, `cost_usd_total` (the CLI's own figures,
summed, never recomputed) and `failed_samples` — a failed attempt still
counts in `samples`/`failed_samples`/`cost_usd_total`, but never in an
average. It also reports two numbers KLC-120 is scoped to move:
`prompt_bytes_per_ticket` (the average measured card size per ticket in the
track, summed over `estimated` attempts only — a `provider` attempt is never
double-counted into it) and `review_passes_per_ticket` (`{actual, expected,
ratio}`, with `expected` derived from the track's own phase list crossed
with a table of review artefacts, their host phases and the ordinal of the
first ticket that carries them — a degraded review only ever lowers
`actual`, never `expected`, so a degrade reads as a degrade rather than a
saving). Per track, `measured_per_ticket` reports `review` and `build`
independently, each with `tickets` (fully measured — every tagged run
attempt of that phase is `provider`), `partial_tickets` (a mix of `provider`
and non-`provider` tagged attempts — a ticket with NO provider attempt at
all, or whose tagged provider attempts ALL failed, counts in neither), and
`avg_total_input`/`avg_out`/`avg_cost_usd`/`avg_num_turns` averaged over the
non-failed provider attempts of the fully-measured tickets only; every
figure is `null`, never `0`, when no ticket qualifies. `estimator_calibration`
per track states the estimator's accuracy against real usage, derived from
the corpus rather than claimed: `estimated in / provider total input (in +
cache_hit + cache_write) = <ratio> over <n> provider-paired phases`, using
each phase's last non-failed provider attempt, and "uncalibrated" when no
provider-sourced attempt exists — which was this project's real state before
KLC-133 (no tokenizer library is installed and 0 of 109 pre-KLC-119
`meta.json` files carried any `provider` record).

**The real review-pass count (KLC-120).** `review_passes_per_ticket` counts
review-phase *artefact files* — one row (`review-report.md`) whatever the
number of reviewer sub-agents that actually ran. Alongside it, per track,
the rollup reports `review_llm_passes_per_ticket`: the mean number of
non-failed `reviewer`-tagged attempts of phase `review` specifically (KLC-133:
a failed reviewer dispatch, or a build-phase `run_pass`-tagged attempt —
which is never `reviewer`-tagged in the first place — never contributes)
over the tickets of that track that carry at least one, plus
`review_llm_passes_measured_tickets` (the denominator). `None`, never `0`,
when no ticket of the track has a tagged attempt — "not measured" must not
read as "costs nothing". This is the real per-ticket count of executed LLM
review passes the review plan (above) enumerates and the cap bounds.

---

## Prompt cards

Every `:work` phase gets a rendered **prompt card** — the per-ticket file that
carries the concrete key, the resolved input paths and the ack instruction
(`core/skills/artefacts.py:write_prompt_card` / `write_step_card`). Two things
about it changed in KLC-118.

**Location.** Cards live at `<card root>/<KEY>/<phase>/_prompt.md` (build
steps: `_prompt_step_N.md`), OUTSIDE the ticket directory. The card root
defaults to `.klc/scratch/` and is overridable with `KLC_CARD_ROOT`. A card
root that cannot be created or written degrades to the ticket directory with
a warning rather than failing the phase transition. Every reader (`klc
status`, `klc work --json`, `klc step`, `klc jump`, the headless runner, the
VS Code extension) resolves the same path through
`core/skills/artefacts.py:card_path()`.

**Render mode.** `write_prompt_card(..., mode=...)` renders one of two
shapes:

- `paste` (the default, and `klc next` / `klc step` / `klc jump`'s human
  output): the role prompt is fully inlined, exactly as before KLC-118. Used
  by the headless providers (`claude --print`, the OpenAI HTTP API,
  `ollama`), which receive one flat prompt string and cannot follow a
  filesystem reference, and by a human pasting the card into a chat.
- `dispatch` (`/klc:run`'s Task-tool dispatch only): the role prompt is
  OMITTED — the generated subagent definition
  (`klc-plugin/agents/<phase>.md`) already carries it — and the `## Role
  prompt` section instead names the role-prompt file by absolute path.

`KLC_CARD_INLINE=1` forces `paste` for either card (`write_step_card`'s
existing flag, generalised to phase cards); an unrecognised mode also
degrades to `paste` — the safe failure direction, since a bigger prompt costs
tokens but a silently dropped role prompt costs correctness.

**Measured baseline (the seven-phase M-track set: acceptance-test-plan,
design, discovery, integrate, learn, manual, review).** The `paste` total is
74 346 bytes; the `dispatch` total falls to roughly 5 813 bytes of
ticket-specific residue plus a small per-phase pointer block — a 92.2 %
reduction, worth about 17 100 estimated tokens per M ticket's phase
dispatches. `tests/integration/test_klc118_card_size_regression.py` gates
`dispatch_total < 0.10 * paste_total` against the real `core/agents/*.md`
files so this saving cannot silently regress.

(The design/spec-time estimate for this ticket, taken when KLC-118 was
scoped, cited 81 967 / 4 198 bytes — measured before KLC-113's prompt-hygiene
pass, stacked underneath this ticket, shrank several role prompts. The
figures above are what the renderer actually produces against today's
`core/agents/*.md`; the saving itself — a dispatch card under 10 % of a paste
card — holds either way.)

Every render also measures itself: `card_bytes` and an estimated token count
go into `meta.json:metrics.tokens.<phase>` via `budget_guard.write_token_metrics`
(never downgrading a `provider`-sourced record), and `klc next` prints both
numbers alongside the card path.

Prompt cards are DERIVED — rendered fresh on every dispatch, never read back
by any gate, and excluded from both the pre-merge consistency snapshot and
the retrospective agent's artefact set. A stale card left by a pre-KLC-118
layout is removed by `artefacts.sweep_legacy_cards()` (automatic, scoped to
the ticket and phase being rendered) or the explicit
`python3 core/skills/artefacts.py sweep-cards [KEY]` one-shot sweep.

---

## Jira integration

Two layers are available: **legacy push** (`jira-sync` command, `mode: mirror`) —
one-way klc → Jira, pushed on every `ack`, filesystem/git remain source of truth;
and **`klc jira` commands** (KLC-020+) — read-only status, GitLab artefact links,
intake dup-check, plus explicit sync/reconcile.

```bash
klc jira status <KEY>                           # read-only: klc phase vs Jira status
klc jira sync <KEY> --dry-run|--apply           # upsert GitLab artefact links in Jira
klc jira reconcile <KEY> push                   # push klc phase to Jira explicitly
klc jira reconcile <KEY> pull --to <phase>      # move klc to match Jira
klc jira reconcile <KEY> force-pull --to <phase> --reason "..."
```

**Managed mode** (`mode: managed`): klc does not auto-push on `ack`; at `ack`/`next`
it prompts inline when Jira diverged (recommended push / leave / record divergence),
and on an external conflict offers a 3-way choice. Non-TTY records the divergence in
`meta.json:jira_sync.conflicts` and warns — it never pushes silently. `klc doctor`
surfaces unresolved conflicts. `push()` finds a single direct transition or records
`transition-blocked`; a `pull`/`force-pull` moves klc to match Jira (forward walks
phase-by-phase, auto-skipping `condition=False`; backward supersedes downstream and
needs confirmation). `jira-pull` events suppress the klc→Jira push hook so a pull
never triggers a circular push. Setup lives in `.klc/config/jira.yml`
(`status_mapping.klc_to_jira` / `jira_to_klc`, `gitlab.blob_url`, transport
`rest`/`mcp`). The `cancelled` status is a terminal sentinel for `klc abort --cancel`.

The legacy push queues failed sends to `.klc/jira-queue.jsonl` (no command is
blocked) and drains opportunistically on any `klc` command, the pre-commit hook, or
`klc jira-sync`. Deduplication sends only the latest phase per ticket.

---

## Roles

Four roles collaborate through the lifecycle. For phase detail, see the per-phase
sections above.

**Product Manager (PM)** — human stakeholder defining requirements. Writes the
initial `raw.md`; reviews and approves discovery output (`spec.md`); makes ack-gate
decisions (approve / rework / cancel); validates ACs before archival.

**Agent (LLM)** — executes phase-specific work per its role prompt: writes spec,
test-plan, design options + ADR, code (TDD loop in build), review reports, and the
retrospective; emits completion signals. Constraints: cannot modify sealed artefacts
(spec after discovery ack, design after design ack); must stay within
`affected_modules`; must obey budget limits. Intake routing itself is deterministic
(no LLM); the optional intake-triage agent only produces a provisional track +
enrichment hints.

**Reviewer (human or agent)** — audits the implementation against `spec.md` and the
ADR in the review phase: correctness, completeness, quality, security (OWASP top
10); validates AC coverage; flags scope creep; produces `review-report.md` with a
verdict. The external reviewer (default-on for S/M/L via `config/reviewers.yml`)
runs on both cascade paths.

**Framework operator (human)** — runs the `klc` CLI to advance the ticket, resolves
merge conflicts at integrate, monitors observe metrics, and manages the two remotes:
`origin` (GitLab, real history) and `gh` (GitHub, clean public mirror) — see
[Dual-remote workflow](#dual-remote-workflow).

| Role | Human/Agent | Key phases | Main outputs |
|------|-------------|------------|--------------|
| PM | Human | intake, discovery-ack, final validation | raw.md, ack decisions |
| Agent | LLM | all :work sub-phases | spec.md, test-plan.md, code, review-report.md, retrospective.md |
| Reviewer | Human or Agent | review | review-report.md |
| Framework operator | Human | all phases (runs commands) | git commits, phase transitions |

---

## Glossary

**Ticket (KEY)** — a unit of work tracked through the lifecycle (e.g. `KLC-006`),
stored in `.klc/tickets/<KEY>/`. **Phase** — a discrete lifecycle stage with `:work`
and optionally `:ack-needed` / `:ack` sub-phases. **Track (XS/S/M/L)** — size class
from the four-axis estimate that decides which phases run. **Acceptance Criteria
(AC)** — testable conditions listed in `spec.md` as AC-1, AC-2, …. **Artefact** — a
file a phase produces (spec.md, test-plan.md, impl-plan.md, review-report.md, …).
**Ack** — a human gate (`klc ack <KEY> --pick N`) to approve / rework / cancel.

**Rework** — returning to `:work` after a needs-rework ack (or a backward `klc jump`
/ `klc abort`). `meta.json:rework_count` is a `{phase: count}` map, initialised to
`{}` at intake; the engine increments it on every backward/rework transition
(KLC-081). A ticket with no backward moves keeps `rework_count == {}`.

**Authority** — who owns an artefact: `human` (never regenerated —
`spec.md` after ack, `retrospective.md` after learn), `generated` (overwritten every
run — index files, `design.md`), or `hybrid` (agent regenerates
the body, but `<!-- BEGIN: manual --> … <!-- END: manual -->` blocks are preserved
verbatim). **Layer** — architectural layer affected (`meta.json:layer`).
**Budget** — iteration-count limits preventing infinite loops. **Phase history** —
the `meta.json` array of transitions used for metrics and audit.

**TDD loop** — test agent writes a failing test → impl agent writes code → verifier
runs tests → repeat until green. **Step** — one unit of build work (step-1, step-2).
**Characterisation test** — pins existing behaviour before a refactor. **Scope
creep** — implementation touching files outside `affected_modules` without
justification. **Coverage gap** — a missing test for an AC or step. **Finding /
Verdict** — a reviewer's issue and its outcome (approve / needs-rework / escalate).

**Remote (gh / origin)** — GitLab `origin` is the real history and the dev/review/
merge remote (via MRs); GitHub `gh` is a clean public mirror refreshed by a
re-authored, scrubbed force-push, so the two mains are intentionally divergent
lineages, not fast-forward mirrors.

Acronyms: **AC** Acceptance Criteria · **ADR** Architecture Decision Record ·
**LSP** Language Server Protocol · **PM** Product Manager · **TDD** Test-Driven
Development · **QA** Quality Assurance · **E2E** End-to-End.

---

## Artifacts

Every ticket lives at `.klc/tickets/<KEY>/` for its whole life. After learn,
`meta.phase` becomes `archived` and the directory stays where it is. Filenames
are stable — skills and agents look for them by name.

```
.klc/tickets/<KEY>/
  meta.json                  # source of truth for phase, track, metrics, manual/integrate outcomes
  raw.md                     # user's original description (immutable)
  spec.md                    # discovery output, incl. ## Approaches (authority: human after ack)
  test-plan.md               # test-planner output
  design.md                  # M/L: ## Options (+ Picked) and ## Consequences
  impl-plan.md               # step list; bumped during build
  build/steps.json           # recorded VERIFY result (+ review marker) per step
  findings.json              # every reviewer's findings, one file (KLC-173)
  advisories.json            # surface-only advisories keyed by phase (KLC-173)
  review/review-plan-r<N>.json  # review plan of round N (KLC-175)
  review-report.md           # findings + verdict
  retrospective.md           # final, human-authority after learn, at most 40 lines
  .index.json                # inline-item graph, regenerated by items.py
```

Derived files (retrieval trace, per-step briefs and reports) live in
`.klc/scratch/<KEY>/` and are not tracked. A superseded phase is deleted in place
and the commit it was deleted from is recorded in `meta.json` under `superseded`.
The budget is ten tracked files per ticket, not counting `findings.json`,
`advisories.json` and `review/`; `tests/integration/test_klc176_layout_budget.py`
holds it. Archived tickets keep their old layout and every reader still accepts it. New tickets
carry `meta.layout: 2`; only a ticket without that marker may still be judged on
the legacy approaches and design option files. `build-log.md` (optional implementer notes)
is outside the budget; `design/scout.md` counts toward it.

**`meta.json`** is the machine-readable single source of truth: `ticket`, `kind`,
`phase`, `phase_history[]`, `track`, `estimate {complexity, uncertainty, risk,
manual, total}`, `layer`, `affected_modules[]`, `related_tickets[]`,
`manual {verdict, note, at}`, `integrate {branch_head, main_head, at}`, `alerts[]`, `rework_count {phase: n}`, `metrics{}`.

**`spec.md`** — rendered full or short (XS); the `Affected` section requires every
entry to be LSP-verified (`src=path:line`) or an explicit
`[!ASSUMPTION if-false=scope-may-expand]`. Full form caps ~80 lines (hard cap 120);
short form max 15 lines. The **`## Approaches`** section (S, M and L; XS exempt)
carries ≥2 labelled options and a `Picked:` line the discovery gates block on. **`test-plan.md`** — S written by discovery-lite in the same call; M/L written by
`test-planner` in two passes (acceptance mode fills `## Acceptance coverage`, detailed
mode replaces the `TBD` with `## Detailed coverage`); authority `hybrid`.
**`design.md`** (M/L) — `## Options` with 2–4 labelled approaches and a `Picked:`
line, then `## Consequences`. **`impl-plan.md`** — authored by the design agent (S: by
discovery-lite); the enforced contract is `core/skills/impl_plan_check.py`.

**Executable step contract** — every `## step-N` includes: `Goal` (✓), `RED` (or
`RED: not applicable — <reason>`), `GREEN`, `VERIFY` (✓), `Expected` (✓), `COMMIT`
(✓, prefixed `<key> step-N:`), `Affected` (✓), `Interfaces` (✓), `Depends on`, and a
non-empty `Code sketch` (✓). **✓** = mechanically checked by `impl_plan_violations()`
(the plan-completeness gate at discovery-lite/design ack); the rest are prompt +
review discipline. `RED: not applicable` is the only sanctioned way to omit a code
sketch (prompt/doc/config-only steps) and relies on author discipline.

**`build-log.md`** — optional free notes (nothing gates on it). Authority `generated`; persists through review rework. **Authority model:**
`human` never regenerated; `generated` overwritten every run; `hybrid` regenerates the
body but preserves `<!-- BEGIN: manual -->` blocks.

Short-form eligibility:

| Track | spec | impl-plan | test-plan |
|-------|------|-----------|-----------|
| XS | short | short | short |
| S  | full  | short | full |
| M  | full  | full  | full |
| L  | full  | full  | full |

---

## Metrics

Per-ticket metrics live in `.klc/tickets/<key>/meta.json:metrics`; rollups in
`.klc/knowledge/process-metrics.json`. Skills: `core/skills/metrics.py set|show|rollup`;
front-ends `klc metrics <key>` and `klc metrics --rollup`. Every phase writes a small,
well-defined set; the learn phase reads them all and computes derived values.

| Phase | Metric | Notes |
|-------|--------|-------|
| intake | `intake_ms`, `intake_agent_ms` | timer; triage agent (when it runs) |
| discovery | `discovery_ms`, `discovery_tokens`, `estimate_axes`, `track` | |
| acceptance-test-plan | `test_plan_ms`, `ac_count` | |
| design | `design_ms`, `options_count`, `adr_triggered` | |
| build | `build_ms`, `iterations`, `red_fixes`, `mutation_score`, `build_head_sha` | |
| review | `review_ms`, `blocking`, `non_blocking`, `sub_agents_ran`, `review_depth`, `full_review_offered`, `full_review_declined` | last three from report frontmatter |
| manual | `manual_minutes`, `manual_outcome` | |
| integrate | `merge_wait_ms`, `branch_head`, `main_head`, `pre_post_snapshot_match` | |
| observe | `observe_hours`, `alerts_seen` | |
| learn | `cycle_time`, `estimate_accuracy`, `rework_count`, `token_spend`, `cost_breakdown` | computed at learn |

`cost_breakdown` aggregates `tokens` (total + by-agent), `lsp.calls`, `api`
(provider call counts, no pricing math), `ci` (runs/minutes when CI posts to
`ci-runs.jsonl`), and `rework` (from `meta.rework_count`). The ack path counts only
genuine rework picks (`needs-rework`, `request-changes`, `regression`, `failed`,
`revise-impl-plan`) — not the `learn` extract-to-CLAUDE.md self-loop; cross-track
escalations and the `observe rollback → learn` pick are treated as route changes,
not rework.

**Rollup** (`.klc/knowledge/process-metrics.json`) is recomputed at learn (or forced
with `klc metrics --rollup`): `per_track` medians/p95 of cycle time, `rework_mean`,
and **`cheap_escape_rate`** — the fraction of cheap/lite-reviewed tickets that later
had rework or regression (`null` when the track has no cheap/lite reviews). A rising
`cheap_escape_rate` signals the cascade is routing too aggressively to cheap review —
tighten tier classification or add sentinel patterns. The retrospective agent reads
the rollup to flag outliers.

---

## Epics

An epic is simply a **group of ordinary tickets** that make up one feature, plus the
dependency edges between them. It is deliberately *not* a second lifecycle: there is
no epic state machine, no `EPIC-` key namespace, no `.klc/epics/` directory, and no
central `graph.json`. Everything an epic "is" comes from three pieces of data on the
member tickets, and every epic-level answer (state, graph, ready set) is **computed**
by scanning members — so an epic adds no new coordination surface. For the design and
rationale see the spec
[`docs/20260724_epic_feature_impl_plan.md`](20260724_epic_feature_impl_plan.md).

```text
1. description  → epic.md in the ROOT ticket's dir: .klc/tickets/<ROOT>/epic.md
2. membership   → meta.epic = "<ROOT>" on every member (the root points at itself)
3. dependencies → meta.blocked_by edges on each downstream ticket
```

**Membership — `meta.epic`.** Every member carries `meta.epic` set to the root
ticket's key (the root's own points at itself; the root key *is* the epic id).
Plain tickets have no `meta.epic` key at all, so they are byte-for-byte unaffected.

**Epic state — computed, never stored** (matching `epic_view.epic_state`, "done"
first): all members archived/cancelled → **done**; all in `intake:*` → **planned**;
otherwise → **in-progress**. `board --epic` recomputes it on every read.

**Dependencies — `meta.blocked_by`.** Recorded as per-ticket edges on the
**downstream** ticket; the whole graph is the union of every member's `blocked_by`.
Each edge: `{"on": "<K>", "phase": "<downstream phase gated>", "point": "<milestone>",
"condition": "passed"?}`.

The three dependency points resolve to an upstream phase-state (at or past):

| point             | meaning                | upstream phase-state                              |
|-------------------|------------------------|---------------------------------------------------|
| `design-accepted` | design / spec chosen   | `design:ack` (M/L) **or** `discovery-lite:ack` (XS/S) |
| `integrated`      | code merged and working| `integrate:ack`                                   |
| `archived`        | ticket fully done      | `archived`                                        |

**The `passed` condition** holds when the point was reached AND the upstream's
`phase_history` shows no rollback / abort / regression / jump and no
`cancelled` / `regression_observed`. A failed condition does not unblock — the epic
view flags a human pause (it never auto-cancels or auto-replans); any unknown
condition is treated as not-holding (fail-safe).

**Enforcement** — a dependency is a **block on entering the gated phase's `:work`
state**, checked inside the verb's transaction right after the state pull (so a
peer's just-merged progress is seen). It is orthogonal to phase gates: phase gates
(the `pick_required` picks) control the `:ack-needed → :ack` *exit*; dependency edges
control the `:work` *entry*. Degrade-not-fail: an empty/absent `blocked_by` is a pure
no-op; a dangling edge (missing `on`) refuses with a message to fix the edge.

**The view — `klc board --epic <ROOT>`** — read-only, epic-scoped: the computed epic
state; each member's phase, unmet `blocked_by` edges, and holder; the **ready set**
(members whose immediate next `:work` has no unmet dependency and are not held);
**blocked** and **upcoming** members; and validation warnings computed at view time —
dependency **cycles**, **dangling** edges, and **dead** edges (the gated phase is not
in that ticket's track). `--json` for a machine-readable report.

**The entry — "discuss a new feature".** The intended way to create an epic is the
`discuss-feature` skill (`/klc:discuss-feature`): one conversation that agrees scope
into `epic.md`, decomposes into tickets each with a rationale and dependency edges,
validates the whole planned set BEFORE creating anything (via
`core/skills/epic_plan.py` — cycles / dangling / every ticket described / every edge's
phase real), then runs intake per ticket and shows `board --epic <ROOT>`. By hand it
shells out to `klc intake`:

```text
klc intake <KEY> --epic <ROOT> \
  [--blocked-by "<K>@<point>[:cond]#<phase>" ...] \
  "<description>"
```

`--epic <ROOT>` tags membership (the root points at itself); `--blocked-by` is
repeatable and records one edge (grammar owned by `epic_deps.parse_edge`, so CLI and
skill validation never drift); the trailing `"<description>"` is mandatory. Read
`KLC-077@integrated:passed#build` as "this ticket's `build` cannot start until
KLC-077 reaches `integrated`, and only if that point was reached with no rollback /
regression".

---

## Dual-remote workflow

The repo has **two** remotes that play **different** roles — they are *not* two peers
holding an identical `main`:

- `origin` → GitLab — the **real history** and the active development remote. All
  branches, MRs, review, and CI live here.
- `gh` → GitHub — a **clean public mirror**. Since the 2026-07-21 history scrub it is
  a re-authored, content-scrubbed lineage: every commit re-authored to the public
  identity, every internal reference removed. It is refreshed by force-push and takes
  **no pull requests**.

Because gh is re-authored and scrubbed, the two `main` branches hold the **same
content under different identity and history** — **intentionally divergent**, not
fast-forwards. Do not try to reconcile them. (An earlier `--ff-only` mirror model is
dead: identical mains would contradict the scrub. See the constitution principles
`divergent-public-mirror` and `public-mirror-no-internal-refs`.)

```text
1. Branch off the latest origin/main:
     git checkout main && git pull origin && git checkout -b feature/klc-0NN-<slug>
2. Develop on the branch (TDD, commits) — never on main directly (branch-first).
3. Push the branch to origin and open a Merge Request there.
4. Review + CI happen on the origin MR. Merge the MR on origin.
5. Refresh the public mirror gh from origin/main via the scrub + re-author step
     (a filtered, re-authored force-push). NOT a merge, NOT a PR.
6. Delete the feature branch on origin when done.
```

The scrub must re-author every commit to the public identity and scrub internal
references from content. The denylist of internal tokens lives in the origin-side
mirror tooling — deliberately NOT in the constitution, because a denylist committed
onto the surface it guards would both ship those tokens to the public mirror and
self-trip a gh-side grep against its own denylist. Verify after publishing that a
grep of the denylist against `gh/main` content and author/committer emails finds
nothing; a hit means the scrub leaked and must be re-pushed.

**Bookkeeping vs code.** Pure `.klc/` lifecycle bookkeeping (phase acks,
retrospectives) with no reviewable diff may be committed on `origin/main` directly;
everything with a code diff goes through a branch and an MR (`branch-first`).

---

## Repository layout

```
klc/                           # framework repo
  config/
    phases.yml                 # state machine (source of truth)
    models.yml                 # model → role-slot mapping
    reviewers.yml              # review gates, cascade, external reviewer
    budgets.yml                # prompt-size limits + autorun cap
    constitution.yml           # machine-checkable review principles
    coverage-taxonomy.yml      # requirement-coverage checklist
  core/
    agents/                    # LLM prompt files
    phases/                    # command implementations (*.py)
    skills/                    # supporting tools
    templates/                 # Jinja2 templates
  hooks/pre-commit             # consistency + plugin-sync + update.py + jira drain
  scripts/klc                  # dispatcher
  docs/                        # this directory (process / architecture + kept docs)
  tests/

<project>/
  .klc/
    config/                    # per-project overrides
    index/                     # structural.json, depgraph.json, stale.json, …
    tickets/<KEY>/             # spec.md, impl-plan.md, meta.json, … (archived too)
    knowledge/                 # reviewer-allowlist, process-metrics, few-shot
    logs/
  CLAUDE.md                    # root, generated by docgen
  <module>/CLAUDE.md           # per-module, generated
```
