# KLC constitution — the principles code and specs must always obey

This is KLC's constitution: a short list of **mandatory, checkable, stable**
principles distilled from our own hard-won lessons. It is deliberately *not* a
style guide and *not* a feature list. Every entry answers one question — "what
must every change to this project always obey?" — and nothing softer. If a rule
is only a "usually" or a preference, it does not belong here.

The constitution is the **anchor for spec review** (epic KLC-082). A spec has no
ground truth for correctness of intent, so the spec layer instead checks what
*is* anchorable — and the first anchor is this document. Downstream, KLC-083's
spec self-check references principles by id, and KLC-084's independent reviewer
loads the whole list as a conformance checklist.

## Two coupled forms

- **This narrative** (`docs/constitution.md`) — the human-readable rationale and
  the evidence in the real code for each principle.
- **The machine form** (`config/constitution.yml`) — one entry per principle:
  `{ id, category, check, statement }`. `core/skills/constitution.py` is the one
  reader that loads it.

The two are kept in **lockstep**: `tests/test_constitution.py` asserts that every
id in the YAML appears as a heading here and vice-versa, so the two forms can
never drift apart.

## How to read each entry

Every principle below is a level-3 heading holding its **stable id** in
backticks, followed by its category, its check type, and the one-line statement
from the YAML, then the rationale and the evidence in the current code.

The **check type** records how conformance is verified:

- `deterministic` — mechanically verifiable. In the machine form each such
  principle carries an executable predicate (`check_target`, `check_command`,
  `check_pattern`/`check_tokens`, `check_expect`) so KLC-083 can run it as a gate
  without reconstructing it from prose. Only **one** principle is deterministic
  today (`klc-state-not-tracked-on-main`); its pattern is a path prefix that is safe
  to ship anywhere. A rule is deterministic here only if its predicate can live and
  run safely on the tree it guards — which is why `public-mirror-no-internal-refs`,
  whose denylist could not, is a `review` principle enforced by origin-side tooling.
- `review` — a judgment call. A human or an LLM reviewer (KLC-084) must assess
  it; there is no mechanical shortcut.

Each entry also carries a **status**: `upheld` (the code satisfies it today) or
`open-gap` (a mandatory target not yet met, which 083 expect-fails or skips rather
than reporting as a permanent false failure). Every principle here is currently
`upheld`.

Labelling a principle `deterministic` does not mean the enforcement engine
exists today. This document ships the **checklist**; building a rule engine is a
later, separate concern. The label only records what *could* be checked
mechanically versus what will always need judgment.

---

## Architecture — the structural invariants

These are the load-bearing shapes of the system. Breaking one does not just add a
bug; it re-opens a class of bugs the current design closed once and for all.

### `single-source-of-truth`

- **category** architecture · **check** review
- There is exactly one resolver, parser, or state machine per concern; a view
  reuses the lifecycle resolvers and never re-derives their logic.

A second implementation of the same concern is the most expensive kind of drift:
the two copies agree today and diverge silently tomorrow. The rule is that a
*view* is a pure consumer of the canonical resolver, never a re-derivation of it.
Evidence: `core/skills/epic_view.py` computes the phase a ticket would enter next
by delegating to `lifecycle.next_work_phase` — the same resolver `klc next`/`ack`
use — precisely so the epic view can never name a phase the real transition would
skip (`epic_view.py:_next_work_entry_phase`). Dependency edges are likewise parsed
once, by `epic_deps.parse_edge`, and reused wherever an edge is read.

### `state-writes-ride-state-tx`

- **category** architecture · **check** review
- Every write to shared klc-state rides the per-ticket state_tx envelope; no verb
  touches git directly and no new coordination primitive is introduced.

