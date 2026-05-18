# Process phases

The framework drives a linear flow through 10 phases defined in
[`config/phases.yml`](../config/phases.yml). Each phase has three
states — `:work`, `:ack-needed`, `:ack` — plus one terminal
`archived`. Six verbs drive every transition:

- `klc intake <key> "<desc>"` — create the ticket
- `klc status <key>` — show the path through the current track
- `klc next <key>` — advance `:ack` → next phase's `:work`
- `klc ack <key> [--pick N]` — confirm `:ack-needed`
- `klc jump <phase> <key> [--yes]` — cross-cut (with dry-run)
- `klc abort <key>` — cancel `:work`, return to previous `:ack`

Companion documents:

- [`process-roles.md`](process-roles.md) — who does what (human /
  agent / script / tool) per phase.
- [`process-artifacts.md`](process-artifacts.md) — file-by-file
  artefact schema.
- [`process-metrics.md`](process-metrics.md) — metric catalogue and
  rollups.

## Phase map

Every phase is entered the same way — `klc next <key>` from the
previous phase's `:ack`, or `klc jump <phase> <key> --yes` to
cross-cut. The picks listed at `:ack-needed` are the ones the user
selects with `klc ack <key> --pick N`.

| # | Phase id               | Tracks       | Picks at `:ack-needed` | Skip rule |
|---|------------------------|--------------|------------------------|-----------|
| 0 | `intake`               | XS, S, M, L  | 1 = confirm            | never |
| 1 | `discovery`            | S, M, L      | 1 = approve · 2 = needs-rework | XS |
| 2 | `acceptance-test-plan` | S, M, L      | 1 = approve · 2 = needs-rework | XS |
| 3 | `design`               | M, L         | 1 = option-A · 2 = option-B · 3 = option-C · 4 = needs-rework | XS, S |
| 4 | `detailed-test-plan`   | M, L         | 1 = approve · 2 = needs-rework | XS, S |
| 5 | `build`                | XS, S, M, L  | 1 = approve           | never |
| 6 | `review`               | XS, S, M, L  | 1 = approve · 2 = request-changes (→ build:work, supersedes review) | never |
| 7 | `manual`               | M, L         | 1 = passed · 2 = failed (→ build:work, supersedes review+manual) | XS, S |
| 8 | `integrate`            | XS, S, M, L  | 1 = merged             | never |
| 9 | `observe`              | S, M, L      | 1 = clean · 2 = regression (→ build:work) · 3 = rollback (→ learn:work) | XS |
| 10 | `learn`               | XS, S, M, L  | 1 = archive · 2 = extract-to-CLAUDE.md | never |

The authoritative definition lives in
[`config/phases.yml`](../config/phases.yml) — track filters, picks,
and auto-jumps are all data. To change the process, edit that file.

### Why test planning is split

Acceptance tests (spec-level, AC → e2e) and detailed unit /
integration tests answer different questions and depend on different
inputs. Acceptance tests derive from `spec.md` alone; detailed ones
need `design/options.md` + `impl-plan.md`. Planning them in one
column forces either premature commitment (pick the tests before
knowing the design) or stale TDD (plan tests after everything else,
violating the "red first" discipline). Splitting the column makes
both work:

- phase 2 guarantees every AC has a concrete e2e test before any
  implementation discussion;
- phase 4 fills in unit-level coverage once the actual files, classes
  and step IDs are known;
- the two live in the same `test-plan.md` (two sections) so
  reviewers and humans see one file.

XS / S skip phase 4: XS plans nothing (test lands in Build), S's
acceptance table is enough and unit tests emerge during the TDD
loop.

### How `integrate` works

The framework **never runs `git merge`**. `integrate:work` is a
two-tick phase that bookends the team's actual merge flow:

- **Tick 1 — pre-merge.** Run the consistency gate, snapshot
  artefact hashes, print go / no-go. Kick off the team's PR / merge
  request.
- **Tick 2 — post-merge.** Record the merge SHA in `meta.json`,
  verify the snapshot still matches, archive scratch.

Both ticks happen inside one `:work` state (the tick is internal
state in `meta.json`). `klc ack <key> --pick 1` closes the phase
once both ticks are done. This keeps klc out of the merge-policy
business while still giving `observe` / `learn` a stable handoff.

## Tracks

Four tracks classify tickets by multi-dimensional estimate. The
mapping sits in `core/agents/discovery.md`; short version:

| Track | Total score | Typical scope | Template set |
|-------|-------------|---------------|--------------|
| XS | 0–2  | one-line change | `*-short.md.j2` for every artefact |
| S  | 3–5  | local fix, local refactor | short impl-plan, full spec/test-plan |
| M  | 6–8  | feature in one module | full everywhere |
| L  | 9–12 | cross-module feature or new dep | full + obligatory ADR |

