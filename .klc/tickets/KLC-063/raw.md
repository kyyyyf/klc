---
ticket: KLC-063
kind_hint: tech
created: 2026-07-16T08:56:51Z
---
klc state init must commit preserved .klc/tickets into klc-state on bootstrap. Today _merge_back (state.py:505-507) copies pre-existing tickets into the new worktree AFTER _add_worktree already committed/pushed the branch, but never commits them -> other clones do not receive preserved tickets and pulls diverge once someone recreates the same paths. Also: state_tx rollback (state_tx.py:135) resets only tickets/<ticket>/, leaving the staged rm --cached of the shared derived index (state_sync.py:523, upgraded-worktree case) -> next tx starts on a dirty index, contradicting the rollback contract. Source: codex P2 x2 + fresh-A LOW. Add a rollback test with a tracked shared derived index.
