---
ticket: KLC-063
last_generated: 2026-07-16T00:00:00Z
design_choice: option-B-clean
---

# Implementation plan — KLC-063

Chosen option: **B — Clean / future-proof**. Two independent correctness fixes.
Step order: the isolated tx-rollback fix first (de-risks the transaction path and
is self-contained), then the init commit+push, then the init fail-safe hardening.

Build status: all three steps done (RED+GREEN committed in TDD order).

> [!DECISION D-004] owner=impl-agent date=2026-07-16 refs=step-2,step-3
> The plan's step-2 sketch already showed the fail-safe (`check=False` + warn)
> push. To give step-3 a genuine failing RED, step-2 delivered the happy
> commit+push plus the no-empty-commit guard, and the push fail-safe (warn +
> exit 0) landed in step-3. The final code is identical to the plan; only the
> RED/GREEN boundary shifted.

## step-1 [x] — tx rollback leaves a clean index (unscoped reset)

- **Goal**: On the feature-ON rollback path, un-stage the WHOLE index (not just
  `tickets/<ticket>/`) so a failed CAS push on an upgraded worktree that tracks
  `knowledge/tickets-index.jsonl` leaves no staged top-level deletion behind.
- **RED**: `tests/integration/test_klc057_hardening.py::test_upgraded_worktree_rollback_leaves_clean_index`
  — build a `.klc/` worktree that TRACKS `knowledge/tickets-index.jsonl`
  (commit+push it via the fixture), force a CAS push failure, and assert
  `git status --porcelain` shows no `D  knowledge/tickets-index.jsonl` after
  rollback. Fails today because `state_tx.py:135` resets only the subtree. Backs
  test-plan AC-3 / AC-6b.
- **GREEN**: replace the subtree-scoped reset with an unscoped index reset.
- **VERIFY**: `python3 -m pytest tests/integration/test_klc057_hardening.py::test_upgraded_worktree_rollback_leaves_clean_index tests/integration/test_klc057_hardening.py::test_orphan_worktree_rollback_still_clean_index -q`
- **Expected**: `2 passed`
- **COMMIT**: `KLC-063 step-1: tx rollback resets the full index (clean index on upgraded worktree)`
- **Affected files**: `core/skills/state_tx.py`, `tests/integration/test_klc057_hardening.py`
- **Interfaces**: none (internal behaviour of `state_tx.state_tx` rollback block).
- **Depends on**: none.
- **Code sketch**:
  ```python
  # core/skills/state_tx.py — rollback block (was: reset -q -- <subtree> only)
  _restore_subtree(snap, ticket, kdir)
  # Unscoped index reset: commit_and_push_cas_subtree stages a top-level
  # `rm --cached knowledge/tickets-index.jsonl` (outside tickets/<ticket>/) and
  # its reset --soft leaves it staged. A subtree-scoped reset misses it, leaving a
  # dirty index. Reset the whole index — safe because stash-popped other-ticket
  # edits and the snapshot restore live in the WORKING TREE, not the index (C-003).
  state_sync._git(["reset", "-q"], kdir)
  raise
  ```
- **Rollback note**: if any future code relied on staged index state surviving a
  rolled-back tx it would break — none does (verified: `_restore_subtree` and
  `pull_rebase_preserving` operate on the working tree).

**Tests:**
| Test type | Test name / location | Target symbol(s) | Notes |
|-----------|----------------------|------------------|-------|
| integration | tests/integration/test_klc057_hardening.py::test_upgraded_worktree_rollback_leaves_clean_index | `state_tx.state_tx` | AC-3 / AC-6b; real bare-repo, index tracks the derived cache, forced push failure |
| integration | tests/integration/test_klc057_hardening.py::test_orphan_worktree_rollback_still_clean_index | `state_tx.state_tx` | AC-4 regression; 053-orphan (index never tracked) stays clean — fix is a no-op |
| integration | tests/integration/test_klc057_hardening.py::test_other_ticket_dirty_edit_is_not_destroyed (existing) | `state_tx.state_tx` | AC-4; unscoped index reset must not touch another ticket's working-tree edit |

## step-2 [x] — state init commits & pushes preserved tickets

- **Goal**: After `_merge_back` copies pre-existing preserved tickets into the
  `klc-state` worktree, commit them on `klc-state` and push to `origin` so a
  second clone receives them.
- **RED**: `tests/integration/test_state_init.py::test_state_init_commits_and_pushes_preserved_tickets`
  — run `klc state init` in a repo with a pre-existing `.klc/tickets/local.txt`
  against a real bare `origin`, then assert the file is on `origin/klc-state`
  (`git show origin/klc-state:tickets/local.txt`) and a fresh second clone sees it.
  Fails today because `_merge_back` never commits. Backs test-plan AC-1 / AC-6a.
