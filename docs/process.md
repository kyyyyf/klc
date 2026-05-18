# Process overview

> **Note.** As of 2026-05 the lifecycle is driven by six verbs
> (`intake` / `status` / `next` / `ack` / `jump` / `abort`) and the
> state machine lives in [`config/phases.yml`](../config/phases.yml).
> Older docs in this directory may still reference phase-specific
> commands (`klc discover`, `klc design`, ...) — those are gone; run
> `klc next` / `klc ack` instead. The **concepts** (phases, tracks,
> gates, artefacts) are unchanged.

High-level, kanban-oriented description. The items below are **columns**
on the board, not steps in a workflow — tickets dwell in each column
for as long as the work inside takes, and enter the next one when its
entry trigger fires. See `process-phases.md` for the formal state
machine, `process-roles.md` for a role-by-role table, and
`process-artifacts.md` for artefact schemas.

## Principles

1. **Kanban, not waterfall.** Work flows through columns by pull; WIP
   limits per column keep flow efficiency high. Nothing batched.
2. **Agents author, humans review.** LLMs draft every artefact; the
   human is the owner of intents and constraints and acknowledges
   them at three mandatory gates.
3. **Short cycle, much documentation.** Closer to RUP than to "agile
   minimalism" in the amount of written artefacts — but the cycle is
   days not months, and the writing is LLM-generated.
4. **Everything is saved.** Specs, options (including rejected ones),
   ADRs, impl plans, review reports, metrics, scratchpads. Archived
   per ticket; browsable by anyone on the team.
5. **Every decision is traceable.** Inline items
   (`[!FACT]` / `[!ASSUMPTION]` / `[!DECISION]` / ...) with IDs,
   supersession chains, and a per-ticket `.index.json` graph. See
   `process-artifacts.md` and `core/skills/items.py`.
6. **Multi-dimensional estimate.** 4 axes — complexity, uncertainty,
   risk, manual — each 0–3. Total maps to a **track**
   (XS / S / M / L). Different tracks skip different columns.
7. **No bottleneck on the human.** Humans confirm at 3 obligatory
   gates + 1 conditional (manual check). Everything else is signal-
   driven: agents escalate when budgets or thresholds break.
8. **Human owns intent and constraints.** LLM cannot change spec
   after discovery ack, cannot unlock design direction, cannot
   merge, cannot mark manual check as passing.
9. **Short tracks for small work.** XS skips test-planning and
   design. S skips design unless promoted. Downgrades are forbidden;
   upgrades are always allowed.
10. **Facts vs assumptions vs decisions** are **marked in every
    artefact**. LLM must tag any claim about the code (FACT with
    `src=`), any guess (ASSUMPTION with `if-false=`), any chosen
    option (DECISION). Cuts hallucination; makes retrospective
    verifiable.
11. **Artefacts stay in sync.** Consistency gate runs before review
    and before integrate. Manual blocks preserved verbatim across
    regenerations; authority model per file prevents silent drift.

## Jira configuration options

You may model tickets in Jira one of two ways. The framework is
indifferent — both work with the same `.klc/tickets/` machinery.

### Option A — parent task + subtasks

The parent task represents the **feature / bug** and stays in
`In Progress`. Each kanban column is a **subtask** with statuses
`To Do → In Progress → Done`. Subtasks complete sequentially. This
keeps the parent-task board clean (one card per ticket) while still
surfacing phase-level progress inside.

- Pros: Jira-native. Works with any Agile board out of the box. No
  workflow edit needed.
- Cons: Hard to filter "tickets currently in Review" across parents.

### Option B — extended workflow with per-column statuses

One Jira ticket = one card. The workflow has custom statuses matching
the columns below (Intake, Discovery, Test planning, …, Learn) with
transitions between them. `klc ack` and `klc back` drive the
transitions via a Jira integration (not shipped — wire via webhook).

- Pros: one card per item; the Jira board itself is the kanban
  board.
- Cons: requires workflow admin rights; transitions must match
  `lifecycle.py:TRANSITIONS`.

We recommend **A** for teams starting out and **B** once the process
stabilises and reporting needs grow.

---

## Columns

### Status 1 — Inbox

**Transitions in**: — (new ticket).

**Goal.** Capture the raw request; classify the kind (feature / bug /
tech) and surface obviously-missing info. Nothing reasoned here.

