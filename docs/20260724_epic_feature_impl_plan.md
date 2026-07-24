# Epic / feature — implementation plan (2026-07-24)

**Chosen option: distributed dependencies, no single shared graph file.**

An epic is not a second lifecycle and not a new stored entity. It is three pieces
of data that live on ordinary tickets, plus a conversation front. The epic's state
and its dependency graph are **computed** by scanning member tickets — nothing about
the epic is stored as its own mutable object. This keeps every write on the existing
per-ticket CAS envelope (`state_tx` over `tickets/<KEY>/`), so a multi-user epic adds
**no new coordination surface** — the decisive reason for the distributed model over a
central `graph.json` manifest (a shared mutable file outside any ticket subtree would
need a coordination path built from scratch).

## The three data pieces (all on existing tickets)

```text
1. description → epic.md artifact in the ROOT ticket's dir: .klc/tickets/<ROOT>/epic.md
                 (a formal document OR free prose — the feature-level discussion result)
2. membership → meta.epic: "<ROOT>"  on every member ticket (the root ticket's key
                 IS the epic id — no separate namespace)
3. dependencies → meta.blocked_by on each DOWNSTREAM ticket (edges live where they are
                 enforced; the whole DAG = the union of all members' blocked_by, computed)
```

### `meta.epic`
A string equal to the **root ticket's key** (the first ticket of the feature, the one
that carries `epic.md`). The root ticket has `meta.epic` pointing at itself. Absent on
non-epic tickets. Used only for grouping/scanning — never for enforcement.

### `meta.blocked_by` (the dependency edges)
An array on the **downstream** ticket. Each edge is one "what waits for what" line:

```jsonc
"blocked_by": [
  {"on": "KLC-077", "phase": "design", "point": "design-accepted"},
  {"on": "KLC-077", "phase": "build",  "point": "integrated", "condition": "passed"}
]
```

- `on` — upstream ticket key.
- `phase` — which **downstream** phase this edge gates (the phase whose `:work` entry is blocked).
- `point` — which upstream milestone must be reached first (table below).
- `condition` (optional) — predicate on the upstream outcome; v1 vocabulary: `passed`
  (the point was reached with no rollback/regression). Absent = unconditional.

There is no central file. To see the whole graph you scan all tickets with the same
`meta.epic` and union their `blocked_by`.

## The three dependency points (upstream milestones)

`point` maps to an upstream **phase-state**, resolved against the upstream ticket's track:

| point | meaning | upstream phase-state |
|---|---|---|
| `design-accepted` | design/spec chosen | `design:ack` (M/L) **or** `discovery-lite:ack` (XS/S) |
| `integrated` | code merged, working | `integrate:ack` |
| `archived` | ticket fully done | `archived` |

"Reached the point" = the upstream ticket's current phase is **at or past** that
phase-state (a monotonic position check over `config/phases.yml`, track-aware).

`condition: passed` = the point was reached and the upstream `phase_history` shows no
rollback/abort/regression up to that point. If a condition fails, the downstream phase
is **not** unblocked and the epic view flags it as a **human pause** (do not
auto-cancel or auto-replan the downstream — a failed condition stops for a person).

## Enforcement (mechanical, no new verb)

Dependency = a **BLOCK on entering `:work`**, orthogonal to phase gates (which control
`:ack-needed → :ack`, i.e. the exit). The two never overlap: a phase can be unblocked
by deps yet still stop at its own `decision`/`integrate` gate, and vice versa.

Hook point: the `:work` entry in `core/phases/next.py` (`state == STATE_WORK`, before
`write_prompt_card` at ~line 176) and the ack path in `core/phases/ack.py` that
advances into a `:work`. Pre-check:

```text
on entering phase P of ticket T:
  edges = [e in T.meta.blocked_by if e.phase == P]
  for e in edges:
    up = read_meta(e.on)                        # read-only
    if not reached(up, e.point):        REFUSE  "blocked by <on> until <point>"
    if e.condition and not holds(e.condition, up):  REFUSE + mark human-pause
  # no edges for P, or all satisfied → proceed (write_prompt_card)
```

Degrade: empty/absent `blocked_by` → the pre-check is a pure no-op, so existing
non-epic tickets are unaffected. A dangling `on` (references a missing ticket) is
treated as unsatisfiable → refuse with a clear message (and the view flags it).

## Epic state — a pure function of member tickets (never stored)

```text
all members in intake:*              → planned
any member past intake               → in-progress
all members archived|cancelled       → done
```
(Matches the agreed rules: any ticket past intake ⇒ feature in work; all terminal ⇒ epic done.)

## Epic view (read-only)

Extend `board` (no new verb): `board --epic <ROOT>` shows, for the epic:
- computed state (planned / in-progress / done);
- per member: current phase, "blocked by …" (unmet edges), and holder if occupied;
- the **ready set** — members whose next phase has no unmet dependency and is not held
  by someone else (held → shown as "occupied", not "ready", per the multi-user model);
