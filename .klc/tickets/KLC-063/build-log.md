# Build log — KLC-063

## Step 1 — 2026-07-16 (RED)
**Attempt**: add `test_upgraded_worktree_rollback_leaves_clean_index` (RED driver) and `test_orphan_worktree_rollback_still_clean_index` (AC-4 regression + other-ticket working-tree safety) to tests/integration/test_klc057_hardening.py. Real bare-repo substrate; CAS push forced to fail via a real pre-receive hook that rejects.
**Outcome**: red
**Notes**: RED driver fails with `D  knowledge/tickets-index.jsonl` staged after rollback — exactly the bug at core/skills/state_tx.py:135 (subtree-scoped index reset misses the top-level staged `rm --cached`). Orphan guard passes (no-op there). Committed 309dd55.

## Step 1 — 2026-07-16 (GREEN)
**Attempt**: replace the subtree-scoped rollback reset (`git reset -q -- tickets/<t>/`) with an unscoped `git reset -q` in core/skills/state_tx.py; drop the now-unused `subtree` local; update the module docstring.
**Outcome**: green
**Notes**: both new tests pass; full test_state_tx.py + test_klc057_hardening.py = 30 passed. Committed e8d155c. Safe per C-003 (stash-popped other-ticket edits + snapshot restore live in the WORKING TREE, not the index).

## Step 2 — 2026-07-16 (RED)
**Attempt**: add `test_state_init_commits_and_pushes_preserved_tickets` (RED driver: real bare origin + second clone) and `test_state_init_no_preserved_content_makes_no_empty_commit` (guard) to tests/integration/test_state_init.py.
**Outcome**: red
**Notes**: RED driver fails — `git show klc-state:tickets/local.txt` returns 128 (preserved ticket copied but never committed). Committed 663cfbc.

## Step 2 — 2026-07-16 (GREEN)
**Attempt**: add `_commit_preserved(repo, klc, remote)` in core/phases/state.py (add -A; skip when nothing staged → no empty commit; commit; push to klc-state) and call it from `run()` after `_merge_back`, inside the existing try/except.
**Outcome**: green
**Notes**: both new tests pass; full test_state_init.py = 34 passed (no regression to existing preserve/idempotent/offline tests). Committed e7ea0e5.

## Step 3 — 2026-07-16 (RED)
**Attempt**: add `test_state_init_preserved_commit_pushfail_warns_exit0` (patches state._git so ONLY the preserved push — the one without `-u` — fails).
**Outcome**: red
**Notes**: fails on step-2 code — the raising push (check=True) tears init down via the except path, and restore_backup then raises FileNotFoundError (backup already consumed by _merge_back). Committed e329fbf.

## Step 3 — 2026-07-16 (GREEN)
**Attempt**: make the preserved-tickets push fail-safe — `check=False` + a "committed locally but not pushed" warning, mirroring the orphan-create push tail (state.py:331-341).
**Outcome**: green
**Notes**: test passes; full test_state_init.py = 35 passed. Committed 1a10dc5.

## Deviation from plan
The committed impl-plan step-2 sketch already showed the fail-safe (`check=False` + warn) push. To give step-3 a genuine RED, step-2 delivered the happy commit+push plus the no-empty-commit guard, and the push fail-safe (warn + exit 0) was implemented in step-3. Net code is identical to the plan; only the RED/GREEN boundary shifted. Recorded as D-004 in impl-plan.md.

## Evidence

```
$ python3 -m pytest "tests/integration/test_klc057_hardening.py::test_upgraded_worktree_rollback_leaves_clean_index" "tests/integration/test_klc057_hardening.py::test_orphan_worktree_rollback_still_clean_index" -q
..                                                                       [100%]
2 passed in 0.50s
```

```
$ python3 -m pytest "tests/integration/test_state_init.py::test_state_init_commits_and_pushes_preserved_tickets" "tests/integration/test_state_init.py::test_state_init_no_preserved_content_makes_no_empty_commit" "tests/integration/test_state_init.py::test_state_init_preserved_commit_pushfail_warns_exit0" -q
...                                                                      [100%]
3 passed in 0.53s
```

```
$ python3 -m pytest tests/test_state_tx.py tests/test_state_sync.py tests/test_state_feature.py tests/integration/test_state_init.py tests/integration/test_klc057_hardening.py tests/integration/test_klc057_real_repo.py tests/integration/test_klc057_sync_holder.py tests/integration/test_klc057_fuzz.py tests/integration/test_klc057_fuzz_concurrent.py -q
130 passed in 86.38s (0:01:26)
```

```
$ python3 -m pytest tests/test_intake_identity.py tests/test_intake_routing.py tests/test_holder.py tests/integration/test_verbs_json.py -q
29 passed in 0.46s
```

## Review-fix round — 2026-07-16 (codex + fresh reviewer: 2 defects in _commit_preserved)

