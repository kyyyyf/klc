---
ticket: KLC-057
kind: tech
authority: human
last_generated: 2026-06-27T08:15:34Z
risk_tags: [data, migration]
---

# KLC-057 — Wire sync + holder into intake/ack/next (uniqueness, holder lifecycle)

## Goals

- Make the multi-user state-sync behaviour **unobtrusive**: a user runs the
  existing verbs (`klc intake`, `klc ack`, `klc next`) exactly as today and
  never learns that `.klc/` is a git worktree bound to a `klc-state` orphan
  branch in the same project repo. All pull/push/holder mechanics live
  **inside** the verbs.
- Enforce **key uniqueness** at intake across collaborators using git-CAS
  push (non-fast-forward rejection) as the coordination primitive — a key
  already created by someone else fails with a clear "already taken" message,
  with no local ticket dir left behind.
- Establish the **holder lifecycle** on the work verbs: `intake` acquires the
  holder for the new ticket's first phase; `ack` releases the holder on a
  successful forward transition; `next` / start-of-work first-grabs the free
  phase it is about to enter.
- Keep every change **fail-safe and backward-compatible**: when the state-sync
  feature is not configured (single-user: `.klc/` is a plain directory, not a
  `klc-state` worktree), the verbs behave exactly as they do today (no pull, no
  push, no holder).

## Problem / Context

KLC is being extended for multi-user collaboration (sibling tickets KLC-053..060).
The chosen architecture has **no dedicated server**: ticket lifecycle state lives
in the same project repo on a `klc-state` **orphan branch** (empty root, history
disjoint from `main`), materialized as a git **worktree** at `.klc/` (KLC-053
`klc state init`). `git push` of the `klc-state` branch to the project's normal
`origin` with CAS semantics (non-fast-forward rejection) is the *only*
coordination primitive. There is no separate state repo and no git remote named
`klc-state`. Identity comes from `git config user.email`; there is no registry and
no forge API. State is partitioned per-ticket, so each ticket is single-writer and
conflict-free; the board is derived from per-ticket `meta.json`.

This ticket is the **integration spine**: it wraps the three lifecycle verbs so
that the primitives delivered by its dependencies become live behaviour:

- KLC-054 — `state_sync` git-CAS primitive: `pull_rebase()` +
  `commit_and_push_cas(paths, msg)` (pushes the `klc-state` branch to `origin`).
- KLC-055 — `identity.current` from `git config user.email`.
- KLC-056 — phase holder model: `acquire` / `release` pure logic.

FACT: the three verbs are independent Python modules dispatched by the CLI —
`klc intake|ack|next` route through `_run_phase` to
`core/phases/{intake,ack,next}.py`. src=scripts/klc:90-93,123 verified=2026-06-27

FACT: the dependency primitives do **not** yet exist in the tree — no module or
symbol named `state_sync`, `acquire_holder`, `release_holder`,
`commit_and_push_cas`, `pull_rebase`, or `identity.current` is present in
`core/skills/` or `core/phases/`. src=grep over core/,scripts/ (no matches)
verified=2026-06-27

ASSUMPTION: KLC-054/055/056 land before this ticket's build, exposing importable
skills (working names `state_sync`, `identity`, `holder`) with the functions
named in the operator brief. if-false=this ticket is blocked at build; the wiring
contract here is the consumer spec those tickets must satisfy, so it is still the
right place to pin the integration points. Tracked as Q-001/Q-002.

FACT: an integration precedent already exists — `klc ack --auto` weaves the
KLC-045 gate-policy skill into the ack verb by importing it and calling
`gate_policy.collect_signals(...)` / `gate_policy.evaluate(...)` inside `run()`.
src=core/phases/ack.py:24,170-191 verified=2026-06-27 — this ticket follows the
same "import a skill, call it inside the verb" shape.

## Acceptance Criteria

1. AC-1 (intake uniqueness — happy path): Given the state-sync feature is
   configured and key `K` is free, when a user runs `klc intake K "..."`, then
   the verb performs `pull_rebase` first, creates the ticket locally, and the
   creation is persisted to the `klc-state` branch on `origin` via a CAS push
   that succeeds; `INTAKE_OK K` is printed and exit code is 0.

2. AC-2 (intake uniqueness — taken key): Given key `K` was already created by
   another collaborator (their meta for `K` is on the `klc-state` branch), when a user
   runs `klc intake K "..."`, then the CAS push for `K` is rejected
   (non-fast-forward), the command exits non-zero with a message that names `K`
   as **already taken**, and **no partial local artifacts for `K` remain**
   (no `meta.json`, no orphan entry appended to the global tickets index).

3. AC-3 (intake acquires holder): Given AC-1 succeeded, when intake completes,
   then the new ticket's first phase records the current user (from
   `identity.current`, i.e. `git config user.email`) as its **holder** in
   `meta.json`, and that holder assignment is included in the same CAS-pushed
   state.