**Description.** A stakeholder creates a ticket by pasting whatever
they wrote into the issue form or the chat. The framework stores the
raw text verbatim; an LLM triage pass annotates what's missing.

**Triggers & inputs**:
- someone runs `klc intake <KEY> --kind <k> "<desc>"`;
- OR a Jira issue lands in the inbox and an automation calls intake.

Inputs: the raw description string; optional `--kind` hint.

**Scripts & agents**:
- `scripts/klc` → `core/phases/intake.py` — creates the directory,
  initialises `meta.json` with `phase=intake`, appends to the global
  tickets index.
- `core/agents/intake.md` — classifies kind, annotates missing
  fields, extracts mentioned modules / symbols.

**Steps by role**:
- **Human**: writes the initial description.
- **Intake agent**: classifies kind; greps for module / symbol
  mentions; appends `intake-agent-notes` to `raw.md`.
- **intake.py**: creates `raw.md`, `meta.json`, appends to
  `.klc/knowledge/tickets-index.jsonl`.

Track differences: none. Every track passes through Inbox.

**Output artefacts**:
- `.klc/tickets/<KEY>/raw.md` (immutable).
- `.klc/tickets/<KEY>/meta.json` with `phase=intake`, empty track /
  estimate / affected_modules.
- one append to the global tickets index.

---

### Status 2 — Discovery

**Transitions in**: `Inbox`.

**Goal.** Turn `raw.md` into `spec.md` with goals, acceptance
criteria, constraints, affected modules. Classify on four axes, pick
the track. Surface every unknown as a `QUESTION`, never invent.

**Description.** The biggest LLM step outside of Build. Agent reads
the raw description, root `CLAUDE.md`, candidate module docs, related
prior tickets, optional external docs; writes `spec.md` with inline
FACT / ASSUMPTION / QUESTION items; updates `meta.json` with track,
estimate, layer, affected_modules, related_tickets. Ends at a
**pull-ready gate** — human ack required before anything else can
run.

**Triggers & inputs**:
- `klc discover <KEY>` pulls from Inbox.
- Inputs: `raw.md`, `.klc/index/modules.json`,
  `.klc/index/symbols_by_module.json`, `CLAUDE.md` of candidate
  modules, last ~30 entries of the global tickets index with matching
  kind / modules.

**Scripts & agents**:
- `core/phases/discover.py` — prepares a context bundle at
  `.klc/tickets/<KEY>/discovery-context/`, bumps phase to
  `discovery-running`; `--continue` validates outputs and bumps to
  `discovery-pending-ack`.
- `core/agents/discovery.md` — writes `spec.md`, fills meta.json.
- `core/skills/lifecycle.py` — gatekeeps the transitions.

**Steps by role**:
- **discover.py**: builds the context bundle (raw + root CLAUDE.md +
  module candidates + related tickets + docs).
- **Discovery agent**: writes `spec.md`, sets track + estimate +
  layer + affected_modules in `meta.json`.
- **discover.py --continue**: validates that meta is populated and
  bumps phase to `discovery-pending-ack`.
- **Human**: reads `spec.md`, answers any `[!QUESTION]` inline in
  raw.md if needed, then `klc ack <KEY> --for discovery`.
  May upgrade the track with `--upgrade-track`.

Track differences:
- **XS**: after ack the ticket jumps straight to Build.
- **S / M / L**: after ack the ticket moves to Test planning.
- **Upgrade**: `--upgrade-track L` allowed anytime; downgrade
  forbidden.

**Output artefacts**:
- `spec.md` (authority: human after ack).
- `meta.json` populated with track / estimate / layer /
  affected_modules / related_tickets.
- `.index.json` regenerated (inline items collected).

---

### Status 3 — Acceptance test plan

**Transitions in**: `Discovery` (S / M / L; XS skips entirely).

**Goal.** Map every AC from `spec.md` to a concrete acceptance /
end-to-end test. These tests are behaviour-level and do not depend
on the chosen implementation. Detailed unit / integration tests come
later, after Design (Status 5).

**Description.** Acceptance tests are the contract between
stakeholders and the change — their shape is fully determined by
spec.md. Planning them *before* Design keeps TDD honest: the design
agent sees the tests and picks options that make them easy to satisfy
rather than easy to write. The agent writes only a coverage mapping
and the manual-check block; real test code lands during Build.

**Triggers & inputs**:
- `klc test-plan <KEY>` after discovery ack.
- Inputs: `spec.md`, `.klc/index/test-framework.json` (if present).