FINDING-1 (HIGH, derived-never-shared / INV7): `_commit_preserved` staged with a bare `git add -A` and never applied the derived-ignore set, so preserved `.lock`/`_prompt.md`/`.index.json`/`scratch/`/`knowledge/tickets-index.jsonl` were committed AND pushed to shared klc-state.
FINDING-2 (P1/data-loss): `_merge_back` deleted the backup before `_commit_preserved` ran; a commit failure then tore down the merged worktree and crashed in `_restore_backup` (backup gone), destroying the only copy of the preserved tickets.

### RED (both bugs demonstrated on current code) — committed e4a8edb
```
$ python3 -m pytest "tests/integration/test_state_init.py::test_state_init_excludes_derived_from_preserved_commit" "tests/integration/test_state_init.py::test_state_init_preserved_commit_failure_preserves_tickets_no_crash" "tests/integration/test_state_init.py::test_state_init_preserved_commit_pushfail_warns_exit0" -q
FAILED ...::test_state_init_excludes_derived_from_preserved_commit
  AssertionError: derived file leaked into klc-state: tickets/KLC-9001/.lock
  tree: knowledge/tickets-index.jsonl / tickets/KLC-9001/.index.json / tickets/KLC-9001/.lock / ...
FAILED ...::test_state_init_preserved_commit_failure_preserves_tickets_no_crash
  FileNotFoundError: ... '/proj/.klc.init-bak' -> '/proj/.klc'  (crash + preserved ticket lost)
2 failed, 1 passed in 4.95s
```

### Fixes (GREEN) — committed 048ec0b
- F1: import `state_sync` in core/phases/state.py; call `state_sync.ensure_derived_ignored(klc)` before `git add -A` in `_commit_preserved` (derived-ignore set is the single source of truth in state_sync).
- F2: removed `shutil.rmtree(backup)` from `_merge_back`; drop the backup only after a fully successful init in `run()`; hardened `_restore_backup` to guard `backup.exists()`.

### Derived-exclusion proof (real repro — only the real ticket is committed to klc-state)
```
$ git ls-tree -r --name-only klc-state
tickets/KLC-9001/meta.json
```
(.lock, .index.json, design/_prompt.md, scratch/note.txt, knowledge/tickets-index.jsonl all ABSENT.)

### Data-loss-averted proof
`test_state_init_preserved_commit_failure_preserves_tickets_no_crash`: forced `_commit_preserved` commit failure via a REAL pre-commit hook → init returns 1 cleanly (no traceback) AND the preserved `local.txt` ("PRECIOUS") survives on disk.

### GREEN + regression
```
$ python3 -m pytest "tests/integration/test_state_init.py::test_state_init_excludes_derived_from_preserved_commit" "tests/integration/test_state_init.py::test_state_init_preserved_commit_failure_preserves_tickets_no_crash" "tests/integration/test_state_init.py::test_state_init_preserved_commit_pushfail_warns_exit0" -q
3 passed in 1.88s

$ python3 -m pytest tests/integration/test_state_init.py -q
37 passed in 5.68s

$ python3 -m pytest tests/test_state_tx.py tests/test_state_sync.py tests/test_state_feature.py tests/integration/test_state_init.py tests/integration/test_klc057_hardening.py tests/integration/test_klc057_real_repo.py tests/integration/test_klc057_sync_holder.py tests/integration/test_klc057_fuzz.py tests/integration/test_klc057_fuzz_concurrent.py -q
132 passed in 70.42s (0:01:10)
```

## Review-fix round 2 — 2026-07-16 (scoped re-review of the FIX delta: 2 new P2 regressions)

P2-A (repo-wide exclude pollution): the FINDING-1 fix called `state_sync.ensure_derived_ignored(klc)`, which appends to `info/exclude` — a COMMON git-dir file shared by every worktree — so a plain `klc state init` silently hid unrelated files in the user's main worktree.
P2-B (silent backup-cleanup failure): the FINDING-2 fix dropped the backup with `shutil.rmtree(backup, ignore_errors=True)`; a cleanup failure left `.klc.init-bak` behind while init reported success, breaking the NEXT init's backup-preflight with no warning.

### RED (both regressions on the fix delta) — committed f42f938
```
$ python3 -m pytest "tests/integration/test_state_init.py::test_state_init_does_not_mutate_repo_exclude" "tests/integration/test_state_init.py::test_state_init_backup_cleanup_failure_surfaces_warning" -q
FAILED ...::test_state_init_does_not_mutate_repo_exclude
  AssertionError: klc state init must NOT mutate the repo-wide .git/info/exclude
  assert b"...\nscratch/\n" == b"...# *~\n"
FAILED ...::test_state_init_backup_cleanup_failure_surfaces_warning
  AssertionError: a leftover-backup warning must be surfaced (not silently ignored): ''
2 failed in 0.68s
```