- **GREEN**: add `_commit_preserved(repo, klc, remote)` and call it from `run()`
  immediately after `_merge_back`, inside the existing try/except; reuse the
  orphan-create commit→push→warn tail.
- **VERIFY**: `python3 -m pytest tests/integration/test_state_init.py::test_state_init_commits_and_pushes_preserved_tickets -q`
- **Expected**: `1 passed`
- **COMMIT**: `KLC-063 step-2: state init commits and pushes preserved tickets`
- **Affected files**: `core/phases/state.py`, `tests/integration/test_state_init.py`
- **Interfaces**: `def _commit_preserved(repo: Path, klc: Path, remote: str) -> None`
  (new private helper in `core/phases/state.py`).
- **Depends on**: none.
- **Code sketch**:
  ```python
  # core/phases/state.py
  def _commit_preserved(repo: Path, klc: Path, remote: str) -> None:
      """Commit tickets merged back into the worktree and push (fail-safe)."""
      _git(["add", "-A"], klc)
      staged = _git(["diff", "--cached", "--quiet"], klc, check=False)
      if staged.returncode == 0:
          return  # nothing preserved / no tracked change -> no empty commit (D-003)
      _git(["-c", "user.name=klc", "-c", "user.email=klc@localhost",
            "commit", "-m", "klc-state: preserve pre-existing tickets"], klc)
      if _remote_is_configured(repo, remote):
          push_refspec = f"refs/heads/{STATE_BRANCH}:refs/heads/{STATE_BRANCH}"
          pushed = _git(["push", remote, push_refspec], klc, check=False)
          if pushed.returncode != 0:
              sys.stderr.write("klc state: warning: preserved tickets committed "
                               "locally but not pushed to the remote\n")

  # in run(), inside the existing try:
  _merge_back(backup, klc)
  _commit_preserved(repo, klc, remote)
  ```
- **Rollback note**: the commit step is inside the existing try/except so a commit
  failure still triggers `_teardown_partial` + `_restore_backup` (C-001).

**Tests:**
| Test type | Test name / location | Target symbol(s) | Notes |
|-----------|----------------------|------------------|-------|
| integration | tests/integration/test_state_init.py::test_state_init_commits_and_pushes_preserved_tickets | `state._commit_preserved`, `state.run` | AC-1 / AC-6a; real bare `origin` + second clone; covers orphan-create and track-origin paths |

## step-3 [x] — init preserved-commit is fail-safe (no empty commit; push-fail warns)

- **Goal**: Guarantee the preserved-commit step is fail-safe — no empty commit when
  there is nothing to preserve, and a push failure warns and still exits 0 without
  stranding data.
- **RED**: `tests/integration/test_state_init.py::test_state_init_no_preserved_content_makes_no_empty_commit`
  (assert `klc-state` still has exactly one root commit after init on an empty
  `.klc/`) and `::test_state_init_preserved_commit_pushfail_warns_exit0` (monkeypatch
  the push to fail; assert exit 0, warning on stderr, file committed locally). Backs
  test-plan AC-2.
- **GREEN**: ensure `_commit_preserved` short-circuits on `diff --cached --quiet`
  (no empty commit) and swallows push failure with a warning (from step-2 sketch);
  add the assertions and tighten the helper if a test bites.
- **VERIFY**: `python3 -m pytest tests/integration/test_state_init.py -q`
- **Expected**: all tests in the file pass (existing + the 3 new)
- **COMMIT**: `KLC-063 step-3: init preserved-commit fail-safe (no empty commit, push-fail warns)`
- **Affected files**: `core/phases/state.py`, `tests/integration/test_state_init.py`
- **Interfaces**: none (refines the step-2 helper).
- **Depends on**: step-2.
- **Code sketch**:
  ```python
  # guard already in _commit_preserved (step-2): the early return on
  # `git diff --cached --quiet` (rc==0 => no staged change) prevents an empty
  # commit; the push-failure branch warns and returns without raising so run()
  # reaches its success print statement and exit 0 (mirrors state.py:331-341).
  ```
- **Rollback note**: none (hardening of an already-guarded helper).

**Tests:**
| Test type | Test name / location | Target symbol(s) | Notes |
|-----------|----------------------|------------------|-------|
| integration | tests/integration/test_state_init.py::test_state_init_no_preserved_content_makes_no_empty_commit | `state._commit_preserved` | AC-2; empty `.klc/` -> klc-state keeps a single root commit |
| integration | tests/integration/test_state_init.py::test_state_init_preserved_commit_pushfail_warns_exit0 | `state._commit_preserved`, `state.run` | AC-2; push monkeypatched to fail -> exit 0 + warning, data committed locally, backup not stranded |
| unit | tests/test_state_tx.py::test_noop_when_feature_off (existing) | `state_tx.state_tx` | AC-5; feature-OFF stays a pure pass-through after the step-1 change |