**Scripts & agents**:
- `core/phases/test_plan.py` — XS is not routed here; S emits the
  short form and skips straight to Build; M / L emit acceptance-only
  and continue to Design.
- `core/agents/test-planner.md` — writes `test-plan.md` with only
  the acceptance coverage table and the manual checklist block.

**Steps by role**:
- **test_plan.py**: checks lifecycle; hands off to the planner.
- **Test planner agent**: emits `test-plan.md` with
  `## Acceptance coverage` table (one row per AC → e2e/acceptance
  test) and `## Manual checklist` when `estimate.manual ≥ 2`.
  `## Detailed coverage` is left as a placeholder — filled in
  Status 5.
- **test_plan.py --continue**: validates the acceptance table
  covers every AC; bumps phase to `design-pending` (M / L) or
  `build-pending` (S).

Track differences:
- **XS**: skipped; goes Discovery → Build.
- **S**: short form, acceptance-only table, then straight to Build.
  Unit / integration tests are written inline during Build's TDD
  loop without a separate detailed plan.
- **M / L**: acceptance table + manual checklist; detailed coverage
  added in Status 5.

**Output artefacts**:
- `test-plan.md` with acceptance section populated; detailed
  section empty (M / L) or absent (S).
- phase advanced to `design-pending` (M / L) or `build-pending` (S).

---

### Status 4 — Design

**Transitions in**: `Acceptance test plan` (M / L by default;
S / XS only after a track upgrade).

**Goal.** Generate three implementation options, let the human pick,
then write an ADR (when triggered) and the `impl-plan.md`.

**Description.** The agent explores Options A / B / C with concrete
trade-offs. One is marked `recommended`. After the human picks, the
agent either continues directly to the impl plan (ADR not triggered)
or writes the ADR first. Direction ack is required before Build.

**Triggers & inputs**:
- `klc design <KEY>` after test-planning done.
- Inputs: `spec.md`, `test-plan.md`, any related ADRs touching the
  affected modules.

**Scripts & agents**:
- `core/phases/design.py` — prepares design-context, hands off;
  `--continue` validates and bumps phase.
- `core/agents/design.md` — umbrella prompt invoking:
  - `core/agents/adr.md` when `ADR_NEEDED=yes`;
  - implicit plan authoring.
- Serena (`core/skills/serena-call.py`) — M / L only; every symbol
  referenced in options / ADR must carry `cached at <path>` or
  `verified-via-serena at <date>`.

**Steps by role**:
- **design.py**: bundles spec + test-plan + related ADRs.
- **Design agent**: writes `design/options.md` (three options +
  recommended flag + `ADR_NEEDED=yes|no`).
- **Human**: reads options; picks one (says which in chat or
  marks in options.md).
- **ADR agent** (conditional): writes `design/adr.md`.
- **Plan agent**: writes `impl-plan.md`.
- **design.py --continue**: validates outputs, bumps phase to
  `design-pending-ack`.
- **Human**: `klc ack <KEY> --for design`.

Track differences:
- **XS / S**: skipped by default (jumps from Test planning to Build).
- **M**: full design; ADR is conditional.
- **L**: full design + ADR obligatory + the intermediate review
  mentioned in `process-phases.md` §5.2 is recommended.

**Output artefacts**:
- `design/options.md` (authority: generated; rejected options
  preserved for audit).
- `design/adr.md` (conditional; MADR format).
- `impl-plan.md` (authority: hybrid).
- `.index.json` regenerated.

---

### Status 5 — Detailed test plan

**Transitions in**: `Design` (M / L only; XS / S skip this column).

**Goal.** Extend `test-plan.md` with a unit / integration table
that references the chosen option, specific modules, and the
step IDs from `impl-plan.md`.

**Description.** Acceptance tests (Status 3) are spec-level; these
are implementation-level. They live in the same `test-plan.md` so
the whole testing story is in one file, but they can only be
written once the Design phase has produced concrete files, classes
and steps. Typical content: which step-N has which unit tests;
which interface contract demands a mock; which refactor needs
characterisation tests. Manual block preserved from Status 3.

**Triggers & inputs**:
- `klc test-plan <KEY> --detailed` after `klc ack ... --for design`.
- Inputs: `spec.md`, existing `test-plan.md` (acceptance section +
  manual block), `design/options.md`, `design/adr.md`,
  `impl-plan.md`, `.klc/index/symbols_by_module.json` scoped to
  affected modules.

