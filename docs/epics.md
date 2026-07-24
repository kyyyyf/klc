# Epics / features

A user-facing guide to the lightweight epic layer (KLC-077 / KLC-078 / KLC-079).
For the design and rationale, see the spec:
[`docs/20260724_epic_feature_impl_plan.md`](20260724_epic_feature_impl_plan.md).

## What an epic is

An epic is simply a **group of ordinary tickets** that make up one feature,
plus the dependency edges between them. It is deliberately *not* a second
lifecycle: there is no epic state machine, no `EPIC-` key namespace, no
`.klc/epics/` directory, and no central `graph.json` manifest. Everything an
epic "is" comes from three pieces of data that live on the member tickets
themselves, and every epic-level answer (its state, its dependency graph, its
ready set) is **computed** by scanning those members. Because there is no shared
mutable epic object, an epic adds no new coordination surface — every write is a
normal per-ticket `state_tx`.

```text
1. description  → epic.md in the ROOT ticket's dir: .klc/tickets/<ROOT>/epic.md
2. membership   → meta.epic = "<ROOT>" on every member (the root points at itself)
3. dependencies → meta.blocked_by edges on each downstream ticket
```

### Membership — `meta.epic`

Every member ticket carries `meta.epic` set to the **root ticket's key**. The
root is the first ticket of the feature — the one whose directory holds
`epic.md` — and its own `meta.epic` points at itself. The root key *is* the epic
id; there is no separate namespace. `meta.epic` is used only for grouping and
scanning, never for enforcement. Plain (non-epic) tickets have no `meta.epic`
key at all, so they are byte-for-byte unaffected.

### Description — `epic.md`

The feature-level description (the problem, agreed scope, and boundaries) lives
as a free document at `.klc/tickets/<ROOT>/epic.md`. It is prose, not a ticket
spec — the per-ticket specs are produced later inside each ticket's own design
phase.

### Epic state — computed, never stored

The epic's state is a pure function of its members' phases, evaluated in this
order (matching `epic_view.epic_state`, which checks "done" first):

```text
all members archived | cancelled     → done
all members in intake:*              → planned
otherwise (any member past intake)   → in-progress
```

There is no stored state to keep in sync — `board --epic` recomputes it on every
read.

## Dependencies — `meta.blocked_by`

Dependencies are recorded as per-ticket edges, and they live on the
**downstream** ticket (the one that must wait). The whole dependency graph is the
union of every member's `blocked_by` — there is no central file. Each edge is a
dict:

```jsonc
"blocked_by": [
  {"on": "KLC-077", "phase": "design", "point": "design-accepted"},
  {"on": "KLC-077", "phase": "build",  "point": "integrated", "condition": "passed"}
]
```

- **`on`** — the upstream ticket key this ticket waits on.
- **`phase`** — which **downstream** phase this edge gates (the phase whose
  `:work` entry is blocked).
- **`point`** — the upstream milestone that must be reached first (table below).
- **`condition`** *(optional)* — a predicate on the upstream outcome. The v1
  vocabulary is a single value, `passed`. Absent = unconditional.

### The three dependency points

`point` resolves to an upstream **phase-state**, against the upstream ticket's
own track:

| point             | meaning                     | upstream phase-state                              |
|-------------------|-----------------------------|---------------------------------------------------|
| `design-accepted` | design / spec chosen        | `design:ack` (M/L) **or** `discovery-lite:ack` (XS/S) |
| `integrated`      | code merged and working     | `integrate:ack`                                   |
| `archived`        | ticket fully done           | `archived`                                        |

"Reached the point" means the upstream ticket's current phase is **at or past**
that phase-state — a monotonic position check over `config/phases.yml`, resolved
against the upstream's track.

### The `passed` condition

`condition: passed` holds when the point was reached **and** the upstream's
`phase_history` shows no rollback, abort, regression, or jump signal — a `jump`
taints regardless of direction, since it is a cross-cut/rework event — and no
`cancelled` / `regression_observed` marker. If a condition fails, the
downstream phase is **not** unblocked and the epic view flags it as a human
pause — a failed condition stops for a person; it never auto-cancels or
auto-replans the downstream ticket. Any unknown condition is treated as
not-holding (fail-safe: it blocks and asks a human).

## Enforcement — a block on entering `:work`