Multi-user safety lives in exactly one place. `core/skills/state_tx.py` is the
only component that touches git when the multi-user feature is on: it wraps a
verb's whole mutating body in the `self-heal → pull → body → glob-commit +
CAS-push` cycle exactly once. Because it glob-commits the whole
`tickets/<ticket>/` subtree, no individual mutation site has to remember to stage
its file, and no verb needs its own locking. Adding a second coordination
mechanism — a lock file, a separate commit path, a direct `git` call in a verb —
would defeat the single envelope. New verbs reuse `state_tx`; they do not invent
their own.

### `single-dependency-choke-point`

- **category** architecture · **check** review
- The blocked_by dependency gate is enforced at exactly one choke point
  (enter_work_guard), immediately before a work-entry write and inside state_tx on
  post-pull state.

A dependency ("this phase may not start until an upstream ticket is integrated")
is only sound if it is checked at the exact moment of entry, on synced state, in
one place. `epic_deps.py` states it directly: enforcement is a *single choke
point* — `lifecycle.enter_work_guard` calls `is_blocked` right before any
`:work`-entry write, inside the verb's `state_tx` (post-pull), and raises
`BlockedError` if blocked (`epic_deps.py` module docstring; `lifecycle.py:616`).
Scattering the check across verbs would let one path bypass the gate.

### `degrade-not-fail`

- **category** architecture · **check** review
- Absent or optional context is a clean no-op, never a crash: the feature-off path
  is a pure pass-through, a ticket with no dependency is an untouched guard, and an
  unreadable upstream never crashes the view.

Optional machinery must be invisible when it is off and forgiving when its inputs
are missing. When `state_feature.enabled()` is false, `state_tx` yields `None` and
touches no git at all, so the single-user path is byte-for-byte identical to
having no state machine. A ticket with no `blocked_by` makes `enter_work_guard` a
pure no-op (`lifecycle.py:622`). An upstream ticket that is missing or corrupt is
surfaced as an `EdgeStatus`, never an exception that crashes the epic view or the
`:work` guard (`epic_deps.py`). The absence of context is a clean skip, not a
failure.

### `decide-on-synced-state`

- **category** architecture · **check** review
- Every validation and decision runs against post-pull (synced) state; a decision
  computed before the pull is rejected by the stale-guard rather than applied to
  stale state.

Deciding on stale state is the multi-user footgun. `state_tx` captures the
ticket's committed subtree hash *before* the pull and re-checks it *after*; if the
pull changed the ticket, it raises `StaleStateError` **before** the body runs, so
every verb's pre-transaction validation (scope, gate, pick, `can_complete`,
`--force`) is thrown away rather than applied to state that moved underneath it
(`state_tx.py`, the class-closing stale-guard). No verb path — current or future —
can act on pulled-changed state.

### `epic-is-a-computed-view`

- **category** architecture · **check** review
- An epic is a read-only computed view whose state is a pure function of its member
  phases; it is never stored as a second lifecycle entity.

An epic is not a stored entity and does not have its own lifecycle. Its state is a
pure function of its members' phases (`epic_view.py:epic_state`), recomputed on
read. This is a product decision as much as an architectural one: there is exactly
one lifecycle in the system, the per-ticket one, and everything epic-shaped is a
projection over it. Storing an epic status would create a second source of truth
that could contradict the members — the very thing `single-source-of-truth`
forbids.

---

## Boundary — what must never leak or be overwritten

These principles guard the edges of the system: what may be published, what may be
committed, and what belongs to the user.

### `klc-state-not-tracked-on-main`

- **category** boundary · **check** deterministic · **status** upheld
- Per-project lifecycle state under .klc is never tracked on the code branch; the
  shipped framework tree carries no .klc entries.

The framework ships clean. Per-project runtime state — tickets, indices, reports,
lifecycle bookkeeping — lives under `$PROJECT_ROOT/.klc/`, which `.gitignore`
excludes, and the lifecycle state is carried on its own `klc-state` branch, not on
the code branch. This keeps the shipped tree free of one project's bookkeeping.
Predicate (`check_target: code-branch`):
`git ls-tree -r --name-only HEAD | grep -E "^[.]klc/"` must find nothing (exit 1),
verified today.

### `no-autocommit-of-user-wip`

- **category** boundary · **check** review
- The state machine only ever commits ticket bookkeeping under .klc on the
  klc-state branch; it never stages or commits the user's source working tree.

The state machine's commits are scoped to `tickets/<ticket>/` under `.klc` on the
`klc-state` branch (`state_tx.py`, the glob-commit). It never stages or commits
the user's source changes — the user's work in progress on the code branch is
theirs alone. `state_tx` goes out of its way to *preserve* uncommitted tracked
artifacts across its pull rather than discard them, but it never sweeps the user's
source into a commit they did not ask for.

### `public-mirror-no-internal-refs`

- **category** boundary · **check** review · **status** upheld
- The public mirror carries no internal-only identifier (internal git host or
  corporate email domain) in its content or authorship; its commits are re-authored
  to the public identity, while the origin remote keeps the real history.

The two remotes have different trust levels. The **origin** remote (an internal
host) is the real history and the active development remote; it legitimately carries
the operator's real identity and internal host references. The **public mirror** is
a *re-authored, content-scrubbed* lineage — every commit re-authored to the public
identity, every internal reference removed — so it must stay free of internal-only
identifiers in both content and authorship.

This principle is **review**, not deterministic, on purpose. A mechanical
no-internal-refs gate is real and valuable, but its denylist and its grep **must
live and run origin-side, in the mirror tooling** (the scrub `--replace-text`
denylist plus the verify greps run at mirror time), *not* as a check shipped in the
constitution. A deterministic denylist committed here would defeat itself twice: it
would ship the very internal tokens it names onto the public mirror, and — because
the constitution is itself mirrored — a gh-side grep would find those tokens inside
its own denylist file and self-trip into a permanent false failure. A denylist
cannot safely live on the surface it guards. So the constitution **states** the
invariant; the origin-side tooling **enforces** it. See
`docs/dual-remote-mr-pr-workflow.md` for the publish-and-verify step.

### `divergent-public-mirror`

- **category** boundary · **check** review · **status** upheld
- Review and merge happen on origin (GitLab) via MRs; gh (GitHub) is a clean public
  mirror updated by re-authored force-push with no PRs, so the two mains are
  intentionally divergent lineages, never fast-forward mirrors of each other.

The remote model is asymmetric by design. All review, CI, and merging happen on
**origin** through merge requests — that is where the real, un-scrubbed history
lives. **gh** is not a peer forge you also merge on; it is a downstream **public
mirror** refreshed by a re-authored, scrubbed force-push, with no pull requests. So
the two `main` branches hold the *same content* under *different identity and
history*, and they are **intentionally divergent** — not fast-forwards of one
another. The earlier "merge on one forge, `--ff-only` mirror the other, identical
mains" model is dead: `--ff-only` mirroring cannot survive a re-authored lineage,
and asserting identical mains would directly contradict `public-mirror-no-internal-refs`.
`docs/dual-remote-mr-pr-workflow.md` describes the live workflow.

---

## Process — how work is validated

These principles govern the discipline around a change, not the change itself.

### `branch-first`

- **category** process · **check** review · **status** upheld
- Implementation work happens on a feature branch off main; code changes are never
  committed directly to main, only pure .klc bookkeeping is.

Working on `main` directly makes a change unreviewable and un-revertable in
isolation, and — given `divergent-public-mirror` — entangles it with the mirror
push. The rule (`CLAUDE.md`, "Starting a ticket": *Never work on main directly*) is
that every implementation change is developed on a `feature/<...>` branch off the
latest `main` and lands through a merge request. The one carve-out is pure `.klc`
lifecycle bookkeeping (phase acks, retrospectives), which carries no reviewable code
diff and may be committed on `main` directly. A spec that proposes editing `main`
in place must not pass conformance unchallenged.

### `mandatory-independent-review`

- **category** process · **check** review
- Every M or L change gets a fresh non-fork plus external independent review before
  its review-report, with a scoped re-review of each fix delta.

Internal review suffers from confirmation bias: the implementer validates against
the spec as they understood it, not against the whole codebase, and misses
cross-file gaps and contradictions introduced during the build. The rule
(`CLAUDE.md`, "Mandatory external code review subagent") is a fresh, no-context
reviewer before `review-report.md`, plus a scoped re-review of every fix delta on
M/L so a fix does not silently introduce a new defect. This is the discipline that
KLC-084/085 shift *left* onto the spec.

### `real-substrate-gate-for-coordination`

- **category** process · **check** review
- A coordination or data ticket is gated by a real-substrate fuzz or property test
  over a design-pass envelope, not by an incremental review-and-fix loop.

For tickets that coordinate state (they gate `:work` on the live machine) or move
data, an incremental review-then-fix loop cannot cover the interleavings that
break them. The gate is instead a real-substrate fuzz or property test over a
design-pass envelope — exercise the real concurrency against a real backing store
and let it hunt for the failure. This is why `state_tx` is validated by real
bare-repo integration tests, not only unit tests.

### `tests-verify-real-behavior`

- **category** process · **check** review
- Tests exercise the real emitter, parser, or template on real substrate; they
  never hand-roll a fixture that merely restates the expected output.

A test that hand-rolls the expected output as a fixture proves only that the
fixture matches itself. The KLC-057 lesson is to drive the real emitter, parser,
or template and assert on what it actually produces. `tests/test_state_tx.py`
stubs only the network at the `state_sync` boundary and drives the real envelope,
and it points at `tests/integration/test_klc057_*.py` where the real git behaviour
runs against a real bare repo.

### `rigor-scales-by-track`

- **category** process · **check** review
- Process rigor scales by track: XS is the fast path, and heavier review and gates
  fire on M or L and on escalation signals, never uniformly.

Cost must match risk. The track (XS/S/M/L) is the floor, and signals escalate from
there. XS is the fast path; the external reviewer is default-on for S/M/L and never
reaches XS (`config/reviewers.yml`); heavier gates fire on M/L and on escalation
signals (risk tags, scope expansion, sentinel hits). Applying the same rigor to
every change would tax the trivial ones and starve the risky ones.

---

## Product — the deliberate non-goals

### `no-dependency-on-unmerged-code`

- **category** product · **check** review
- A ticket depends only on integrated (merged) upstreams via blocked_by; it never
  stacks on an unmerged branch.

Dependencies are expressed as per-ticket `blocked_by` edges that clear only when
the upstream reaches **integrated** (see the epic DAG in `docs/epics.md` and the
KLC-082 epic plan: `KLC-083.build ← KLC-082 @ integrated`). A ticket therefore
builds on merged code, never on an unmerged branch stack that could be rebased or
abandoned under it. There is no central dependency manifest; the edges live on the
tickets themselves.

---

## Governance — how this document changes

### `constitution-changes-by-decision`

- **category** governance · **check** review
- This constitution changes only by an explicit, recorded decision; principles stay
  few, mandatory, checkable, and stable.

The constitution is worthless as an anchor if it drifts with every ticket. A
principle is added, removed, or reworded only by an explicit, recorded decision —
not as a side effect of unrelated work. Ids are stable once shipped: downstream
checks reference them, so a rename is a breaking change. Keep the list few: prefer
tightening an existing principle to adding a marginal one.
