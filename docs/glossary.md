# Glossary

This document defines key terms used throughout the klc framework documentation.

## Core concepts

**Ticket (KEY)**  
A unit of work tracked through the framework lifecycle. Identified by a key like `KLC-006`. Stored in `.klc/tickets/<KEY>/`.

**Phase**  
A discrete stage in the ticket lifecycle (e.g., intake, discovery, build). Each phase has `:work` and optionally `:ack-needed` and `:ack` sub-phases.

**Track (XS / S / M / L)**  
Size classification determining which phases a ticket goes through. Based on complexity + uncertainty + risk + manual estimate total.

**Acceptance Criteria (AC)**  
Testable conditions that must be met for a ticket to be considered complete. Listed in `spec.md` as AC-1, AC-2, etc.

**Artefact**  
A file produced by a phase (e.g., `spec.md`, `test-plan.md`, `impl-plan.md`, `review-report.md`). Stored in `.klc/tickets/<KEY>/`.

**Ack (Acknowledgement)**  
A gate where a human decides whether to approve, request rework, or cancel the phase output. Triggered via `klc ack <KEY> --pick N`.

**Rework**  
Returning to the :work sub-phase after an ack decision of "needs-rework" (or a `klc jump` / `klc abort` back-transition). The `meta.json:rework_count` field is initialized at intake and read by metrics and the `learn` gate, but the current deterministic engine does not increment it on these back-transitions, so it stays empty in practice (a historical/aspirational field).

**Manual**  
Work requiring human intervention. Estimated as a dimension (0-3) and tracked in `meta.json:estimate.manual`. M/L tickets include a dedicated manual phase.

## Ticket lifecycle

**Raw input (`raw.md`)**  
Initial ticket description written by PM or human. Input to discovery phase.

**Spec (`spec.md`)**  
Formal specification written by agent in discovery phase. Contains goals, problem, solution, ACs, estimate, constraints. Authority: agent (until ack), then sealed.

**Test plan (`test-plan.md`)**  
Test coverage document mapping ACs to acceptance tests (phase 2) and impl-plan steps to unit/integration tests (phase 4, M/L only).

**Design artefacts (`design/options.md`, `design/adr.md`)**  
M/L track only. Options lists 2-4 approaches; ADR documents the chosen option and rationale.

**Implementation plan (`impl-plan.md`)**  
M/L track only. Step-by-step build plan with step IDs (step-1, step-2, ...), affected files, expected tests.

**Build log (`build-log.md`)**  
Journal of build phase iterations. Records each step attempt, outcome (green/red/blocked), and notes. Preserved through review cycles.

**Review report (`review-report.md`)**  
Audit output from review phase. Contains findings (scope, correctness, quality, security) and verdict (approve/needs-rework/escalate).

**Observation report (`observe.md`)**  
Metrics and stability data from 24h post-merge monitoring (S/M/L only). Includes runtime metrics, error rates, rollback assessment.

**Retrospective (`retrospective.md`)**  
Learn-phase output summarizing what went well, what could improve, lessons learned, recommendations, action items.

## Configuration and metadata

**Layer**  
Architectural layer affected by the ticket (e.g., content, code, config, infra). Stored in `meta.json:layer`.

**Affected modules**  
List of code modules touched by the ticket (e.g., `["core/agents", "docs"]`). Stored in `meta.json:affected_modules`. Defines scope boundaries.

**Authority**  
Who owns the artefact: `human` (PM-written), `agent` (LLM-generated), `hybrid` (collaborative). Determines editability rules.

**Budget**  
Limits on iteration counts to prevent infinite loops. Examples: `red_test_fix_attempts` (max 3), `mutation_fix_attempts` (max 3), `regenerate_impl_plan` (max 3).

**Phase history**  
Array in `meta.json` tracking all phase transitions with timestamps, events, and notes. Used for metrics and audit trail.

## Build phase concepts

**TDD loop**  
Test-Driven Development cycle in build phase: test agent writes failing test → impl agent writes code → verifier runs tests → repeat until green.

**Step**  
One unit of work within build phase (e.g., step-1, step-2). Each step has affected files, expected tests, and completion criteria.

**DECISION item (`[!DECISION D-NNN]`)**  
Inline annotation in impl-plan.md documenting plan deviations. Format: `[!DECISION D-NNN] owner=impl-agent date=<iso> refs=step-N`.

**FACT item (`[!FACT F-NNN]`)**  
Inline annotation citing source code. Must include `src=file:line` pointing to actual code.

**QUESTION / CONFLICT item**  
Inline annotation signaling a blocker requiring human decision. Used when assumptions break or scope expands unexpectedly.

## Review phase concepts

**Scope creep**  
Implementation touching files outside `meta.json:affected_modules` without justification. Flagged in review-report.md.

