---
ticket: KLC-063
last_generated: 2026-07-16T00:00:00Z
---

# Design options — KLC-063

Two independent, small correctness fixes in the shared-state git machinery:
**(1)** `klc state init` must commit+push preserved tickets; **(2)** `state_tx`
rollback must leave a clean index on the upgraded-worktree path. The options
below differ only in the *shape* of fix (2) and where fix (1)'s git step lives;
the behavioural target is identical across A/B/C.

## Dependency impact

dependency-impact: unavailable — `.klc/index/depgraph.json` is absent, so
module/file import edges cannot be read. Fallback: direct call-site inspection of
the three touched files (done during discovery).

- **`core/phases/state.py`** — `run()` is the only caller of `_merge_back`
  (state.py:507) and of the orphan-push tail (state.py:325-356). The new commit
  step is called only from `run()`; no other module imports these private
  helpers. src=core/phases/state.py:437-521 verified=2026-07-16
- **`core/skills/state_tx.py`** — the rollback block (state_tx.py:124-136) runs
  only on the feature-ON exception path; `state_tx()` is the public entry consumed
  by intake/ack/next via the transaction envelope. The change touches one line
  (the index-reset call), adds no new edge. src=core/skills/state_tx.py:83-138
  verified=2026-07-16
- **`core/skills/state_sync.py`** — read-only for this ticket:
  `_derived_untrack_pathspecs` (159-172) and the `_git` helper (89) are referenced
  but their logic is unchanged. No option alters the push-side staging.
- No cross-module edge is added or inverted. No public-API surface changes.

## Option A — Minimal diff (recommended: false)

- **Summary**: (init) add `_commit_preserved(repo, klc, remote)` called from
  `run()` right after `_merge_back`, doing `git add -A` + commit + reuse the
  existing orphan push+warn tail; (rollback) extend `state_tx.py:135` to reset the
  subtree **and** the derived pathspecs explicitly:
  `_git(["reset","-q","--", subtree, *state_sync._derived_untrack_pathspecs(ticket)], kdir)`.
- **Trade-off**: smallest possible diff, but the derived-pathspec list now lives in
  two places (the push-side staging and the rollback), so a future addition to
  `_DERIVED_IGNORES` must be mirrored or the dirty-index bug silently returns.
- **Affected files**: `core/phases/state.py`, `core/skills/state_tx.py`,
  `tests/integration/test_state_init.py`, `tests/integration/test_klc057_hardening.py`.
- **Affected public APIs**: none (new helper is private).
- **New dependencies**: none.
- **Risks**: the duplicated pathspec list drifts; a top-level derived path added
  later but not to the rollback list re-opens the exact bug this ticket closes.
- **Rollout**: immediate; fail-safe-off (feature-OFF path untouched).
- **Estimate**: S (~2-3h incl. tests).

## Option B — Clean / future-proof (recommended: true)

- **Summary**: (init) identical `_commit_preserved` helper as A; (rollback)
  replace the subtree-scoped reset at `state_tx.py:135` with an **unscoped**
  `state_sync._git(["reset", "-q"], kdir)` so the index is fully un-staged after
  the working-tree snapshot restore — any top-level derived residue (present or
  future) is cleared with no path list to maintain.
- **Trade-off**: one obvious rollback line and no duplicated pathspec list; the
  only thing to justify is that an unscoped index reset is safe, which C-003
  establishes (other-ticket edits are working-tree, not index).
- **Affected files**: `core/phases/state.py`, `core/skills/state_tx.py`,
  `tests/integration/test_state_init.py`, `tests/integration/test_klc057_hardening.py`.
- **Affected public APIs**: none.
- **New dependencies**: none.
- **Risks**: an unscoped `git reset -q` (index-only, NOT `--hard`) unstages
  everything; must confirm no code path relies on staged index state surviving the
  rollback. Verified: `_restore_subtree` restores this ticket's working tree, and
  `pull_rebase_preserving` pops other-ticket edits into the **working tree**, so
  neither depends on the index. src=core/skills/state_tx.py:67-81,
  core/skills/state_sync.py:187-232 verified=2026-07-16
- **Rollout**: immediate; fail-safe-off.
- **Estimate**: S (~2-3h incl. tests).

## Option C — Push-side fix (recommended: false)

- **Summary**: (init) same helper as A/B; (rollback) leave `state_tx.py:135`
  untouched and instead change `commit_and_push_cas_subtree`'s `reset --soft`
  unwind (state_sync.py:547) to follow with an index reset that clears the derived
  removal at the source.
- **Trade-off**: keeps the reset next to the code that staged the removal, but
  splits the rollback contract across two files and two functions.
- **Affected files**: `core/phases/state.py`, `core/skills/state_sync.py`,
  `tests/...`.
- **Affected public APIs**: none.
- **New dependencies**: none.
- **Risks**: the envelope docstring locates the rollback guarantee at
  `state_tx` (C-002); moving it into the push helper means two places now claim to
  own "clean index after rollback", inviting future contradiction. Also
  `commit_and_push_cas` (the non-subtree sibling, state_sync.py:461) would need the
  same treatment to stay consistent, widening scope.
- **Rollout**: immediate.
- **Estimate**: S-M.

## Decisions

> [!DECISION D-001]
> Init commit lives in a dedicated private `_commit_preserved(repo, klc, remote)`
> helper called from `run()` after `_merge_back`, inside the existing try/except
> (C-001), rather than inside `_merge_back` — keeps `_merge_back` a pure filesystem
> merge and makes the git step testable and fail-safe in isolation.

> [!DECISION D-002]
> Rollback fix uses an unscoped `git reset -q` (Option B) over the explicit-
> pathspec variant (Option A). Justification: it is the smallest robust change and
> removes the second copy of the derived path list; safe per C-003.

> [!DECISION D-003]
> The init commit is skipped when there is nothing to commit (no preserved content,
> or the merge produced no tracked change) so init never creates an empty commit
> and its output/exit code stay unchanged on the no-preserve path (AC-2).

> [!FACT F-001] src=core/phases/state.py:325-356 verified=2026-07-16
> The orphan-create path already implements the exact commit→push→warn-on-failure
> pattern the preserved-commit step must reuse (push refspec branch-qualified;
> push failure warns and exits 0). `_commit_preserved` follows this shape.

## ADR trigger

ADR_NEEDED=no

Rationale: no public-API change, no new external dependency, no cross-module
boundary crossed, no new/inverted dependency edge. The change is a correctness fix
to *existing* persistence behaviour (init already writes the klc-state branch; this
makes the preserved-ticket write actually durable) — it introduces no new data
schema and no new persistence format, so the schema/persistence ADR trigger does
not fire. The cleaner option (B) is the one picked, so "cleaner option rejected for
pragmatic reasons" does not apply.

<!-- BEGIN: manual -->
<!-- Human additions / revise-impl-plan feedback -->
<!-- END: manual -->
