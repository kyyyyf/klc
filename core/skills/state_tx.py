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
   restored) and the WHOLE index is reset, so the next op's pull never hits a
   dirty tree/index — including the top-level `rm --cached` untracking of the
   shared derived cache that an upgraded worktree stages OUTSIDE the subtree.

When ``state_feature.enabled()`` is False (single-user mode) the wrapper is a
pure pass-through: no git at all. It yields ``None`` so callers can gate holder
writes on ``if tx is not None:`` and keep the feature-off path byte-for-byte
identical (AC-8).
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import lifecycle
import state_feature
import state_sync
import token_journal
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


def _drain_journal(ticket) -> list[str]:
    """KLC-119 (D-002/D-201/D-202): fold every attempt currently buffered in
    the ticket's journal into `meta.json:metrics.tokens`, returning the
    drained ids so the caller can `token_journal.consume` them once the
    write is durable (after a confirmed commit+push on the feature-ON
    branch; immediately on the feature-OFF branch, which has no push to
    wait for). Must run INSIDE `token_journal.scope(ticket)` so the writer
    routes straight into meta.json instead of re-buffering into the very
    journal being drained.

    `budget_guard` is imported here (function-local), not at module level:
    ADR-004 point 1 keeps `budget_guard` a leaf that never imports
    `state_tx`, and this keeps the DAG the same shape even though the
    reverse direction (state_tx -> budget_guard) would not itself cycle.
    """
    import budget_guard
    records = token_journal.read(ticket)
    if not records:
        return []
    ids: list[str] = []
    for rec in records:
        phase_id = rec.get("phase") or "unknown"
        # KLC-133 AC-9: forward every AC-8 key that is ACTUALLY present on
        # the journaled record (never a hard-coded all-keys set — a partial
        # key set must drain with the rest genuinely absent, test-plan-review
        # F-4), plus the original `ts` so the drain never re-stamps "now"
        # over a journaled attempt's real time (options F-104).
        extra = {k: rec[k] for k in budget_guard.ATTEMPT_OPTIONAL_KEYS if k in rec}
        budget_guard.write_token_metrics(
            ticket, phase_id,
            rec.get("in", 0), rec.get("out", 0), rec.get("cache_hit", 0),
            source=rec.get("source", "estimated"),
            card_bytes=rec.get("card_bytes"),
            step=rec.get("step"), attempt_id=rec.get("id"),
            reviewer=rec.get("reviewer"), ts=rec.get("ts"), **extra)
        ids.append(rec.get("id"))
    return ids


def _warn_drain_failed(ticket, exc: Exception) -> None:
    """C-003: telemetry never takes a verb down. One stderr line naming the
    journal path, so a repeated failure is diagnosable rather than merely
    quiet."""
    sys.stderr.write(
        f"telemetry: drain failed ({exc}); attempts kept in "
        f"{token_journal.journal_path(ticket)}\n")