**Coverage gap**  
Missing tests for an AC or impl-plan step. Review failure condition.

**Security vulnerability**  
Code issue matching OWASP top 10 categories (SQL injection, XSS, CSRF, etc.). Flagged in review-report.md security section.

## Git workflow

**Feature branch**  
Git branch for a single ticket (e.g., `feature/KLC-006-documentation`). Created from up-to-date main, merged back via integrate phase.

**Fast-forward merge**  
Git merge strategy requiring local branch to be rebased on remote main before push. Enforced by GitLab. Prevents non-linear history.

**Remote (gh / origin)**  
GitHub (`gh`) and GitLab (`origin`) remotes. GitHub `gh` is the canonical merge
point; GitLab `origin/main` is kept as a `--ff-only` mirror. See
[dual-remote-mr-pr-workflow.md](dual-remote-mr-pr-workflow.md).

## CLI commands

**`klc intake`**  
Submit new ticket. Reads `raw.md`, creates `.klc/tickets/<KEY>/`, transitions to intake:ack-needed.

**`klc status <KEY>`**  
Show ticket's current phase, completed phases, and next steps.

**`klc ack <KEY> --pick N`**  
Complete phase gate. N=1 typically means approve, N=2 needs-rework, N=3 cancel (varies by phase).

**`klc step <KEY> N`**  
Advance to build step N. Generates `_prompt_step_N.md` for impl agent.

**`klc abort <KEY>`**  
Cancel ticket, mark as aborted in meta.json.

## Index files

**`.klc/index/modules.json`**  
Maps module names to file paths and dependencies.

**`.klc/index/symbols_by_module.json`**  
Maps modules to their exported symbols (functions, classes). Used by agents to verify symbol names.

**`.klc/index/test-framework.json`**  
Test runner configuration (command, mutation tool, coverage tool).

**`.index.json` (per ticket)**  
Indexed DECISION/FACT/QUESTION items for fast lookup. Generated via `items.py index --ticket <KEY>`.

## Roles

**PM (Product Manager)**  
Human stakeholder writing raw.md, reviewing specs, making ack decisions.

**Agent**  
LLM executing phase work (writing spec, test plan, code, review reports).

**Reviewer**  
Human or agent auditing implementation in review phase.

**Framework operator**  
Developer running `klc` commands, managing git branches, resolving merge conflicts.

## Phase-specific terms

### Intake
**Raw input validation**  
Checks raw.md has required sections (Goals/Problem or Context).

### Discovery
**Estimate dimensions**  
Complexity, uncertainty, risk, manual — each scored 0-3 (total 0-12).

**Track assignment**  
Automatic based on total estimate, or manual override in meta.json.

### Acceptance-test-plan
**Acceptance coverage**  
Table mapping every AC to a test type (e2e/acceptance/manual) and test location.

### Design (M/L)
**Options.md**  
Lists 2-4 design approaches with trade-offs.

**ADR (Architecture Decision Record)**  
Documents chosen option, rationale, rejected alternatives.

### Detailed-test-plan (M/L)
**Detailed coverage**  
Table mapping impl-plan steps to unit/integration/characterisation tests.

### Build
**Green/Red/Blocked**  
Test outcome states. Green = pass, Red = fail, Blocked = cannot proceed (e.g., missing fixture).

**Characterisation test**  
Test pinning existing behavior before refactor. Ensures no regression.

### Review
**Finding**  
Issue identified by reviewer (scope, correctness, quality, security category).

**Verdict**  
approve (proceed to integrate) / needs-rework (back to build) / escalate (human decision needed).

### Manual (M/L)
**Manual QA**  
Human-performed validation steps (e.g., staging deployment test, visual inspection).

### Integrate
**Merge conflict**  
Git conflict requiring human resolution before merge to main.

### Observe (S/M/L)
**Monitoring window**  
24h post-merge period tracking metrics, errors, stability.

**Rollback assessment**  
Evaluation of whether rollback is needed based on observe data.

### Learn
**Retrospective**  
Summary of what went well, what could improve, lessons learned, action items.

## Acronyms

**AC**: Acceptance Criteria  
**ADR**: Architecture Decision Record  
**CLI**: Command Line Interface  
**LOC**: Lines of Code  
**LSP**: Language Server Protocol  
**PM**: Product Manager  
**TDD**: Test-Driven Development  
**QA**: Quality Assurance  
**E2E**: End-to-End (testing)

## Related documentation

- [Roles](roles.md) — Who does what in the framework
- [Tracks](tracks.md) — XS/S/M/L decision flowchart
- [Process overview](process.md) — High-level lifecycle description
- [Phases](phases/) — Detailed phase-by-phase guides
