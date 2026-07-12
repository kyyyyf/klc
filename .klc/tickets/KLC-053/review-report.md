---
ticket: KLC-053
kind: review-report
authority: human
reviewed_by: general-purpose subagent (fresh, no conversation context) + codex exec review --base main (4 rounds)
reviewed_at: 2026-07-12
review_depth: full
branch: feature/klc-053-state-init
---

# Review report — KLC-053

## Summary

`klc state init` materializes the `klc-state` orphan branch as a git worktree
at `.klc/` — a data-safety-critical command that moves real ticket state. It
went through an unusually deep review: a fresh `general-purpose` subagent (per
CLAUDE.md's mandatory pre-review-report step) plus **four** rounds of
`codex exec review --base main` (each round re-reviewing the previous round's
fixes). This is exactly the bounded review⇄fix loop the operator elected to
run and then stop.

Rounds 1–3 (10 findings: 1 HIGH + 3 MEDIUM + 3 LOW + 4 P2) were all fixed with
verified RED→GREEN cycles. Round 4 surfaced 3 further P2 edge cases; per the
operator's bounded-loop decision these are **deferred** to a follow-up
hardening ticket (`.klc/wave1-followup-hardening.md`) rather than triggering a
fifth round. The common/default paths are fully covered; 19 tests pass.

## Verdict

APPROVED (with 3 documented edge cases deferred to follow-up hardening). All
HIGH/MEDIUM and rounds 1–3 P2 findings are fixed and verified; no data-loss
path remains on the tested surface.

## Findings by round

### Round 1 — fresh review (1 HIGH + 3 MED + 3 LOW) — all fixed

| id | sev | finding | fix |
|----|-----|---------|-----|
| H1 | HIGH | partial-failure strands ticket data in `.klc.init-bak` + false "already initialized" success | teardown partial worktree + restore backup on any failure; idempotency gated on a *completed* init |
| M2 | MED | orphan root commit needs git identity (fails on fresh clone/CI) | inline `git -c user.name=klc -c user.email=klc@localhost commit` |
| M3 | MED | repo root from `Path.cwd()` → wrong `.klc/` from a subdir | `_resolve_repo()` honors `PROJECT_ROOT` / `git rev-parse --show-toplevel` |
| M4 | MED | collision "local wins" + failure-restore untested | added both tests |
| L5 | LOW | `--orphan` needs git ≥2.42, no guard | `_git_version()` guard w/ clear message |
| L6 | LOW | `_stash_existing` rmtree's an existing backup | refuse when `.klc.init-bak` exists |
| L7 | LOW | merge-back symlink/type-clash aborts | recursive `_merge_tree` (symlink-aware) |

### Round 2 — codex re-review of fixes (2 P2) — all fixed

- **P2** `git ls-remote` failure treated as branch-absence → forks a fresh
  orphan instead of tracking existing `origin/klc-state`. Fix: tri-state
  `_remote_state_status()` (`present`/`absent`/`unreachable`) + local
  remote-tracking-ref fallback; refuses to orphan when the remote is unreachable
  and no local ref exists; a repo with no remote at all is `absent` (safe orphan).
- **P2** idempotency accepted a `.klc/` worktree on the *wrong* branch. Fix:
  `_klc_worktree_branch()` verifies the worktree is on `klc-state`; a different
  branch is a clear error, not idempotent success.

### Round 3 — codex re-review of round-2 fixes (2 P2) — all fixed

- **P2** merge-back followed a symlink-to-dir (`Path.is_dir()` dereferences) →
  wrote preserved tickets outside `.klc/`. Fix: unlink any destination symlink
  before dispatch (never traverse a symlink); local content wins.
- **P2** `_merge_back` OSError bypassed the git/StateError-only restore handler
  → traceback + stranded backup. Fix: broadened to catch `OSError`; also gated
  the blind-`rmtree` teardown behind a `stashed=` flag so it can never delete
  the original before a backup exists (latent data-loss hardening).

### Round 4 — codex record pass (3 P2) — DEFERRED to follow-up

See `.klc/wave1-followup-hardening.md`: (1) fetch doesn't refresh the
remote-tracking ref in a single-branch/stale clone; (2) a nested `.git` in a
preserved `.klc/` clobbers worktree metadata; (3) a deleted-but-unpruned
`.klc/` worktree reports idempotent success. All exotic; default paths tested.

## AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-1 | PASS | origin-has-klc-state → tracks `origin/klc-state`, preserves tickets; `test_state_init_tracks_origin_*`, offline/tracking-ref tests |
| AC-2 | PASS | no branch → orphan + worktree, idempotent; `test_state_init_*orphan*`, wrong-branch/idempotency tests |

## Final state

`python3 -m pytest tests/integration/test_state_init.py -v` → 19 passed.
12 commits on the branch (build ×4, build-log, ack, r1 ×2, r2 ×2, r3 ×2).
Data-safety invariant: on any failure (git OR filesystem) the command tears
down the partial worktree and restores `.klc.init-bak` before erroring — never
strands ticket data.
