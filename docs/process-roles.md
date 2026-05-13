# Role map — who does what across the phases

One row per phase. "Human" / "Agent" / "Script" / "Tool" columns show
who is responsible; links point to the file that implements the role.

Legend:
- **Human** — a decision only a person can make (intent, direction,
  merge approval, manual sign-off).
- **Agent** — LLM prompt at `core/agents/*.md` executed by Claude Code
  (or any MCP-capable client).
- **Script** — executable at `scripts/*` or `core/phases/*.py` called
  via the `klc` dispatcher.
- **Tool** — MCP server or CLI tool the script/agent uses: Serena,
  ast-grep, git, external reviewer LLMs.

The entire flow is driven by `scripts/klc` — one dispatcher,
subcommands per phase. Legacy wrappers `feature.sh` / `bug.sh` are
deprecated; see `MIGRATION.md`.

| # | Phase | Human | Agent | Script | Tool |
|---|-------|-------|-------|--------|------|
| — | init (one-off) | — | `core/agents/inventory.md` + `core/agents/decompose.md` + `core/agents/docgen.md` | `scripts/init.sh` | ast-grep, git |
| — | update (cron) | — | `core/agents/periodic.md` | `scripts/update.sh` | ast-grep, git, `serena-call` on L only |
| 0 | Intake | types the raw description | `core/agents/intake.md` | `klc intake <key> "<desc>"` (`core/phases/intake.py`) | git (reads user config) |
| 1 | Discovery | acks pull-ready + track | `core/agents/discovery.md` (wraps `core/agents/validator.md`) | `klc discover <key>` (`core/phases/discover.py`) | ast-grep; Serena only on L with override |
| 2 | Acceptance test plan | — | `core/agents/test-planner.md` (acceptance mode) | `klc test-plan <key>` (`core/phases/test_plan.py`) | — |
| 3 | Design | acks direction + ADR | `core/agents/design.md` + `core/agents/adr.md` + `core/agents/plan.md` | `klc design <key>` (`core/phases/design.py`) | Serena (verify symbols on M/L via `serena-call.py`) |
| 4 | Detailed test plan | — | `core/agents/test-planner.md` (detailed mode) | `klc test-plan <key> --detailed` (`core/phases/test_plan.py`) | — |
| 5 | Build | watches on escalation signals | `core/agents/test.md` + `core/agents/impl.md` + `core/agents/validator.md` | `klc build <key>` (`core/phases/build.py`) | Serena, ast-grep, test runners, mutation tools |
| 6 | Review | acks merge approval | `core/agents/review.md` + `core/agents/review/*.md` | `klc review <key>` (`core/phases/review.py` — thin wrapper over `review.sh`) | Serena (reviewers verifying signatures), external reviewer LLM (optional) |
| 7 | Manual check | ticks the checklist | `core/agents/manual-check.md` | `klc manual <key>` (`core/phases/manual.py`) | — |
| 8 | Integrate | runs `git merge` between `pre` and `post` | `core/agents/consistency.md` (wraps `consistency_check.py`) | `klc integrate pre <key>`; `klc integrate post <key> --merge-sha <sha>` (`core/phases/integrate.py`) | git, `items.py validate`, `consistency_check.py` |
| 9 | Observe (optional) | — | — (no-op today; CI hook later) | `klc observe <key>` (`core/phases/observe.py`) | — |
| 10 | Learn | reviews proposed allowlist / few-shot edits | `core/agents/retrospective.md` | `klc learn <key>` (`core/phases/learn.py`) | `metrics.py rollup`, `serena_deny.py propose` |

## Operational commands (not phases)

| Command | Agent | Script | Purpose |
|---|---|---|---|
| `klc ack <key> --for <phase>` | — | `core/phases/ack.py` | Satisfy a human-gate. Required to leave `*-pending-ack` phases. |
| `klc back <key> --to <phase> --reason "..."` | — | `core/phases/back.py` → `lifecycle.py:back` | Rework. Only way to move a ticket backwards. |
| `klc status <key>` | — | `core/phases/status.py` | Human-readable diagnosis: current phase, pending issues, budget state. |
| `klc resume <key>` | — | `core/phases/resume.py` | Re-enter the interrupted phase idempotently. |
| `klc doctor` | — | `core/phases/doctor.py` | Install-level health check. Safe on CI. |
| `klc board` | — | `core/phases/board.py` | Kanban view of all tickets by current phase. |
| `klc metrics <key>` / `klc metrics --rollup` | — | `core/skills/metrics.py` | Per-ticket JSON or 30-day rollup. |
| `klc reindex <key>` | — | `core/skills/items.py index` | Rebuild `.index.json` of inline items. |

## Tools used across phases

- **Serena** (LSP-backed symbol queries). Gated by `core/skills/serena-call.py`; track-aware policy blocks XS from all phases, S outside Build, etc. Cache per-ticket at `.klc/tickets/<key>/serena-cache/`.
- **ast-grep** — structural code search (profile rules at `profiles/<name>/rules/`). Available everywhere, no gate.
- **git** — every phase that touches files expects a clean-enough working tree. `klc doctor` surfaces `git status` warnings.
- **Test runners / mutation tools** — detected at `klc test-plan` time and recorded in `.klc/index/test-framework.json`. Not framework-shipped; install per project.

## Human-gate summary

Default count: **3 obligatory + 1 conditional**.

1. `klc ack <key> --for discovery` — pull-ready.
2. `klc ack <key> --for design` — direction.
3. `klc ack <key> --for review` — merge approval.
4. `klc ack <key> --for manual` — only when `manual` axis ≥ 2.

Everything else is LLM-driven. Agents escalate to human on the
signals enumerated in `process-phases.md` §11, not on a schedule.
