"""state_tx — the self-contained, self-healing sync envelope (KLC-057).

``state_tx(ticket, msg)`` is a context manager wrapping a lifecycle verb's whole
mutating body in the ``self-heal → pull → body → glob-commit + CAS-push`` cycle
exactly once. It is the ONLY component that touches git when the multi-user
feature is ON, and it is designed so no individual mutation site needs to know
it is inside a transaction:

1. **Self-heal on enter.** Before pulling, force the tracked worktree back to a
   pristine ``HEAD`` (``state_sync.ensure_clean``). Every successful op
   commits+pushes, so any dirty tracked state on enter is a never-pushed
   crash/leftover artifact; the remote (restored by the pull) is truth. This
   makes the envelope robust to ANY stray write and kills the deadlock class.
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

    # 1. Self-heal the tracked tree to clean HEAD, and make sure the derived
    #    caches are git-ignored, BEFORE pulling (both never raise).
    state_sync.ensure_clean(kdir)
    state_sync.ensure_derived_ignored(kdir)
    # 2. Pull the latest remote state onto the now-clean tree.
    state_sync.pull_rebase(kdir)
    # 3. Snapshot the ticket subtree so any body mutation can be rolled back.
    snap = _snapshot_subtree(ticket, kdir)
    try:
        # 4. The verb's whole mutating body runs here.
        yield _TxHandle()
        # 5. Glob-commit the ticket subtree + single CAS push.
        state_sync.commit_and_push_cas_subtree(ticket, msg, kdir)
    except Exception:
        # ANY terminal failure — StateConflictError, a first-grab
        # HolderConflictError, or a non-CAS sync error (RuntimeError/ValueError/
        # NothingToCommitError) — unwinds every local mutation the body made so
        # the local tree never diverges ahead of the untouched remote, and the
        # index is reset for the subtree (commit_and_push_cas_subtree leaves its
        # aborted commit STAGED via reset --soft) so the next pull never hits a
        # dirty index. The exception then propagates for a clean verb message.
        _restore_subtree(snap, ticket, kdir)
        state_sync._git(["reset", "-q", "--", subtree], kdir)
        raise
