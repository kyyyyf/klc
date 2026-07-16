# Agent prompt — KLC-063 · build:work · step-1

Ticket: **KLC-063** · track: **M** · kind: **tech**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

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

### Current step — step-1

**tx rollback leaves a clean index (unscoped reset)**

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
- 
**Tests:**
| Test type | Test name / location | Target symbol(s) | Notes |
|-----------|----------------------|------------------|-------|
| integration | tests/integration/test_klc057_hardening.py::test_upgraded_worktree_rollback_leaves_clean_index | `state_tx.state_tx` | AC-3 / AC-6b; real bare-repo, index tracks the derived cache, forced push failure |
| integration | tests/integration/test_klc057_hardening.py::test_orphan_worktree_rollback_still_clean_index | `state_tx.state_tx` | AC-4 regression; 053-orphan (index never tracked) stays clean — fix is a no-op |
| integration | tests/integration/test_klc057_hardening.py::test_other_ticket_dirty_edit_is_not_destroyed (existing) | `state_tx.state_tx` | AC-4; unscoped index reset must not touch another ticket's working-tree edit |

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/.claude/worktrees/agent-a9f4f3102be940437/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-063 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-063/impl-plan.md`
- Full spec: `.klc/tickets/KLC-063/spec.md`
- Full test-plan: `.klc/tickets/KLC-063/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-063 step-1` and
run `klc step KLC-063 2` to get the next step's card,
or `klc ack KLC-063 --pick 1` if this was the last step.
