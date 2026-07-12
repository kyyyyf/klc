---
ticket: KLC-054
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no conversation context) + codex exec review --base main (4 rounds)
reviewed_at: 2026-07-12
review_depth: full
branch: feature/klc-054-state-sync
---

# Review report — KLC-054

## Summary

`state_sync.commit_and_push_cas` / `pull_rebase` provide git-CAS coordination
for the multi-user `.klc/` state — data-coordination code where a
misclassified conflict corrupts shared state. Reviewed by a fresh
`general-purpose` subagent (per CLAUDE.md) plus **four** rounds of
`codex exec review --base main`, each re-reviewing the prior round's fixes.

Rounds 1–3 (7 + 2 + 3 = 12 findings) were all fixed with verified RED→GREEN
cycles. Round 4 surfaced 1 further P2 (only on the non-default `remote`
argument that AC-2 never exercises); per the operator's bounded-loop decision
it is **deferred** to a follow-up hardening ticket
(`.klc/wave1-followup-hardening.md`). 21 tests pass, stable across repeated
runs (the multi-race concurrency test included).

## Verdict

APPROVED (with 1 documented non-default-arg edge deferred to follow-up). All
findings on the AC-exercised paths are fixed and verified.

## Findings by round

### Round 1 — fresh review (3 MED + 4 LOW) — all fixed

| id | sev | finding | fix |
|----|-----|---------|-----|
| — | MED | locale-dependent stderr parsing breaks CAS under non-English git | `_GIT_ENV` (`LC_ALL=C`, `LANG=C`, `GIT_TERMINAL_PROMPT=0`) on every git call |
| — | MED | `git fetch` return code unchecked → masks network errors as retry-exhaustion | check fetch rc, raise before classifying |
| — | MED | local commit left on HEAD after terminal failure (pollutes next CAS) | `git reset --soft HEAD~1` rollback on `StateConflictError`/`RetryExhausted`/push error |
| — | LOW | merge commits invisible to `git log --name-only` | (superseded by round-3 per-commit classifier) |
| — | LOW | `pull_rebase` over-labels all failures `RebaseConflictError` | `_rebase_in_progress()` guard |
| — | LOW | bare `RuntimeError` on nothing-to-commit | typed `NothingToCommitError` |
| — | codex-P2 | `git push HEAD` targets local branch name, not the upstream | `_upstream_branch()` + explicit `HEAD:<upstream>` refspec |
| — | codex-P2 | `git add` failure unchecked → commits pre-staged content | check add rc; pathspec-limited commit |

### Round 2 — codex re-review (2 P2) — all fixed

- **P2** non-CAS rejections (protected branch / pre-receive hook say `rejected`
  but not `non-fast-forward`) sent through the CAS loop → masked as
  `RetryExhaustedError`. Fix: positive allowlist `_CAS_RACE_MARKERS`
  (`non-fast-forward`, `fetch first`, `cannot lock ref`, `failed to update ref`,
  `stale info`) — only genuine races retry; policy declines raise clearly. (The
  `cannot lock ref` / `failed to update ref` markers were found empirically to
  be how real simultaneous-write races surface, and are deliberately included.)
- **P2** self-reverting same-ticket commits: net 3-dot diff empty → missed.
  (superseded/refined by round 3.)

### Round 3 — codex re-review (3 P2) — all fixed

- **P2** `git log -m` double-counts a merge's second-parent paths → other-ticket
  merge misreported as `StateConflictError` (false AC-3 conflict).
- **P2** renames report only the destination → a file renamed out of
  `tickets/<ticket>/` missed (AC-4).
- **P2** empty `paths` list → `git commit --` with no pathspec commits
  already-staged content.
- **Combined fix:** new `_incoming_same_ticket_paths()` enumerates
  `git rev-list HEAD..@{upstream}` and unions each commit's changed paths from
  `git show --first-parent -M --name-status` — first-parent-per-commit kills the
  2nd-parent double-count while preserving merge visibility; `-M --name-status`
  unions rename source+dest; empty `paths` now raises `ValueError` before any git
  op (also fixed a latent generator double-iteration).

### Round 4 — codex record pass (1 P2) — DEFERRED to follow-up

See `.klc/wave1-followup-hardening.md`: a non-default `remote` argument
(≠ configured upstream) makes classification/rebase read `@{upstream}` instead
of the pushed remote. The default `remote="origin"` == upstream path (the only
one AC-2 uses) is correct and tested; only the documented-but-unused non-default
arg is affected.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 | PASS | `pull_rebase` clean; `test_clean_pull_rebase` |
| AC-2 | PASS | fast-forward push to upstream branch; `test_fast_forward_push`, `test_push_targets_upstream_branch_not_local_name` |
| AC-3 | PASS | other-ticket → rebase+retry; `test_other_ticket_*`, `test_multi_race_*`, `test_other_ticket_merge_second_parent_*` |
| AC-4 | PASS | same-ticket → `StateConflictError`; `test_same_ticket_*`, `test_self_reverting_*`, `test_rename_out_of_ticket_*` |
| AC-5 | PASS | entire suite runs against local bare repos, zero network |

## Final state

`python3 -m pytest tests/test_state_sync.py -v` → 21 passed (stable ×4);
`tests/test_jira_sync.py` → 18 passed (no regression). 12 commits on the branch
(build ×4, build-log, ack, r1 ×2, r2 ×2, r3 ×2). All git subprocess calls are
list-arg, C-locale, never `shell=True`.


---
[!CONFLICT] scope-expansion detected at review:ack-needed
  planned modules: ['core/skills/state_sync.py', 'tests/integration']
  actual modules:  ['core/skills', 'tests']
  unplanned:       ['core/skills', 'tests']
Resolve: update meta.json:affected_modules to include all touched modules, then re-run `klc ack KLC-054`.