4. AC-4 (ack releases holder on forward transition): Given the current user
   holds phase `P` of ticket `K` and `klc ack K` advances to the next phase,
   when ack completes, then the verb has run `pull_rebase` → existing
   validation/gate-policy → phase advance → **release of the holder for `P`** →
   CAS push, and the released holder is reflected in `meta.json`.

5. AC-5 (ack ordering & atomicity): Given a successful `klc ack`, then the
   release-holder step happens **after** the phase advance and **before** the
   push, so a single CAS push carries both the advance and the release; if the
   CAS push is rejected, the command exits non-zero and reports a concurrent
   update without having advanced the *remote* phase.

6. AC-6 (next / start-of-work first-grab): Given ticket `K` is at `<P>:ack`
   with phase `P+1` free (no holder), when a user runs `klc next K`, then after
   `pull_rebase` the verb advances to `<P+1>:work` and **first-grabs** `P+1` —
   the current user becomes its holder — and the grab is CAS-pushed. If `P+1` is
   already held by another user, the verb reports it as taken and does not steal
   it (stealing is KLC-058's concern, out of scope here).

7. AC-7 (hidden from the user): None of the three verbs print state-branch,
   worktree, push, or git-internals language on the success path; existing human-facing
   output (e.g. `INTAKE_OK`, `→ <state>`, prompt-card hints) is unchanged in
   shape. The only new user-visible text is on the *failure* paths (key already
   taken; phase held by someone else; concurrent update — retry).

8. AC-8 (feature-off backward compatibility): Given the state-sync feature is
   **not** configured (`.klc/` is a plain directory, not a git worktree bound to
   the `klc-state` branch), when any of the three verbs runs, then behaviour is
   byte-for-byte identical to today — no pull, no push, no holder fields written —
   and all existing intake/ack/next tests still pass.

9. AC-9 (per-ticket lock preserved): The new sync/holder logic runs **inside**
   the existing `acquire_lock(ticket)` critical section in `ack`/`next` (and an
   equivalent guard for `intake`), so local concurrent `next`/`ack` cannot
   interleave with the remote sync. src=core/phases/ack.py:64,
   core/phases/next.py:46 verified=2026-06-27

10. AC-10 (tests): Add integration tests under `tests/integration/` that cover:
    intake-taken-key rollback (AC-2), intake-acquires-holder (AC-3),
    ack-releases-holder ordering (AC-4/AC-5), next-first-grab and
    held-by-other (AC-6), and feature-off no-op (AC-8). The git-CAS layer is
    exercised through a local bare-repo fixture or a stubbed `state_sync` that
    simulates non-fast-forward rejection; tests must not require a network push.

## Non-goals

- Implementing the git-CAS transaction primitive itself (KLC-054), the identity
  resolver (KLC-055), or the holder pure-logic model (KLC-056) — this ticket
  **consumes** them.
- Heartbeat / stale-holder stealing (KLC-058), `klc remind` + hooks (KLC-059),
  and `klc board` holder display (KLC-060).
- State worktree / orphan-branch bootstrap (`klc state init`, KLC-053).
- Any user-facing surfacing of the `klc-state` branch, a registry, or a forge API.
- Changing the phase state machine semantics in `phases.yml` (advance/skip/pick
  rules are unchanged; only the verbs' wrapping is new).

## Constraints

> [!CONSTRAINT C-001] source=operator-brief
> No dedicated server. The **only** coordination primitive is git push with CAS
> (non-fast-forward rejection). Uniqueness and holder claims must be expressed
> as CAS pushes, not as queries against a service.

> [!CONSTRAINT C-002] source=operator-brief
> The `klc-state` branch / worktree is **invisible** to the user. Verbs must not
> teach the user about `klc-state`. New vocabulary is allowed only on failure paths.

> [!CONSTRAINT C-003] source=operator-brief + core/phases/ack.py:64
> State is single-writer-per-ticket. Remote sync must run inside the per-ticket
> lock so it composes with the existing local lock; no shared hot files (the
> board stays derived from per-ticket meta).

> [!CONSTRAINT C-004] source=AC-8
> Fail-safe default: when the feature is unconfigured, the verbs must be exact
> no-ops with respect to sync/holder. Existing single-user workflows and tests
> must not regress.

> [!CONSTRAINT C-005] source=core/phases/ack.py:24,170-191
> Reuse, don't replace, the existing gate-policy (KLC-045) validation already in
> `ack`. The release+push wrapping composes around it.

## Affected modules

- intake: wrap `run()` with pull → uniqueness-via-CAS → create → acquire_holder
  → push; roll back local artifacts when the CAS push is rejected (taken key).
  src=core/phases/intake.py:129-260
- ack: wrap `run()` with pull → (existing validate / gate-policy) → advance →
  release_holder → push; ordering per AC-5. src=core/phases/ack.py:49-220
- core/phases: home of the three verb modules being wired (intake/ack/next).
  Note: `next` lives at core/phases/next.py and is part of this scope even
  though "next" is not a distinct module name in modules.json — it is covered
  by the `core/phases` module entry. src=core/phases/next.py:35-109
- core/skills: the consumer-side integration glue (importing/calling the new
  `state_sync` / `identity` / `holder` skills delivered by KLC-054/055/056)
  and the place a thin "is the feature configured?" helper would live.

(All four names are members of modules.json. The `next` verb is intentionally
folded into `core/phases` rather than introduced as a new module ref.)

## Approaches (shortlist — detail in design/options.md)

- Option A — **Inline wrapping inside each verb's `run()`**: call
  `state_sync` / `holder` / `identity` directly at the right points in each of
  the three files, mirroring how `ack --auto` already inlines gate-policy.
- Option B — **A shared `transaction` wrapper / decorator** that does
  pull → <body> → push (with rollback) once, and each verb supplies its body.
- Option C — **Event hooks on the lifecycle layer** (`set_state` /
  `apply_ack` in `core/skills/lifecycle.py`) that fire acquire/release/push so
  the verbs stay untouched.

Picked: Option B — a shared `transaction` wrapper — because the
pull→body→push-with-rollback envelope is identical across all three verbs, the
CAS-rejection rollback logic is the riskiest part and must not be copy-pasted
three times, and the wrapper gives one obvious seam to make the whole thing a
no-op when the feature is off (C-004). Each verb keeps its own body (uniqueness
for intake, validate+advance+release for ack, first-grab for next) so behaviour
stays explicit and the per-verb diffs stay small. Option A was rejected for
triplicating the fragile rollback path; Option C was rejected because hiding
network I/O inside `set_state` makes the lifecycle layer non-deterministic and
hard to keep a pure no-op for single-user mode and existing tests.

## Open questions

> [!QUESTION Q-001] blocks=design
> Exact import surface of the dependency skills is not yet in the tree
> (KLC-054/055/056 unbuilt). Design must pin module + function names:
> `state_sync.pull_rebase()` / `state_sync.commit_and_push_cas()`,
> `identity.current()`, `holder.acquire()` / `holder.release()`, and their
> return/raise contract (esp. how a non-fast-forward rejection is signalled —
> exception type vs. return code). Resolve by reading the sibling specs or
> defining the contract here and treating siblings as obligated to match.

> [!QUESTION Q-002] blocks=design
> Where does holder state live in `meta.json`? The operator brief says "current
> phase has a single `holder`". Design must fix the schema (e.g.
> `meta.holder = "<email>"` for the current phase, vs. a per-phase map) and how
> `release` clears it, so the board (KLC-060) and heartbeat (KLC-058) can read
> a stable shape. This couples to KLC-056's pure-logic model.

> [!QUESTION Q-003] blocks=design — RESOLVED (D-004)
> Feature-detection mechanism for C-004/AC-8. Resolved: the feature is ON iff
> `.klc/` is a git **worktree bound to the `klc-state` branch** — detected by
> `git -C <klc_dir> symbolic-ref --short HEAD` == `klc-state` (equivalently
> `git worktree list` shows `.klc` on `klc-state`, or the `klc-state` branch
> exists). It is **not** gated by a remote named `klc-state` (there is none) and
> needs no separate config flag. KLC-053 `klc state init` is what creates the
> orphan branch + worktree, so the worktree binding is the single source of
> truth. `state_feature.enabled()` owns the check; `state_tx` short-circuits to a
> no-op when it returns False.

> [!QUESTION Q-004] blocks=design
> Intake rollback granularity (AC-2): intake currently appends to the
> append-only global tickets index (src=core/phases/intake.py:232-241) and
> writes meta.json + raw.md *before* any push. Design must decide whether to (a)
> build state locally then push and roll back all of it on rejection, or (b)
> CAS-push a uniqueness claim *first* and only materialise local artifacts after
> it succeeds. (b) is cleaner for "no partial artifacts" but changes intake's
> current write ordering.

## Estimate

- complexity: 2  (three verbs, ordering-sensitive transaction envelope, rollback;
  not cross-architecture but more than a localized change)
- uncertainty: 2  (dependency primitives KLC-054/055/056 are unbuilt; contracts
  must be pinned in design — Q-001..Q-004)
- risk: 2  (klc-state branch writes are data operations across collaborators; a wrong
  rollback or ordering can leave inconsistent shared state — risk_tags: data,
  migration; but it is fail-safe-off by default)
- manual: 1  (mostly autotestable via a local bare-repo / stubbed-CAS fixture;
  light manual sanity of the real multi-collaborator flow)
- total: 7
- track: M

blast-radius: unavailable — modules.json carries no dependency edges
(`depends_on`/`depended_by` are null for every module, including intake/ack/
core/phases/core/skills). src=.klc/index/modules.json verified=2026-06-27.
Per the hard rule, the route_hint floor (S) is held and not downgraded; the
score independently lands at M (total=7), which is at/above the floor, so this
is an upgrade justified by integration breadth, not a downgrade. The verbs are
the universal entrypoints of the whole lifecycle, so conservative scoring is
warranted even without an explicit reverse-edge count.