Guard invariants:
- Any axis = 3 floors the track at M.
- Uncertainty = 3 with total ≥ 7 forces L.
- Downgrading the track is forbidden. Upgrading the track between
  phases is the discovery agent's responsibility — if discovery
  returns from rework with a higher track, the downstream phase set
  widens accordingly.

## Lifecycle

`core/skills/lifecycle.py` + `core/skills/phases.py` own the state
machine. `lifecycle.py` knows the five operations (`set_state`,
`apply_ack`, `advance_to_next`, `jump`, `abort`); `phases.py` loads
`config/phases.yml` and resolves per-track phase sequences, pick
definitions, and auto-jump targets. Neither module hardcodes phase
names.

Movement primitives:

- `klc next` — only legal from `<X>:ack`; picks the next
  track-applicable phase's `:work`.
- `klc ack --pick N` — only from `<X>:ack-needed`; follows the
  pick's `goto` (usually `next`, sometimes `<phase>:work` with a
  supersede list — e.g. review pick 2 auto-reopens `build:work` and
  moves the stale review report to `_superseded/`).
- `klc jump <phase> --yes` — only from `<X>:ack`; cross-cut to any
  `<phase>:work`. Backward jumps supersede downstream artefacts;
  budgets always reset. Without `--yes` the command is a dry run
  that prints the plan.
- `klc abort` — only from `<X>:work`; supersedes current-phase
  artefacts and drops back to the previous phase's `:ack`. This is
  how you leave a stuck `:work` without a successful `ack`.

Rework is not a special verb. The two common flows are:

- Reviewer rejects → `klc ack <key> --pick 2` → `build:work` again.
- Decision to rework after an earlier ack → `klc jump <phase> <key>
  --yes` from the `:ack` you reached → fresh `:work`, downstream
  artefacts parked under `_superseded/<ts>/`.

## Human gates

Every phase with `pick_required: true` in `config/phases.yml` is
effectively a gate. The human doesn't tick a checkbox — they hit
`klc ack <key> --pick N` with a pick that carries meaning for the
downstream flow. Default obligatory gates (always-on):

| Gate | At phase | Picks |
|------|----------|-------|
| Pull-ready | `discovery:ack-needed` | 1 = approve · 2 = needs-rework |
| Direction  | `design:ack-needed`    | 1..3 = option A/B/C · 4 = needs-rework |
| Merge approval | `review:ack-needed` | 1 = approve · 2 = request-changes |

Conditional gates (only when the track includes the phase):

| Gate | At phase | Picks |
|------|----------|-------|
| Acceptance test plan | `acceptance-test-plan:ack-needed` (S, M, L) | 1 = approve · 2 = needs-rework |
| Detailed test plan | `detailed-test-plan:ack-needed` (M, L) | 1 = approve · 2 = needs-rework |
| Manual check | `manual:ack-needed` (M, L) | 1 = passed · 2 = failed |
| Observation outcome | `observe:ack-needed` (S, M, L) | 1 = clean · 2 = regression · 3 = rollback |
| Learn outcome | `learn:ack-needed` | 1 = archive · 2 = extract-to-CLAUDE.md |

Everything else is agent-driven; agents escalate on the signals
listed below.

## Signals that escalate to the human

Outside of the ordered gates, agents pull the human on any of:

- `tests stuck red > budget` (`red_test_fix_attempts` exceeded).
- `mutation score < threshold` after `mutation_fix_attempts`.
- `CONFLICT` item emitted anywhere.
- Scope creep: diff touches modules not in `affected_modules`.
- Budget-exceeded event — agent writes `meta.json:blocked_reason`
  and halts.
- `rework_count[<phase>] ≥ 3` — third bounce → escalate to lead.

Signals are written to the scratchpad (`scratch.py`) and to
`serena-calls.log` where applicable so Retrospective can review
them.

## Operational commands (not phases)

| Command | Purpose |
|---------|---------|
| `klc status <key>` | vertical path view; read-only |
| `klc board` | kanban view across live tickets |
| `klc doctor` | install-level health check |
| `klc metrics <key>` / `klc metrics --rollup` | per-ticket / aggregate metrics |
| `klc reindex <key>` | rebuild `.index.json` of inline items |
| `klc install <project>` | bootstrap a project to use this klc checkout |
| `klc init` / `klc update` | run / refresh the indexing loop |

All share the same `$PROJECT_ROOT` resolution as the lifecycle
verbs.

## Artefact rule of thumb

Every phase reads / writes a specific subset of
`.klc/tickets/<key>/`. Cross-artefact authority is enforced by the
consistency gate (see `process-proposal.md` §4). If you're about to
write a code path that cares about "which file belongs to which
phase", go to `process-artifacts.md` instead of guessing.