A dependency is a **block on entering the gated phase's `:work` state**. It is
checked at the `:work` entry, inside the verb's transaction, right after the
state pull (so a peer's just-merged upstream progress is seen). If any edge for
that phase is unmet, the transition is refused with a clear message; the
autorunner turns the same refusal into a clean pause.

This is **orthogonal to phase gates**. Phase gates (the `pick_required` picks in
`config/phases.yml`) control the `:ack-needed → :ack` *exit* of a phase.
Dependency edges control the `:work` *entry*. The two never overlap: a phase can
be unblocked by its dependencies yet still stop at its own `decision` /
`integrate` gate, and vice versa.

Degrade-not-fail: an empty or absent `blocked_by` makes the check a pure no-op,
so non-epic tickets are never affected. An edge whose `on` references a missing
ticket is treated as unsatisfiable (dangling) and refuses with a message telling
a human to fix the edge.

## The view — `klc board --epic <ROOT>`

`klc board --epic <ROOT>` is a read-only, epic-scoped view (it never advances a
phase or writes meta). It scans the members and shows:

- the **computed epic state** (planned / in-progress / done);
- each member's current **phase**, its unmet **blocked-by** edges, and its
  **holder** if someone is working it;
- the **ready set** — members that can be picked up now: their immediate next
  `:work` entry has no unmet dependency and the ticket is not held by another
  user (a held member is shown as **occupied**, not ready, per the multi-user
  holder model);
- **blocked** members (an unmet edge gates their immediate next `:work`) and
  **upcoming** gates (an unmet edge that gates a *later* phase — it does not drop
  the member from the ready set, because early-phase work is still actionable);
- **validation warnings** computed at view time: dependency **cycles** (mutual
  `blocked_by` so nobody can start), **dangling** edges (`on` is not a real
  ticket), and **dead** edges (the gated phase is not in that ticket's track, so
  the edge can never fire). These whole-graph checks run here (and in the skill
  front) because no single edge-write ever sees the whole graph.

Add `--json` for a machine-readable report.

## The entry — "discuss a new feature"

The intended way to create an epic is the **discuss-feature** skill
(`klc-plugin/skills/discuss-feature`), invoked as `/klc:discuss-feature`. It is
one conversation, not a sequence of CLI incantations:

```text
1. problem + artifacts   — the conversation; attached files fold into epic.md
2. discussion            — agree scope and boundaries → epic.md
3. feature-level plan    — decompose into tickets, each with a rationale and its
                           dependency edges (NOT a per-ticket impl-plan)
4. create + run          — validate the whole planned set BEFORE creating anything
                           (cycles / dangling / every ticket has a description /
                           every edge's #phase is real), then run intake per ticket,
                           write epic.md into the root, and show `board --epic <ROOT>`
```

Validation happens **before** any ticket is created (via
`core/skills/epic_plan.py`), so a bad plan creates nothing — a partial epic is
worse than no epic. Once created, you drive the ready tickets with the ordinary
`klc run` / `next` / `ack`, and edges unblock downstream tickets as their upstream
points are reached.

### Doing it by hand — the intake flags

The skill ultimately shells out to `klc intake`. The exact flags (defined in
`core/phases/intake.py`) are:

```text
klc intake <KEY> --epic <ROOT> \
  [--blocked-by "<K>@<point>[:cond]#<phase>" ...] \
  "<description>"
```

- `--epic <ROOT>` — tags this ticket as a member of the epic rooted at `<ROOT>`
  (the root is created with `--epic` pointing at itself).
- `--blocked-by "<K>@<point>[:cond]#<phase>"` — **repeatable**; records one
  dependency edge on this (downstream) ticket. The grammar and the
  point/condition vocabulary are owned by `core/skills/epic_deps.parse_edge`, so
  the CLI and the skill's validation can never drift.
- the trailing `"<description>"` positional is mandatory — intake refuses a
  description-less ticket (rc 2) before writing anything.

Edge grammar:

```text
<K>@<point>[:cond]#<phase>
```

| part    | meaning                                                                |
|---------|------------------------------------------------------------------------|
| `<K>`   | upstream ticket key (the one this ticket waits on)                     |
| `point` | upstream milestone: `design-accepted` \| `integrated` \| `archived`    |
| `cond`  | optional condition on the outcome — v1 vocabulary: `passed`            |
| `phase` | the **downstream** phase this edge gates (whose `:work` entry blocks)   |

Read `KLC-077@integrated:passed#build` as: *this ticket's `build` phase cannot
start until KLC-077 reaches `integrated`, and only if that point was reached with
no rollback / regression.* Omit `:cond` for an unconditional edge. Example
(three-ticket epic rooted at KLC-077):

```bash
klc intake KLC-077 --epic KLC-077 "epic root: schema + intake flags + :work enforcement"
klc intake KLC-078 --epic KLC-077 --blocked-by "KLC-077@design-accepted#build" \
  "epic state + board --epic view + validation"
klc intake KLC-079 --epic KLC-077 \
  --blocked-by "KLC-077@integrated#build" \
  --blocked-by "KLC-078@integrated#build" \
  "discuss-feature skill front"
klc board --epic KLC-077
```

## Non-goals (what an epic deliberately is not)

- No second state machine and no stored epic state — state is computed.
- No `.klc/epics/` directory, no `graph.json`, no `EPIC-` namespace, no central
  manifest.
- No new coordination primitive — every write is a normal per-ticket `state_tx`.
- No worktree / multi-agent execution infra — parallelism is just the ready set
  plus the existing holder hand-off.
- `integrated` means a real merge; there is no dependency on unmerged branch
  stacks.