**Scripts & agents**:
- `core/phases/test_plan.py --detailed` — second pass of the same
  phase script, keyed by a phase-bump into
  `detailed-test-plan-pending`.
- `core/agents/test-planner.md` — same prompt, detailed-mode branch.

**Steps by role**:
- **test_plan.py --detailed**: verifies that options / adr /
  impl-plan are in place; hands off to the planner.
- **Test planner agent**: appends `## Detailed coverage` to the
  existing `test-plan.md`, preserving the acceptance table and
  manual block verbatim. Each row cites a `step-N` and the target
  file / function.
- **test_plan.py --detailed --continue**: validates that every
  step from `impl-plan.md` either appears in the detailed table or
  has an explicit `covered-by: AC-N` note (e.g. steps that are
  wiring only and have no new behaviour). Bumps phase to
  `build-pending`.

Track differences:
- **XS / S**: skipped. S's acceptance table, written in Status 3,
  is enough; new tests appear inline during Build's TDD loop.
- **M**: mandatory.
- **L**: mandatory.

**Output artefacts**:
- `test-plan.md` extended with `## Detailed coverage` (same file,
  two sections now).
- `.index.json` regenerated.
- phase advanced to `build-pending`.

---

### Status 6 — Build

**Transitions in**: `Discovery` (XS), `Acceptance test plan` (S),
`Detailed test plan` (M / L).

**Goal.** Implement the plan test-first, with the red-then-green
discipline and mutation testing where the language supports it.

**Description.** The loop is: test agent writes a failing test →
impl agent makes it pass → verifier runs the suite → mutation tool
(if configured) reports score. Budget (`core/skills/budget.py`)
caps the number of red-fix and mutation-fix attempts per ticket.
Artefacts (`impl-plan.md` especially) are updated as the actual
implementation diverges from the plan.

**Triggers & inputs**:
- `klc build <KEY>`.
- Inputs: `spec.md`, `impl-plan.md`, `test-plan.md`;
  `symbols_by_module.json`; Serena access (all M / L and S in Build
  only).

**Scripts & agents**:
- `core/phases/build.py` — prepares build-context.
- `core/agents/test.md` — test writing (TDD).
- `core/agents/impl.md` — code changes.
- `core/agents/validator.md` — post-step self-check.
- `core/skills/test-writer.py`, `core/skills/budget.py`,
  mutation tools (per language).
- Serena via `serena-call.py` — allowed on M / L / S-in-build.

**Steps by role**:
- **Test agent**: emits failing tests keyed to every AC. For bug
  tickets, the first test is a regression that currently fails.
- **Verifier**: runs the suite; if red tests are not red, fails.
- **Impl agent**: makes tests green step-by-step per `impl-plan.md`;
  patches `impl-plan.md` with DECISION items when the plan diverges.
- **Budget**: counts red-fix / mutation-fix attempts; stops at
  limit with `BUDGET_EXCEEDED` in `meta.json:blocked_reason`.
- **build.py --continue**: records `build_head_sha`, bumps to
  `review-pending`.
- **Human**: touches nothing unless an escalation signal fires
  (budget, scope creep, conflict).

Track differences:
- **XS**: single-iteration; test + impl in the same pass; no
  mutation gate.
- **S**: full loop, mutation gate optional (per language config).
- **M / L**: full loop + mutation gate enforced where supported.

**Output artefacts**:
- Code + test changes committed to the ticket branch.
- `impl-plan.md` updated with any DECISION items and rollback notes.
- `meta.json.metrics`: build_ms, iterations, red_fixes,
  mutation_score.
- Optional scratch sessions under `scratch/` if trace got long.

---

### Status 7 — Review

**Transitions in**: `Build`.

**Goal.** Multi-agent code review + human merge approval. The only
gate where the human sees the full diff.

**Description.** Sub-agents (security, architecture, performance,
test-coverage, plus profile-specific ones) run in parallel against
the diff + spec + module context. Each emits a partial with
`ISSUES_TOTAL=N ISSUES_BLOCKING=M`. Aggregator builds the final
report with a verdict (`APPROVED` / `CHANGES REQUESTED`). The human
reads it, decides merge.

**Triggers & inputs**:
- `klc review <KEY>`.
- Inputs: the diff (HEAD by default), `spec.md`, module CLAUDE.md
  bundle, `.klc/knowledge/reviewer-allowlist.yml`.

