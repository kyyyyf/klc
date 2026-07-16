---
ticket: KLC-063
kind: tech
authority: human
last_generated: 2026-07-16T00:00:00Z
risk_tags: [data, migration]
---

# KLC-063 — state init must commit preserved tickets; tx rollback must reset the derived-cache untracking

## Goals

- Close a **preserve-and-commit gap** in `klc state init`: when a project already
  has `.klc/tickets/...` and `state init` binds the `.klc/` worktree to the
  `klc-state` branch, the pre-existing tickets it copies into the worktree must be
  **committed and pushed** on the `klc-state` branch, so a second clone actually
  receives them. Today they are copied but never committed, so init reports
  success while the preserved state stays local-only.
- Close a **rollback contract gap** in `state_tx`: when a CAS push fails on an
  *upgraded* worktree that still tracks the shared derived index
  (`knowledge/tickets-index.jsonl`), the rollback must leave a **clean index** —
  no staged deletion left behind — so the next pull/transaction never starts on a
  dirty index, exactly as the envelope's own docstring promises.
- Keep both fixes **fail-safe and backward-compatible**: single-user (feature-OFF)
  behaviour is byte-for-byte unchanged, and the KLC-053 orphan-create happy path
  (where the derived index is never tracked) does not regress.

## Problem / Context

KLC keeps per-ticket lifecycle state on a `klc-state` **orphan branch** in the
same project repo, materialized as a git worktree at `.klc/` (KLC-053
`klc state init`). `git push` of that branch to `origin` with CAS semantics is the
only coordination primitive; there is no server. Two correctness gaps in that
machinery were flagged by an external reviewer (codex P2 ×2) and a fresh reviewer
(fresh-A LOW). Both concern the *shared, committed* state, so a wrong outcome is a
cross-collaborator data problem, not a local nuisance.

### Gap 1 — init copies preserved tickets but never commits them

FACT: `state.init.run()` does, in order, `backup = _stash_existing(klc, repo)` →
`_add_worktree(repo, klc, remote)` → `_merge_back(backup, klc)`.
src=core/phases/state.py:505-507 verified=2026-07-16

FACT: `_add_worktree` is what commits/pushes the `klc-state` branch — on the
orphan-create path it makes the empty root commit and `git push -u` (state.py:317-321,
331), and on the track-origin path it only checks out an existing tip. By the time
`_merge_back` runs, the branch has already been committed and (if remote) pushed.
src=core/phases/state.py:314-356 verified=2026-07-16

FACT: `_merge_back(backup, klc)` calls `_merge_tree(backup, klc, skip={".git"})`
and then `shutil.rmtree(backup)`. It performs **no** `git add` / `git commit` /
`git push` — the copied files land in the worktree as untracked/uncommitted
content only. src=core/phases/state.py:424-434 verified=2026-07-16

Consequence: after `klc state init` prints success, the preserved
`.klc/tickets/...` are present on disk in the initializing checkout but are **not**
on the `klc-state` branch, so a second clone that runs `klc state init` (tracking
the same `origin/klc-state`) receives an empty (or peer-only) ticket set. Worse,
once another user later creates the *same* ticket paths on the remote, the first
user's next `pull --rebase` in `.klc/` can diverge/conflict against locally
uncommitted files.

FACT: the existing init tests only assert the preserved file is present **in the
local worktree** — `test_state_init_preserves_existing_tickets_orphan`
(state_init.py:142-143) and `test_state_init_tracks_origin_and_preserves_local`
(state_init.py:201-202). Neither commits+pushes and re-clones to prove
propagation, so the gap is currently untested.
src=tests/integration/test_state_init.py:130-203 verified=2026-07-16

### Gap 2 — rollback leaves the derived-cache untracking staged (dirty index)

FACT: `commit_and_push_cas_subtree` builds its index by `git reset -q` (unstage
all) → `git add -A -- tickets/<ticket>/` → `git rm --cached --ignore-unmatch --
<derived pathspecs>`, then commits. The derived pathspecs include the **top-level**
`knowledge/tickets-index.jsonl`, which is OUTSIDE `tickets/<ticket>/`.
src=core/skills/state_sync.py:509-524 verified=2026-07-16

FACT: `_derived_untrack_pathspecs(ticket)` returns
`["knowledge/tickets-index.jsonl", ":(glob)tickets/<t>/**/.lock", ...]` — the first
entry is a shared top-level path, the rest are subtree-scoped.
src=core/skills/state_sync.py:159-172 verified=2026-07-16

FACT: on a push failure the function does `git reset --soft HEAD~1` and re-raises;
a soft reset moves HEAD back but **keeps the index staged**, so the aborted
commit's staged content (including the staged deletion of
`knowledge/tickets-index.jsonl`) remains in the index.
src=core/skills/state_sync.py:542-548 verified=2026-07-16

FACT: the `state_tx` rollback handler then runs
`_restore_subtree(snap, ticket, kdir)` and
`state_sync._git(["reset", "-q", "--", subtree], kdir)` — the index reset is scoped
to `tickets/<ticket>/` ONLY, so it un-stages the subtree but **not** the top-level
`knowledge/tickets-index.jsonl` deletion, which stays STAGED after rollback.
src=core/skills/state_tx.py:134-135 verified=2026-07-16

