---
ticket: KLC-053
kind: feature
authority: agent
track: XS
risk_tags: [user-facing]
---

## Goals
Add `klc state init` — a one-time per-checkout operation that materializes the project's `klc-state` **orphan branch** as a git **worktree** at `.klc/` in the SAME project repo (no separate state repo). If the `klc-state` branch does not exist yet (on `origin` or locally), it is created as an orphan (`git checkout --orphan`, empty root, history disjoint from `main`). All existing `.klc/tickets/...` reads stay unchanged. `.klc/` remains in `main`'s `.gitignore` (it is a worktree of another branch). A plain clone "for usage" does not materialize `.klc/`; cloning "for work" = clone + `klc state init`.

## Acceptance Criteria
- [ ] AC-1: Running `klc state init` in a checkout where `origin` already has a `klc-state` branch adds a worktree at `.klc/` tracking `origin/klc-state`, preserving any existing ticket files, and exits 0.
- [ ] AC-2: Running `klc state init` in a checkout where no `klc-state` branch exists yet creates the orphan `klc-state` branch (empty root) and adds the `.klc/` worktree bound to it, then exits 0; a second run is idempotent (worktree already present → no-op, exit 0).

## Affected
[!ASSUMPTION if-false=scope-may-expand] scripts/klc — dispatcher, `_dispatch` function: src=/home/ek/projects/klc/scripts/klc:110 — needs `"state"` routed to `_run_phase("state", rest)` or equivalent; LSP symbol resolution not available for this shell-dispatched entry, path verified by direct read.
[!ASSUMPTION if-false=scope-may-expand] core/phases/state.py — new file implementing `run(argv)` with `state init <remote>` subcommand; no pre-existing symbol to verify.

## Estimate
complexity: 1
uncertainty: 1
risk: 0
manual: 0
total: 2

DISCOVERY_LITE_DONE