**Scripts & agents**:
- `core/phases/review.py` → `scripts/review.py` → profile's
  reviewer agents.
- `core/agents/review.md` — orchestrator.
- `core/agents/review/{security,architecture,performance,test-coverage}.md`
  plus profile reviewers (UE: replication, ue-conventions,
  content-pipeline, ...).
- Serena allowed for verifying signatures cited in a finding.

**Steps by role**:
- **review.py**: fans out job cards to the sub-agents; collects
  partials; runs the aggregator.
- **Sub-agents**: emit findings; downgrade to INFO when matched by
  `reviewer-allowlist.yml`.
- **Aggregator**: writes `.klc/reports/review-<ts>.md`, prints
  `VERDICT`.
- **Human**: reads the report.
  - If `APPROVED`: `klc review <KEY> --continue`, then
    `klc ack <KEY> --for review`.
  - If `CHANGES REQUESTED`: address blockers, re-run. After the 3rd
    rework cycle: escalation.

Track differences:
- **XS**: security + test-coverage sub-agents only; auto-APPROVED
  if both clean.
- **S**: full review without the architecture sub-agent.
- **M / L**: full review including all profile-specific sub-agents.

**Output artefacts**:
- `.klc/reports/review-<ts>.md`.
- `.klc/reports/partials-<ts>/<reviewer>.partial.md` per sub-agent.
- `meta.json.metrics`: review_ms, blocking, non_blocking.
- Optional `scratch/review-overflow-*.md` when a reviewer produced
  more than 10 findings.

---

### Status 8 — Manual check

**Transitions in**: `Review` (when `estimate.manual ≥ 2`;
otherwise skipped).

**Goal.** Human walks through AC-N + edge cases from `spec.md` as a
checklist. Does not touch code.

**Description.** Agent generates the checklist verbatim from spec
(no paraphrasing — keeps traceability). Human ticks boxes. Outcome
recorded; fail → `klc back`.

**Triggers & inputs**:
- `klc manual <KEY>` after review ack.
- Inputs: `spec.md`, `test-plan.md` manual block.

**Scripts & agents**:
- `core/phases/manual.py`.
- `core/agents/manual-check.md`.

**Steps by role**:
- **Manual-check agent**: writes `manual-checklist.md` with AC
  wording verbatim.
- **Human**: walks through; runs
  `klc manual <KEY> --continue --outcome=<pass|fail>`.
- On `fail`: script suggests `klc back <KEY> --to build-pending
  --reason "..."`.
- On `pass`: phase bumps to `manual-pending-ack`;
  `klc ack <KEY> --for manual` completes.

Track differences:
- **All tracks with `estimate.manual ≥ 2`**: mandatory.
- **Otherwise**: skipped (ticket moves straight from Review to
  Integrate).

**Output artefacts**:
- `manual-checklist.md` with every box ticked (if passed) or an
  annotation (if failed).
- `meta.json.manual_outcome` = `pass|fail`.
- `meta.json.metrics.manual_minutes`.

---

### Status 9 — Integrate

**Transitions in**: `Review` (manual skipped) or `Manual` (passed).

**Goal.** Thin bookends around the human-performed `git merge`.
Framework never runs `git merge` itself.

**Description.** Two sub-commands, one column:
1. `klc integrate pre <KEY>` — runs the consistency gate, snapshots
   hashes of every artefact, prints go / no-go.
2. Human performs the merge (PR, squash, whatever the team uses).
3. `klc integrate post <KEY> --merge-sha <sha>` — verifies the
   snapshot still matches, records the SHA, archives scratch,
   advances to Observe (or Learn).

**Triggers & inputs**:
- `klc integrate pre <KEY>` after Review (+ Manual) ack.
- Inputs: the full ticket directory; `core/skills/items.py` and
  `consistency_check.py` output.

**Scripts & agents**:
- `core/phases/integrate.py`.
- `core/skills/consistency_check.py`,
  `core/skills/items.py validate`.
- `core/skills/scratch.py archive` called by post.

**Steps by role**:
- **integrate pre**: consistency check; if fails, integrate does
  not advance, human fixes (`klc back` or edit + `klc reindex`).
  On success, writes `meta.json:pre_merge_snapshot`, prints
  `INTEGRATE_PRE_OK`.