FACT: the envelope's own contract says the index is reset "so the next pull never
hits a dirty index." A staged top-level deletion left behind contradicts that
contract. src=core/skills/state_tx.py:23-26,128-131 verified=2026-07-16

Scope of impact: this can only happen on an **upgraded** worktree that still tracks
`knowledge/tickets-index.jsonl` from an older layout (the `rm --cached` matches
something). On a KLC-053-created orphan the index was never tracked, so
`--ignore-unmatch` makes the `rm --cached` a no-op and nothing is left staged
(fresh-A confirmed it cannot occur there). It self-heals on the next successful op
and loses no data — but it violates the documented rollback contract on the
upgraded path, and the upgraded-worktree combination is currently untested.

## Acceptance Criteria

1. AC-1 (init commits & pushes preserved tickets): Given a project whose `.klc/`
   contains pre-existing `tickets/...` and `klc state init` binds the `.klc/`
   worktree to `klc-state` (orphan-create OR track-existing-origin path), when
   init completes successfully, then the preserved ticket files are **committed on
   the `klc-state` branch** and (when a remote is configured and reachable)
   **pushed to `origin/klc-state`**, such that a second clone tracking the same
   `origin/klc-state` receives them. Init must not report success while preserved
   ticket state remains uncommitted.

2. AC-2 (init commit is fail-safe, never strands data): Given AC-1, when the
   post-merge commit succeeds but the push fails (offline / auth / permission),
   then init behaves like the existing orphan-push warning path — it warns that
   the state was committed locally but not pushed and still exits 0, and never
   deletes or strands the preserved content. Given there is **nothing to preserve**
   (no `_merge_back` content) OR the merge produced no tracked change, init makes
   no empty commit and its output/exit code are unchanged from today.

3. AC-3 (tx rollback leaves a clean index): Given the state-sync feature is ON and
   a CAS push fails inside `commit_and_push_cas_subtree` on an **upgraded** worktree
   that still tracks `knowledge/tickets-index.jsonl`, when the `state_tx` rollback
   runs, then after rollback the git index is **clean** — no staged deletion of
   `knowledge/tickets-index.jsonl` (nor any other derived pathspec) remains — so a
   subsequent `git pull --rebase` / next transaction does not start on a dirty
   index. The on-disk derived index file itself is untouched (only its *staged*
   removal is undone).

4. AC-4 (no regression to the 053 orphan happy path): Given a KLC-053-created
   orphan worktree where the derived index was never tracked, a failed CAS push
   still rolls back to a clean tree AND clean index (the fix is a no-op there —
   `--ignore-unmatch` never staged anything to un-stage), and the successful-push
   path is unchanged. Any stash-popped edits to *other* tickets remain safe: they
   live in the working tree, not the index, so an unscoped index reset does not
   touch them.

5. AC-5 (feature-OFF parity): When `state_feature.enabled()` is False, `state_tx`
   remains a pure pass-through (no git at all) and both fixes are inert. Every
   existing intake/ack/next and state test still passes.

6. AC-6 (real-substrate tests — per the KLC-057 lesson, not stubs): Add tests that
   exercise the real git substrate (local bare-repo upstream + a real second
   clone), not stubbed git:
   - **(a) two-clone propagation**: `klc state init` on a project with pre-existing
     `.klc/tickets`, then clone `origin` afresh and `state init` the clone (or
     directly inspect `origin/klc-state`) and assert the preserved tickets are
     present on the second side — proving the commit+push of AC-1.
   - **(b) upgraded-worktree rollback**: a worktree that TRACKS
     `knowledge/tickets-index.jsonl` (the currently-untested upgraded combination),
     forced into a CAS push failure, asserting the index is CLEAN after rollback
     (`git status --porcelain` shows no staged `D knowledge/tickets-index.jsonl`).

## Non-goals

- Changing the KLC-053 orphan-bootstrap semantics, the CAS classification/retry
  machinery (`_push_with_cas`), or the stale-guard / preserve-and-pull behaviour of
  `state_tx` beyond the rollback index reset.
- Redefining what counts as a derived cache (`_DERIVED_IGNORES` /
  `_derived_untrack_pathspecs` stay as they are).
- Touching the intake/ack/next verb bodies, holder logic, or Jira deferral.
- Adding any new user-facing vocabulary on the success path (init's success output
  shape is unchanged; only the existing "not pushed" warning may fire — AC-2).

## Constraints

> [!CONSTRAINT C-001] source=core/phases/state.py:508-518
> The init commit must stay inside the existing try/except so a failure during the
> new commit/push step still triggers `_teardown_partial` + `_restore_backup` and
> never strands the preserved backup. A push failure specifically must NOT abort
> init (mirror the orphan-create warn-and-continue at state.py:331-341).

