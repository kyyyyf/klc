# Process phases (0–7 and 9; 8 optional)

The framework drives a 9-phase flow. Each phase has a single entry
point under `scripts/klc`. Companion documents:

- [`process-roles.md`](process-roles.md) — who does what (human /
  agent / script / tool) per phase.
- [`process-artifacts.md`](process-artifacts.md) — file-by-file
  artefact schema.
- [`process-metrics.md`](process-metrics.md) — metric catalogue and
  rollups.

## Phase map

| # | Name | Entry point | Human gate? | Skip rule |
|---|------|-------------|-------------|-----------|
| 0 | Intake | `klc intake <key> "<desc>"` | — | never |
| 1 | Discovery | `klc discover <key>` | ack (pull-ready, track) | never |
| 2 | Acceptance test plan | `klc test-plan <key>` | — | XS (tests land in Build) |
| 3 | Design | `klc design <key>` | ack (direction) | XS / S (jump to Build) |
| 4 | Detailed test plan | `klc test-plan <key> --detailed` | — | XS / S |
| 5 | Build | `klc build <key>` | — | never |
| 6 | Review | `klc review <key>` | ack (merge-approval) | never |
| 7 | Manual check | `klc manual <key>` | ack (manual) | `estimate.manual` ≤ 1 |
| 8 | Integrate | `klc integrate pre <key>` → human `git merge` → `klc integrate post <key> --merge-sha <sha>` | — | never |
| 9 | Observe (optional) | `klc observe <key>` | — | projects without deploy automation |
| 10 | Learn | `klc learn <key>` | — | never |

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

### How phase 8 works

The framework **never runs `git merge`**. Phase 7 is two thin
bookends around the team's actual merge flow:

- `klc integrate pre` — runs after Review ack. Executes the
  consistency gate, snapshots artefact hashes, prints go / no-go.
- Human performs `git merge` (or opens PR, pushes, anything the
  team's branch policy asks).
- `klc integrate post --merge-sha <sha>` — records the SHA, verifies
  the snapshot still matches, archives scratch, bumps phase to
  `observe` (or `learn` if observe is disabled).

This keeps us out of the merge-policy business while still giving
Observe / Learn a stable handoff.

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
- Downgrading the track is forbidden. Upgrading is allowed at the
  discovery ack via `klc ack ... --upgrade-track L`.

## Lifecycle

`core/skills/lifecycle.py` owns the phase state machine. Each phase
script reads `meta.json:phase` and calls `lifecycle.advance(target)`
on success. Illegal jumps raise and are rejected before any artefact
is touched. Full transition graph is in `lifecycle.py:TRANSITIONS`.

Only two ways to move backwards:

- `klc back <key> --to <phase> --reason "..."` — audited rework jump
  (increments `rework_count` for the source phase).
- `klc manual ... --outcome=fail` — suggests `klc back` to the human
  without running it automatically.

## Human gates

Default count: **3 mandatory + 1 conditional**.

| # | Gate | Command | Condition |
|---|------|---------|-----------|
| 1 | Pull-ready | `klc ack <key> --for discovery` | always |
| 2 | Direction | `klc ack <key> --for design` | when phase 3 ran |
| 3 | Merge approval | `klc ack <key> --for review` | always |
| 4 | Manual check | `klc ack <key> --for manual` | only when `estimate.manual` ≥ 2 |

Everything else is agent-driven; agents escalate on signals listed
in §11 below.

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
| `klc ack <key> --for <gate>` | satisfy a gate |
| `klc back <key> --to <phase> --reason "..."` | audited rework |
| `klc status <key>` | human-readable diagnosis (read-only) |
| `klc resume <key>` | re-enter the interrupted phase |
| `klc doctor` | install-level health check |
| `klc board` | kanban view of every live ticket |
| `klc metrics <key>` / `klc metrics --rollup` | per-ticket / aggregate metrics |
| `klc reindex <key>` | rebuild `.index.json` of inline items |

All share the same `$PROJECT_ROOT` resolution as phase scripts.

## Artefact rule of thumb

Every phase reads / writes a specific subset of
`.klc/tickets/<key>/`. Cross-artefact authority is enforced by the
consistency gate (see `process-proposal.md` §4). If you're about to
write a code path that cares about "which file belongs to which
phase", go to `process-artifacts.md` instead of guessing.
