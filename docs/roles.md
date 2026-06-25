# Roles in the klc framework

This document describes the roles involved in the klc ticket lifecycle and what each role is responsible for.

## Product Manager (PM)

**Who**: Human stakeholder defining requirements

**Responsibilities**:
- Write initial ticket description in `raw.md`
- Review and approve discovery phase outputs (spec.md)
- Make decisions during ack gates (approve/rework/cancel)
- Validate acceptance criteria are met before archival

**Key activities**:
- Intake: Submit ticket via `klc intake`
- Discovery ack: Review spec.md, decide approve/needs-rework
- Acceptance-test-plan ack: Review test coverage
- Final validation: Confirm all ACs met during observe/learn phases

## Agent (LLM)

**Who**: Automated agent executing phase-specific tasks

**Responsibilities**:
- Generate phase artifacts per role prompt (spec.md, test-plan.md, design options, impl-plan, code, review reports, etc.)
- Follow TDD loop in build phase (make tests pass)
- Execute within budget limits (token usage, iteration counts)
- Emit completion signals when phase work is done

**Key activities**:
- Intake (optional): cheap triage of short, low-confidence tickets — provisional track + enrichment hints (no spec.md). Intake routing itself is deterministic (no LLM).
- Discovery: Write spec.md from raw.md; uses the `AskUserQuestion` tool for the Socratic loop — exactly one question per call before recording approaches and pick
- Acceptance-test-plan: Write test-plan.md covering all ACs
- Design (M/L): Generate design options, write ADR
- Build: Implement code per impl-plan, make tests green
- Review: Audit implementation against spec/ADR
- Retrospective: Write learn-phase summary

**Constraints**:
- Cannot modify sealed artifacts (spec.md after discovery ack, design after design ack)
- Must work within affected_modules scope
- Must adhere to budget limits (red_test_fix_attempts, mutation_fix_attempts, etc.)

## Reviewer (Human or Agent)

**Who**: Human or automated reviewer in review phase

**Responsibilities**:
- Audit implementation against spec.md and ADR
- Check code quality, test coverage, security vulnerabilities
- Validate all ACs have corresponding tests
- Identify scope creep or missing functionality
- Produce review-report.md with verdict (approve/needs-rework/escalate)

**Key activities**:
- Review phase: Read build artifacts, run static analysis, check test coverage
- Produce review-report.md with findings
- Human reviewer makes final ack decision (approve/needs-rework)
- External reviewer (default-on for S/M/L via `config/reviewers.yml`): runs on both
  cheap and full cascade paths; skipped when `--no-external`, `meta.review.skip_external`,
  or the configured api key env var is unset

**Focus areas**:
- **Correctness**: Does implementation match spec?
- **Completeness**: Are all ACs covered?
- **Quality**: Code style, test coverage, documentation
- **Security**: OWASP top 10, input validation, auth/authz

## Framework operator (Human)

**Who**: Developer running klc CLI commands

**Responsibilities**:
- Execute `klc` commands to advance ticket through phases
- Run `klc ack <KEY> --pick N` to complete phase gates
- Resolve merge conflicts during integrate phase
- Monitor observe phase metrics
- Commit phase artifacts to git

**Key activities**:
- `klc intake` — submit new ticket
- `klc status <KEY>` — check current phase
- `klc ack <KEY> --pick N` — complete phase gate
- `klc step <KEY> N` — advance to next build step
- `klc abort <KEY>` — cancel ticket

**Context**:
- Operates within project root (PROJECT_ROOT env var)
- Works with git branches (feature branches per ticket)
- Manages two remotes: gl (GitLab) and gh (GitHub)

## Summary table

| Role | Human/Agent | Key phases | Main outputs |
|------|-------------|------------|--------------|
| PM | Human | intake, discovery-ack, final validation | raw.md, ack decisions |
| Agent | LLM | all :work sub-phases | spec.md, test-plan.md, code, review-report.md, retrospective.md |
| Reviewer | Human or Agent | review | review-report.md |
| Framework operator | Human | all phases (runs commands) | git commits, phase transitions |

## How roles collaborate

1. **PM writes ticket** → Framework operator runs `klc intake` → Agent generates spec.md
2. **PM reviews spec** → Framework operator runs `klc ack --pick 1` (approve) → Advance to acceptance-test-plan
3. **Agent writes test-plan.md** → Framework operator acks → Advance to build (or design for M/L)
4. **Agent implements code** → Framework operator advances steps → All tests green
5. **Reviewer audits code** → Framework operator runs `klc ack` → Advance to integrate
6. **Framework operator merges** → Advance to observe → Agent writes retrospective
7. **PM validates ACs met** → Archive ticket

For detailed phase-by-phase workflows, see `docs/phases/<phase>.md`.
