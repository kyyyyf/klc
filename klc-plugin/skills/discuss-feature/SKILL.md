---
name: klc-discuss-feature
description: >
  Entry point for "I want to discuss a new feature" (обсудить новую фичу). One
  conversation — not CLI incantations — that turns a rough problem into a KLC
  epic: fold the problem and any attached artifacts into epic.md, discuss scope
  and boundaries, decompose into tickets with rationale and dependency edges,
  then validate the whole planned set (cycles + dangling edges) BEFORE creating
  anything, create each ticket via `klc intake --epic <ROOT> --blocked-by …`,
  write epic.md into the root ticket, and show the ready set via
  `board --epic <ROOT>`. Orchestrates the KLC-077 intake flags and the KLC-078
  epic view; it does not reimplement enforcement or state computation.
---

# /klc:discuss-feature — the "discuss a new feature" front

## What this is

You are the **main agent** having ONE conversation with the user about a new
feature. The output of that conversation is a KLC **epic**: a set of ordinary
tickets tied together by three pieces of data, defined by the shared contract at
`docs/20260724_epic_feature_impl_plan.md` (read it — it is authoritative):

```text
1. description  → epic.md in the ROOT ticket's dir: .klc/tickets/<ROOT>/epic.md
2. membership   → meta.epic = "<ROOT>" on every member (root points at itself)
3. dependencies → meta.blocked_by edges on each downstream ticket
```

An epic is **not** a second lifecycle and **not** a stored object. Its state and
its dependency graph are computed by scanning member tickets. You do not create
any of that machinery here — you drive the flags KLC-077 adds to `intake` and the
view KLC-078 adds to `board`. This skill is the conversation and the
orchestration around them, nothing more.

## The interactive principles (how to run the conversation)

Follow these the whole way through — they are the point of a skill-front over raw
CLI:

- **One question at a time.** Never dump a questionnaire. Ask, listen, then ask
  the next thing informed by the answer.
- **Lead with a recommendation.** Do not ask open "what do you want?" questions
  when you can propose a concrete answer and ask the user to confirm or correct
  it. Give your reasoning, then let them steer.
- **Explore before asking.** Read the attached artifacts and the codebase first;
  spend your own effort before spending the user's. Ask only what you genuinely
  cannot determine yourself.

## The four steps

### 1. Problem + artifacts → epic.md

Draw out the problem in the user's words. Read any attached files. Fold both into
a first draft of `epic.md` — a formal document or free prose, whichever fits.
This is the feature-level description, not a ticket spec. Keep it in your working
notes for now; you write it into the root ticket's dir in step 4 (the root key is
not known until the tickets are created).

### 2. Discussion → scope / boundaries

Discuss what is in and what is out. Capture the agreed scope and boundaries into
`epic.md`. Surface non-goals explicitly. This is where you and the user agree on
the shape of the feature before decomposing it.

### 3. Feature-level plan → tickets + dependency edges

Decompose the feature into tickets. For each ticket capture:

- a short **rationale** (why it is its own ticket);
- its **dependency edges** — which other tickets (and at which milestone) must be
  reached before this ticket's work can start.

This is a *feature-level* plan. It is **not** a per-ticket implementation plan —
those are produced later, inside each ticket's own design phase. Here you only
decide the ticket boundaries and the edges between them.

Choose the **root** ticket — the first ticket of the feature, the one that will
carry `epic.md`. Its key becomes the epic id; every member gets `meta.epic =
"<ROOT>"`.

#### Edge syntax (parsed by KLC-077's `epic_deps.parse_edge` — the single source)

Each edge is one string. The grammar and the point/condition vocabulary below are
owned by `core/skills/epic_deps.py` (KLC-077): both `klc intake --blocked-by` and
this skill's pre-create validation parse edges through the same
`epic_deps.parse_edge`, so the syntax can never drift between them.

```text
<K>@<point>[:cond]#<phase>
```

| part    | meaning                                                              |
|---------|---------------------------------------------------------------------|
| `<K>`   | upstream ticket key (the one this ticket waits on)                   |
| `point` | upstream milestone: `design-accepted` \| `integrated` \| `archived` |
| `cond`  | optional condition on the outcome — v1 vocabulary: `passed`          |
| `phase` | the **downstream** phase this edge gates (whose `:work` entry blocks)|

Read `KLC-077@integrated:passed#build` as: *this ticket's `build` phase cannot
start until KLC-077 reaches `integrated`, and only if that point was reached with
no rollback/regression.* Omit `:cond` for an unconditional edge.

An edge blocks **entering `:work`** for the named phase. It is orthogonal to the
phase's own decision/integrate gate — the two never overlap. This skill only
records edges; the actual enforcement lives in KLC-077's `:work` pre-check.