### Fixes (GREEN) — committed 0cff9fd
- P2-A: added `state_sync.derived_add_exclude_pathspecs()` (built from the SAME `_DERIVED_IGNORES` single source of truth). `_commit_preserved` now stages with `git add -A -- . :(exclude,glob)**/…` and NO LONGER calls `ensure_derived_ignored`, so `.git/info/exclude` is untouched.
- P2-B: replaced `ignore_errors=True` with a guarded `try: rmtree(backup) except OSError` that warns with the leftover path (init still exits 0).

### Proof (real repro): derived absent via pathspecs AND info/exclude unchanged
```
$ git ls-tree -r --name-only klc-state
tickets/K/meta.json
$ .git/info/exclude md5 before=036208b4a1ab4a235d75c181e685e5a3 after=036208b4a1ab4a235d75c181e685e5a3
UNCHANGED (identical)
```

### GREEN + regression
```
$ python3 -m pytest "tests/integration/test_state_init.py::test_state_init_does_not_mutate_repo_exclude" "tests/integration/test_state_init.py::test_state_init_backup_cleanup_failure_surfaces_warning" "tests/integration/test_state_init.py::test_state_init_excludes_derived_from_preserved_commit" "tests/integration/test_state_init.py::test_state_init_preserved_commit_failure_preserves_tickets_no_crash" "tests/integration/test_state_init.py::test_state_init_commits_and_pushes_preserved_tickets" -q
5 passed in 2.99s

$ python3 -m pytest tests/integration/test_state_init.py -q
39 passed in 5.88s

$ python3 -m pytest tests/test_state_tx.py tests/test_state_sync.py tests/test_state_feature.py tests/integration/test_state_init.py tests/integration/test_klc057_hardening.py tests/integration/test_klc057_real_repo.py tests/integration/test_klc057_sync_holder.py tests/integration/test_klc057_fuzz.py tests/integration/test_klc057_fuzz_concurrent.py -q
134 passed in 68.24s (0:01:08)
```

## Review-fix round 3 — 2026-07-16 (close the derived-handling class, not a 4th patch)

FINDING-3 (P2, same class as F1/P2-A): the exclude-pathspec `git add` stopped NEW derived files being staged, but did NOT converge OUT a derived path the EXISTING klc-state already TRACKS (legacy layout). On the track-existing/upgrade path `_merge_back` overwrites the tracked derived file with the local copy; the excluded add stages neither the modification nor a removal → init reports success with `.klc` DIRTY and the derived file still tracked/shared. Closed by matching the proven runtime discipline in `state_sync.commit_and_push_cas_subtree` (exclude NEW + `git rm --cached` TRACKED).

### RED (upgrade case on current code) — committed 60851ad
```
$ python3 -m pytest "tests/integration/test_state_init.py::test_state_init_converges_out_tracked_derived_on_upgrade" -q
FAILED ...::test_state_init_converges_out_tracked_derived_on_upgrade
  AssertionError: worktree must be clean w.r.t. tracked files, got: 'M knowledge/tickets-index.jsonl'
```

### Fix (GREEN) — committed 2b08872
- state_sync: factored `_derived_match_pathspecs()` (single base from `_DERIVED_IGNORES`); `derived_add_exclude_pathspecs()` is its negated form; added `derived_untrack_pathspecs()` (positive, unscoped, tree-wide).
- `_commit_preserved`: after the exclude `git add -A -- . <excludes>`, run
  `git rm -r --cached -q --ignore-unmatch -- <derived pathspecs>` to stage removal of any already-tracked derived file (kept on disk). No info/exclude mutation (keeps P2-A).

### Proof (real upgrade repro): dirty→clean + derived converged OUT of klc-state
```
klc-state tree BEFORE init:  knowledge/tickets-index.jsonl , tickets/KLC-ORIG/meta.json
klc-state tree AFTER  init:  tickets/KLC-NEW/meta.json , tickets/KLC-ORIG/meta.json   (derived GONE)
worktree `git status --porcelain --untracked-files=no`: [clean]
derived file still on disk (untracked): .klc/knowledge/tickets-index.jsonl
```

### GREEN + regression
```
$ python3 -m pytest <6 derived/init tests: converge-out, no-exclude-mutation, excludes-derived, commits+pushes, commit-fail-preserves, backup-cleanup-warn> -q
6 passed in 2.33s

$ python3 -m pytest tests/integration/test_state_init.py -q
40 passed in 6.41s

$ python3 -m pytest tests/test_state_tx.py tests/test_state_sync.py tests/test_state_feature.py tests/integration/test_state_init.py tests/integration/test_klc057_hardening.py tests/integration/test_klc057_real_repo.py tests/integration/test_klc057_sync_holder.py tests/integration/test_klc057_fuzz.py tests/integration/test_klc057_fuzz_concurrent.py -q
135 passed in 71.14s (0:01:11)
```

No further distinct derived-handling gap found: `_commit_preserved` now matches the runtime staging discipline exactly (exclude NEW + untrack TRACKED), so the derived-never-shared invariant is closed for init.
