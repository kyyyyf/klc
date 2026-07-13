"""state_tx — the single shared sync+holder transaction envelope (KLC-057).

`state_tx(ticket, paths, msg)` is a context manager wrapping a lifecycle verb's
body in the `pull → body → CAS-push (with rollback)` envelope exactly once
(ADR Option B). Each verb supplies only its body and enters the wrapper INSIDE
its existing `with acquire_lock(ticket):` critical section.

When `state_feature.enabled()` is False (single-user mode) the wrapper is a pure
pass-through: no pull, no push, no holder writes — the verb behaves exactly as
today (AC-8). It yields `None` in that case so callers can gate holder writes on
`if tx is not None:` and keep the feature-off path byte-for-byte identical.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import state_feature
import state_sync
from _paths import klc_dir


class _TxHandle:
    """Truthy marker yielded when the feature is ON (distinguishes from None)."""


def _rel(path, kdir: Path) -> str:
    """Normalise a path (absolute or relative) to klc_dir-relative for git."""
    p = Path(path)
    if p.is_absolute():
        return os.path.relpath(p, kdir)
    return str(p)


def _snapshot(rel_paths, kdir: Path) -> dict:
    """Map each path → its current bytes, or None if it does not exist."""
    snap: dict[str, bytes | None] = {}
    for rel in rel_paths:
        fp = kdir / rel
        snap[rel] = fp.read_bytes() if fp.exists() else None
    return snap


def _restore(snapshot: dict, kdir: Path) -> None:
    """Undo local mutations: delete files that were absent, rewrite the rest."""
    for rel, prior in snapshot.items():
        fp = kdir / rel
        if prior is None:
            if fp.exists():
                fp.unlink()
        else:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(prior)


@contextmanager
def state_tx(ticket, paths, msg, remote=None):
    if not state_feature.enabled():
        # AC-8 no-op: run the body, touch no git, write no holder.
        yield None
        return

    kdir = klc_dir()
    rel_paths = [_rel(p, kdir) for p in paths]

    # Pull first so the body mutates the latest remote state; snapshot AFTER the
    # pull so a rollback restores to the post-pull baseline (not stale bytes).
    state_sync.pull_rebase(kdir)
    snap = _snapshot(rel_paths, kdir)
    try:
        # The body (verb + holder mutation) runs here. If it raises anything
        # other than a CAS conflict (e.g. HolderConflictError from a first-grab
        # refusal) the exception propagates WITHOUT a push — the remote is left
        # untouched, which is the desired "no steal / no advance" outcome.
        yield _TxHandle()
        # Clean exit → the single CAS push carries only this ticket's paths.
        state_sync.commit_and_push_cas(rel_paths, msg, ticket, kdir)
    except state_sync.StateConflictError:
        # Same-ticket single-writer violation: unwind every local mutation the
        # body made (created files deleted, modified files restored) and surface
        # the conflict to the caller.
        _restore(snap, kdir)
        raise