@contextmanager
def state_tx(ticket, msg):
    kdir = klc_dir()
    if not state_feature.enabled():
        # D-201: feature-OFF is the headless runner's ONLY mode
        # (autorunner.run() refuses when the feature is ON) — the early
        # return here would otherwise mean the drain NEVER runs on that
        # path. This branch has no git, but it still owns the meta.json
        # write, so it drains too: under its OWN local snapshot, inside its
        # own try, truncating immediately on success (no push to wait for).
        # On failure it restores that snapshot, leaves the journal intact,
        # warns once and CONTINUES into the body — never fatal (C-003). The
        # snapshot/restore exist only on the drain path, so the normal
        # feature-OFF body keeps its current no-rollback semantics
        # (KLC-057 AC-8 stays byte-for-byte identical).
        snap = _snapshot_subtree(ticket, kdir)
        with token_journal.scope(ticket):
            try:
                drained = _drain_journal(ticket)
            except Exception as exc:
                _restore_subtree(snap, ticket, kdir)
                _warn_drain_failed(ticket, exc)
            else:
                try:
                    token_journal.consume(ticket, drained)
                except Exception:
                    pass        # a failed truncate costs one idempotent re-drain
            yield None
        return

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
    with token_journal.scope(ticket):
        with lifecycle.defer_jira_pushes() as pending:
            drained: list[str] = []
            try:
                # 5b. KLC-119 D-002/D-202: the drain sits INSIDE this same try,
                #     AFTER the snapshot (so a failure restores exactly like a
                #     body mutation) and in its OWN inner try, so a drain
                #     failure is restored and SWALLOWED — never propagated —
                #     and the verb still runs. This is the whole safety
                #     argument: the protection is what matters, not whether
                #     the failure is re-raised.
                try:
                    drained = _drain_journal(ticket)
                except Exception as exc:
                    _restore_subtree(snap, ticket, kdir)
                    # SCOPED reset: the unscoped one below (terminal failure)
                    # exists to clear a staged top-level `rm --cached` a drain
                    # never produces (the drain only writes meta.json, never
                    # touches git directly).
                    state_sync._git(
                        ["reset", "-q", "--", str(_subtree_root(ticket, kdir))],
                        kdir)
                    _warn_drain_failed(ticket, exc)
                    drained = []       # journal NOT truncated — retried next time
                # 6. The verb's whole mutating body runs here.
                yield _TxHandle()
                # 7. Glob-commit the ticket subtree + single CAS push. The remote is
                #    left to `commit_and_push_cas_subtree`, whose default now resolves
                #    to the branch's CONFIGURED upstream remote (KLC-069) — the remote
                #    `klc state init <remote>` bound klc-state to (e.g. `sm`), NOT a
                #    hardcoded `origin`. Resolving inside the CAS layer keeps state_tx
                #    from touching git directly (all git stays behind state_sync entry
                #    points) and closes the class for every caller, not one call site;
                #    it also takes the tested use_upstream @{upstream} CAS path rather
                #    than the other-remote FETCH_HEAD path.
                state_sync.commit_and_push_cas_subtree(ticket, msg, kdir)
            except Exception:
                # ANY terminal failure — StateConflictError, a first-grab
                # HolderConflictError, or a non-CAS sync error (RuntimeError/
                # ValueError/NothingToCommitError) — unwinds every local mutation the
                # body made so the local tree never diverges ahead of the untouched
                # remote, and the WHOLE index is reset so the next pull never hits a
                # dirty index. commit_and_push_cas_subtree leaves its aborted commit
                # STAGED via reset --soft, and that staged set includes the
                # `rm --cached` untracking of the shared derived cache
                # (knowledge/tickets-index.jsonl) which lives OUTSIDE tickets/<ticket>/
                # on an upgraded worktree (state_sync.py:523). A subtree-scoped reset
                # would leave that top-level staged deletion behind, contradicting the
                # rollback contract; an UNSCOPED `git reset` clears it too. This is
                # safe: stash-popped edits to other tickets and this ticket's snapshot
                # restore both live in the WORKING TREE, not the index, so an
                # index-only reset (no --hard) cannot destroy any in-progress work.
                # The collected Jira push is DISCARDED (not flushed). The exception
                # then propagates for a clean verb message.
                _restore_subtree(snap, ticket, kdir)
                state_sync._git(["reset", "-q"], kdir)
                raise
            # KLC-119: truncate the journal only AFTER a confirmed commit+push
            # — a rejected CAS or a crash before this point leaves the
            # attempts on disk for the next transaction (id-keyed idempotent
            # re-drain), never lost and never double-counted.
            try:
                token_journal.consume(ticket, drained)
            except Exception:
                pass    # a failed truncate costs one idempotent re-drain
    # 8. CAS push succeeded → NOW fire the deferred Jira push (never on rollback).
    lifecycle.flush_jira_pushes(pending)