- **validation at view time**: detect cycles (mutual `blocked_by` → nobody can start)
  and dangling edges (`on` not a member / not a real ticket) → warn. Because no single
  write sees the whole graph, cycle/dangling checks run here and in the skill-front
  (not at single-edge write time).

## Skill-front — "discuss a new feature"

A Claude Code skill is the entry the user asked for ("хочу обсудить новую фичу"). It is
one conversation, not CLI incantations. Per the interactive principles (one question at
a time, lead with a recommendation, explore before asking):

```text
1. problem + artifacts   — conversation; attached files fold into epic.md
2. discussion            — scope/boundaries → epic.md
3. feature-level plan    — decompose into tickets with rationale + the dependency edges
                           (NOT per-ticket impl-plan; that appears later inside each ticket)
4. create + run          — skill calls `klc intake --epic <ROOT> --blocked-by ...` per
                           ticket, validates the whole set (cycles/dangling) BEFORE
                           creating, writes epic.md into the root ticket, then shows the
                           ready set; the user drives ready tickets with klc run/next/ack,
                           and edges unblock downstream as points are reached.
```

## Execution / multi-user (reuse what exists)

- Parallelism is the **ready set**: the user (or several people) pick from unblocked
  tickets and drive them with existing `klc run`/`next`/`ack`. No worktree/multi-agent
  infra is added.
- Hand-off uses the existing **holder** mechanism: a phase shift releases the holder
  (`ack`/`next`/`abort`); a ticket abandoned mid-phase holds until the 30-min TTL, then
  `klc steal`. Different people on one ticket is already supported.
- "Not past build" ceiling is per-edge: a leaf ticket (nobody depends on it) stops at
  `build`; a ticket someone depends on at `integrated`/`archived` is driven that far
  (real merge / archived). `autorunner` always pauses at `integrate`, so review/merge
  stay human.

## Ticket decomposition (this epic, built against this shared contract)

Root ticket = **KLC-077** (holds `epic.md`). All three carry `meta.epic: "KLC-077"`.
The conceptual DAG (recorded in each ticket's raw.md as prose until enforcement exists;
this epic bootstraps the very machinery that would enforce it):

```text
KLC-078.build ← KLC-077 @ design-accepted   (view builds against the schema contract)
KLC-079.build ← KLC-077 @ integrated        (skill needs the real intake flags)
KLC-079.build ← KLC-078 @ integrated        (skill surfaces the ready-set view)
```

- **KLC-077 — schema + intake flags + `:work` enforcement (M).** Define `meta.epic` +
  `meta.blocked_by`; `intake --epic <ROOT>` and repeatable `--blocked-by "<K>@<point>[:cond]#<phase>"`;
  `core/skills/epic_deps.py` (point→phase-state resolver, track-aware `reached()`,
  `condition holds()`); the `:work` pre-check in `next.py`/`ack.py`. No-op when no edges.
  Coordination-sensitive (gates `:work` on the live machine) → real-substrate tests that
  a blocked phase refuses and unblocks exactly when the upstream point is reached; edits
  ride the per-ticket `state_tx` (no new coordination path).
- **KLC-078 — epic state + `board --epic` view + validation (M).** Compute state from
  members; render per-member phase / blocked-by / holder / ready-set; cycle + dangling
  detection. Read-only. Builds against the schema (reads the json fields; does not need
  077's writer at runtime — tests seed metas directly).
- **KLC-079 — skill-front "discuss a new feature" (S–M).** The Claude Code skill:
  conversation → epic.md in root ticket → decompose → `intake --epic --blocked-by` per
  member → validate the set → show ready set. Uses 077's flags + 078's view. Skill is
  mostly prose; any helper stubs the CLI boundary in tests.

All three are built in parallel off `main`, each strictly following the schema/interfaces
in THIS document — the doc is the shared contract that keeps the parallel builds
consistent. Review/merge in dependency order (077 → 078 → 079).

## Non-goals

- No second state machine for the epic; no stored epic state.
- No `.klc/epics/` dir, no `graph.json`, no `EPIC-ID` namespace, no central manifest.
- No new coordination primitive: every write is a normal per-ticket `state_tx`.
- No worktree/multi-agent execution infra; parallelism is the ready set + holder hand-off.
- No dependency on unmerged code via branch stacks: `integrated` means a real merge.

## Open items (decide during each ticket's design phase)

- Richer `condition` predicates beyond `passed` (e.g. matching a specific
  `design_choice`) — add on the design phase of KLC-077 if needed.
- Whether the epic id should later also allow a free slug (not tied to a root ticket).
  v1 = root-ticket-key (description lives in the first ticket, per the agreed shape).
- An optional **derived** read-only graph render (computed like `modules.json`, never
  hand-edited) if a single whole-graph view is later wanted — not needed for v1.
