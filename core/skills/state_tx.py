"""state_tx — the self-contained, self-healing sync envelope (KLC-057).

``state_tx(ticket, msg)`` is a context manager wrapping a lifecycle verb's whole
mutating body in the ``self-heal → pull → body → glob-commit + CAS-push`` cycle
exactly once. It is the ONLY component that touches git when the multi-user
feature is ON, and it is designed so no individual mutation site needs to know
it is inside a transaction:

1. **Preserve-and-pull on enter.** Before pulling, uncommitted TRACKED artifacts
   (in-progress work products an agent wrote under the ticket) are stashed around
   the rebase and restored (``state_sync.pull_rebase_preserving``) — never
   discarded. They are then captured by the exit glob-commit, so a normal op
   never loses phase work. Only truly derived/ignored files are excluded.
1b. **Class-closing stale-guard.** The ticket's committed subtree hash is
   captured before the pull and re-checked after; if the ticket existed and the
   pull changed it, ``StaleStateError`` is raised BEFORE the body runs. Every
   verb's pre-tx validation (scope/gate/pick/can_complete/``--force``) is thus
   never applied to pulled-changed state — the single guard for the whole
   "validate-before-pull" class, so no verb path can bypass it.
2. **Glob-commit the ticket subtree on exit.** Instead of a hand-listed set of
   paths, everything under ``tickets/<ticket>/`` is committed and CAS-pushed, so
   any file the body writes there is captured automatically — no forgotten site.
3. **Rollback cleans tree AND index.** On ANY terminal failure the subtree is
   restored to its post-pull snapshot (created files deleted, modified files
   restored) and the index is reset for the subtree, so the next op's pull never
   hits a dirty tree/index.

When ``state_feature.enabled()`` is False (single-user mode) the wrapper is a
pure pass-through: no git at all. It yields ``None`` so callers can gate holder
writes on ``if tx is not None:`` and keep the feature-off path byte-for-byte
identical (AC-8).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import lifecycle
import state_feature
import state_sync
from _paths import klc_dir


class _TxHandle:
    """Truthy marker yielded when the feature is ON (distinguishes from None)."""


def _subtree_root(ticket, kdir: Path) -> Path:
    return kdir / "tickets" / str(ticket)


def _snapshot_subtree(ticket, kdir: Path) -> dict:
    """Capture bytes of every file currently under ``tickets/<ticket>/``.

    Recorded relative to *kdir*. A file absent from the snapshot but present at
    rollback time was created by the body → it is deleted on rollback.
    """
    root = _subtree_root(ticket, kdir)
    files: dict[str, bytes] = {}
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file():
                files[str(p.relative_to(kdir))] = p.read_bytes()
    return files


def _restore_subtree(snapshot: dict, ticket, kdir: Path) -> None:
    """Undo every body mutation under the subtree: delete files the body
    created, then restore snapshotted files to their post-pull bytes."""
    root = _subtree_root(ticket, kdir)
    if root.exists():
        for p in list(root.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(kdir))
                if rel not in snapshot:
                    p.unlink()
    for rel, prior in snapshot.items():
        fp = kdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(prior)


@contextmanager
def state_tx(ticket, msg):
    if not state_feature.enabled():
        # AC-8 no-op: run the body, touch no git, write no holder.
        yield None
        return

    kdir = klc_dir()
    subtree = f"tickets/{ticket}/"

    # 0. CLASS-CLOSING stale-guard (capture BEFORE the pull). Record this
    #    ticket's committed subtree hash so we can tell, after the pull, whether
    #    the shared state moved under a verb's pre-tx validation.
    pre_hash = state_sync.ticket_tree_hash(kdir, ticket)
    # 1. Make sure the derived/runtime-local caches are git-ignored so they never
    #    dirty the tree, block the pull, or ride the glob-commit.
    state_sync.ensure_derived_ignored(kdir)
    # 2. Pull the latest remote state, PRESERVING any uncommitted tracked
    #    artifacts (in-progress work) across the rebase — never discard them.
    state_sync.pull_rebase_preserving(kdir)
    # 3. If the ticket EXISTED at enter and the pull changed its committed state
    #    (meta.json / raw.md / any artifact — it is a content-addressed SUBTREE
    #    hash), EVERY verb's pre-tx validation (scope/gate/pick/can_complete/
    #    --force overwrite) is stale → abort BEFORE the body runs. This closes the
    #    whole "validate-before-pull" class at the envelope, so no verb path —
    #    intake/ack/next, current or future — can act on pulled-changed state.
    #    (pre_hash None → a brand-new ticket that only now appears; that
    #    creation-collision is left to the verb's own taken-key handling.)
    if pre_hash is not None and state_sync.ticket_tree_hash(kdir, ticket) != pre_hash:
        raise state_sync.StaleStateError("remote state advanced — re-run")
    # 4. Snapshot the ticket subtree so any body mutation can be rolled back.
    snap = _snapshot_subtree(ticket, kdir)
    # 5. Defer any Jira push the body triggers (via set_state) until AFTER the
    #    CAS push confirms — so a rejected/rolled-back push never leaves Jira
    #    advanced ahead of klc (P1). The flush below fires only on clean success.
    with lifecycle.defer_jira_pushes() as pending:
        try:
            # 6. The verb's whole mutating body runs here.
            yield _TxHandle()
            # 7. Glob-commit the ticket subtree + single CAS push.
            state_sync.commit_and_push_cas_subtree(ticket, msg, kdir)
        except Exception:
            # ANY terminal failure — StateConflictError, a first-grab
            # HolderConflictError, or a non-CAS sync error (RuntimeError/
            # ValueError/NothingToCommitError) — unwinds every local mutation the
            # body made so the local tree never diverges ahead of the untouched
            # remote, and the index is reset for the subtree
            # (commit_and_push_cas_subtree leaves its aborted commit STAGED via
            # reset --soft) so the next pull never hits a dirty index. The
            # collected Jira push is DISCARDED (not flushed). The exception then
            # propagates for a clean verb message.
            _restore_subtree(snap, ticket, kdir)
            state_sync._git(["reset", "-q", "--", subtree], kdir)
            raise
    # 8. CAS push succeeded → NOW fire the deferred Jira push (never on rollback).
    lifecycle.flush_jira_pushes(pending)