> [!CONSTRAINT C-002] source=core/skills/state_tx.py:23-26
> The rollback must honour the documented contract ("the index is reset so the
> next pull never hits a dirty index"). The fix belongs at the rollback site
> (state_tx.py:135) — either reset the derived pathspecs too, or use an unscoped
> `git reset -q` — not by changing how `commit_and_push_cas_subtree` stages.

> [!CONSTRAINT C-003] source=core/skills/state_sync.py:187-232
> An unscoped index reset is safe: `pull_rebase_preserving` stashes and pops
> *tracked* edits to other tickets into the **working tree**, and the snapshot
> rollback restores this ticket's working tree. Neither depends on staged index
> state, so `git reset -q` (index-only, no `--hard`) cannot destroy another
> ticket's in-progress work.

> [!CONSTRAINT C-004] source=AC-5, core/skills/state_tx.py:85-88
> Fail-safe default: the feature-OFF pass-through path must stay byte-for-byte
> identical (no git). The rollback change lives on the feature-ON branch only.

## Affected modules

- core/phases: `state.init` — `_merge_back` (and/or `run`) must commit the
  preserved subtree and push it, fail-safe, inside the existing try/except.
  src=core/phases/state.py:424-434,505-518
- core/skills: `state_tx` — rollback index reset must also clear the staged
  derived-cache untracking (state_tx.py:135). `state_sync` is read for the
  derived-pathspec list and the `_git` helper; no change to its staging logic is
  required by the chosen approach. src=core/skills/state_tx.py:134-135,
  core/skills/state_sync.py:159-172,509-548
- tests: add the two real-substrate tests (AC-6) alongside the existing
  `test_state_init.py` and `test_klc057_hardening.py` bare-repo fixtures.
  src=tests/integration/test_state_init.py, tests/integration/test_klc057_hardening.py:63-107

## Open questions

> [!QUESTION Q-001] blocks=design — RESOLVED
> Rollback fix shape: reset the derived pathspecs explicitly vs. unscoped
> `git reset -q`. Resolved in design toward the **unscoped `git reset -q`** as the
> primary candidate — it is the smallest, most future-proof change (any
> not-yet-enumerated top-level staged path is also cleared) and is proven safe by
> C-003. The explicit-pathspec variant is kept as the conservative fallback in
> design/options.md. Final selection is the design ack pick.

> [!QUESTION Q-002] blocks=design — RESOLVED
> Where to place the init commit: inside `_merge_back` vs. in `run()` after
> `_merge_back`. Resolved toward a dedicated `_commit_preserved(...)` helper called
> from `run()` right after `_merge_back` and still inside the try/except, so
> `_merge_back` stays a pure filesystem merge and the git step (add/commit/push) is
> testable and fail-safe in isolation. Detail in design/options.md.

## Estimate

- complexity: 2  (two independent correctness fixes in the shared-state git
  machinery; init must add a fail-safe commit+push step with the same teardown
  guarantees, and the rollback change must not disturb other-ticket working-tree
  safety — more than a one-liner, but localized and non-architectural)
- uncertainty: 1  (both bugs are precisely diagnosed with line-level evidence and a
  named fix direction; the real-substrate fixtures already exist to prove them)
- risk: 2  (writes to the shared `klc-state` branch across collaborators; a wrong
  commit/push or a wrong index reset can leave inconsistent shared state or lose an
  edit — risk_tags: data, migration — though both are fail-safe-off by default)
- manual: 1  (fully autotestable via bare-repo + second-clone fixtures; light
  manual sanity of a real two-user init is optional)
- total: 6
- track: M

blast-radius: unavailable — `.klc/index/modules.json` carries no dependency edges
(`depends_on`/`depended_by` null for every module, as recorded for the sibling
KLC-057). Per the hard rule the `route_hint` floor (M) is held, not downgraded; the
score independently lands at M (total=6). These files are the shared-state spine of
the multi-user machinery, so conservative scoring is warranted.

## Approaches (shortlist — detail in design/options.md)

- Option A — **Minimal, targeted**: (init) add a small `_commit_preserved` helper
  called from `run()` after `_merge_back` that `git add`/commits the worktree and
  reuses the orphan-create push+warn tail; (rollback) extend state_tx.py:135 to
  also reset the derived pathspecs. Smallest surface, but the rollback still lists
  the derived paths in two places.
- Option B — **Clean / future-proof**: same init helper as A, but (rollback)
  replace the subtree-scoped reset with an **unscoped `git reset -q`** so any
  top-level staged residue (present or future) is cleared, justified safe by C-003.
  One obvious rollback line, no path list to keep in sync.
- Option C — **Push-side fix**: change `commit_and_push_cas_subtree` so the
  `reset --soft` unwind also un-stages the derived removal at the source. Rejected
  in shortlist: the docstring locates the rollback guarantee at the envelope
  (C-002), and moving it into the push helper splits the contract across two files.

Picked: Option B — the unscoped `git reset -q` is the smallest, most robust
rollback fix and removes the second copy of the derived path list, while the init
commit helper is identical to A. Safe per C-003 (other-ticket edits are
working-tree, not index).