- **Human**: performs merge via team's flow.
- **integrate post**: verifies snapshot parity (fails on drift
  unless `--allow-drift`), records `merge_sha` and `merged_at`,
  archives `scratch/` into `archived-scratch-<ts>/`.

Track differences: none. Every track passes through Integrate.
Observe (next column) may be skipped.

**Output artefacts**:
- `meta.json` populated with `merge_sha`, `merged_at`,
  `pre_merge_snapshot`, `metrics.integrate_pre_ms`,
  `pre_post_snapshot_match`.
- `archived-scratch-<ts>/` in the ticket directory.

---

### Status 10 — Observe (optional)

**Transitions in**: `Integrate` when the project wires it; skipped
otherwise.

**Goal.** Placeholder for post-deploy observation (alerts, metrics
deltas). Ships as a no-op; wire to CI when deploy semantics exist.

**Description.** First invocation of `klc observe <KEY>` timestamps
`observation_started_at`. Every alert (webhook → `klc observe ...
--alert '<json>'`) appends to `meta.json.alerts`. `klc observe
<KEY> --now` ends the window and advances to Learn.

**Triggers & inputs**:
- `klc observe <KEY>` after `integrate post`.
- Alert payloads from CI (optional).

**Scripts & agents**:
- `core/phases/observe.py`.

**Steps by role**:
- **observe.py**: records timestamps and alert data.
- **CI / alerting system** (optional): posts alerts.
- **Human or cron**: runs `--now` after the chosen window.

Track differences: none; entirely optional per project.

**Output artefacts**:
- `meta.json.alerts[]`.
- `meta.json.metrics.observe_hours`, `alerts_seen`.

---

### Status 11 — Learn

**Transitions in**: `Integrate` (when Observe skipped) or
`Observe` (when wired).

**Goal.** Write the retrospective; collect final metrics; propose
allowlist / deny / few-shot updates; archive the ticket.

**Description.** Agent reads every artefact + metrics + Serena call
log, drafts `retrospective.md` with facts (not opinions), lessons in
imperative form, and up to 2 proposed entries for each knowledge
base. The human approves (or edits) the retro; `--continue` runs
the metrics rollup, optionally runs `serena_deny.py propose`, and
moves the ticket to `.klc/tickets/archive/<KEY>/`.

**Triggers & inputs**:
- `klc learn <KEY>`.
- Inputs: all artefacts + `meta.json` + `serena-calls.log`.

**Scripts & agents**:
- `core/phases/learn.py`.
- `core/agents/retrospective.md`.
- `core/skills/metrics.py rollup`.
- `core/skills/serena_deny.py propose` (optional).

**Steps by role**:
- **Retrospective agent**: writes `retrospective.md`.
- **Human**: reviews / edits the retro; approves proposed knowledge
  updates by running `serena_deny.py add` manually.
- **learn.py --continue**: rolls up
  `.klc/knowledge/process-metrics.json`, archives the ticket.

Track differences: none.

**Output artefacts**:
- `retrospective.md` (authority: human).
- Updated `.klc/knowledge/process-metrics.json`.
- Ticket directory moved to `.klc/tickets/archive/<KEY>/`.
- Proposed (not auto-applied) updates to
  `reviewer-allowlist.yml` / `serena-deny.yml` / reviewer few-shots.

---

### Status 12 — Done / Archived

**Transitions in**: `Learn` (after archive).

Terminal state. The ticket directory lives at
`.klc/tickets/archive/<KEY>/`; the global index shows
`phase=archived`. Cross-ticket queries (`klc board`, global
knowledge lookups in future Discovery) still see it.

---

## Gates at a glance

| Gate | Column out → in | Required condition |
|------|-----------------|--------------------|
| pull-ready ack | Discovery → next | human runs `klc ack ... --for discovery` |
| direction ack  | Design → Build   | human runs `klc ack ... --for design` |
| merge-approval ack | Review → next | human runs `klc ack ... --for review` |
| manual ack     | Manual → Integrate | only when `estimate.manual ≥ 2` |

Everything else — phase-bumps inside a column, artefact writes,
index regeneration — happens automatically on `--continue`
invocations.

## Rework

The only sanctioned way to move a ticket backwards is
`klc back <KEY> --to <phase> --reason "..."`. It writes an audit
entry to `meta.json.phase_history`, increments
`meta.json.rework_count[<phase>]`, and switches phase. After 3
rework jumps from the same column, the ticket auto-escalates to
`tech-lead` per `process-phases.md` §5.3.