### 4. Create + run

This is the only step that writes anything. Do it in this exact order:

1. **Validate the whole planned set BEFORE creating anything.** Use the helper
   `core/skills/epic_plan.py`. Build a `PlannedTicket(key, description, blocked_by
   =(…edge strings…))` for every ticket — `description` is that ticket's planning
   rationale from step 3 and is REQUIRED (`klc intake` hard-fails without one).
   Then call `epic_plan.create_epic(root, planned, intake_runner=…)`. It runs
   `epic_plan.validate_plan` first, which checks:
   - **cycles** — mutual `blocked_by` where nobody can ever start (the
     plan-set-level check that is genuinely this skill's);
   - **dangling edges** — an `on` that is neither a member of this epic nor an
     existing ticket;
   - **every ticket has a non-empty description** (else intake would reject it
     mid-run and leave a partial epic);
   - **every edge's downstream `#phase` is a real phase** (checked against
     `config/phases.yml`, mirroring what intake enforces — because
     `epic_deps.parse_edge` deliberately does NOT validate the phase, a bad
     `#phase` caught only at the intake call would leave earlier tickets already
     created);
   - the root is a member of the set;
   - per-edge grammar, point/condition vocabulary and self-reference — delegated
     to `epic_deps.parse_edge` (KLC-077), not re-implemented here.

   These whole-set checks MUST run here (and again in `board --epic`) because no
   single `intake` write ever sees the whole graph. If validation fails,
   `create_epic` raises `EpicPlanError` and **creates nothing** — surface every
   problem to the user, fix the plan together, and only then retry. Never create
   tickets from an unvalidated set. This is what protects the no-partial-epic
   guarantee: a partial epic is worse than no epic.

2. **Create each ticket** once validation is clean. `create_epic` calls the
   injected `intake_runner` per ticket; that runner shells out to:

   ```text
   klc intake <KEY> --epic <ROOT> [--blocked-by "<K>@<point>[:cond]#<phase>" …] "<description>"
   ```

   `--epic <ROOT>` sets `meta.epic`; each repeatable `--blocked-by` records one
   edge on the downstream ticket; the trailing `"<description>"` positional is the
   ticket's rationale and is mandatory (intake refuses a description-less ticket
   with rc 2 before writing anything). The root ticket is created with `--epic
   <ROOT>` pointing at itself and no `--blocked-by` (unless it genuinely waits on
   an existing ticket outside the epic).

3. **Write `epic.md`** into the root ticket's dir: `.klc/tickets/<ROOT>/epic.md`
   — the description + scope/boundaries from steps 1 and 2. Write it into the
   root ticket's own subtree: on a feature-ON multi-user machine, ticket state
   lives on the `klc-state` branch and is persisted through the per-ticket
   `state_tx`, which globs the whole `tickets/<ROOT>/` subtree — so `epic.md`
   placed there is swept into shared state by the root ticket's next normal
   lifecycle write (its first `ack`), not lost. Until that first `ack` it is a
   local file only; there is no separate CAS-push for it and none is needed.

4. **Show the ready set** with `board --epic <ROOT>` (the KLC-078 view). It
   renders the computed epic state, each member's phase / blocked-by / holder,
   and the **ready set** — members whose next phase has no unmet dependency and
   is not held by someone else. Point the user at the ready tickets; they drive
   those with `klc run` / `next` / `ack`, and edges unblock downstream as points
   are reached.

## Discipline (do not cross these lines)

- **Orchestrate, do not reimplement.** The schema, the `:work` enforcement, and
  the point→phase-state resolver are KLC-077's; epic state and the ready-set /
  cycle-dangling view are KLC-078's. This skill only holds the conversation,
  validates the planned set once up front, and calls those two surfaces. Do not
  duplicate their logic.
- **Validate before create, always.** A partially-created epic is worse than no
  epic. `create_epic` guarantees the seam is never touched on a bad set — rely on
  it, do not create tickets by hand and validate afterward.
- **Edge syntax is not copied, it is reused.** The grammar + vocab live once, in
  `epic_deps.parse_edge` (KLC-077); both the CLI and `epic_plan.validate_plan`
  call it. Do not add a parallel parser to the skill or to `epic_plan.py`.
- **The CLI boundary is a seam.** `epic_plan.create_epic` takes an
  `intake_runner` so the create step is testable without the real CLI. In the
  live skill that runner runs `klc intake …`; in tests it is stubbed.

## Stop conditions

- Validation fails → surface all problems, fix the plan with the user, retry. Do
  not create anything.
- The user has not agreed on scope (step 2) → do not decompose yet.
- `klc intake` returns non-zero for any ticket → stop, surface stderr verbatim,
  do not continue creating the rest silently.
