#!/usr/bin/env python3
"""`klc heartbeat` — keep an actively-held ticket alive against the steal TTL (KLC-064).

`heartbeat_holder` (KLC-058) refreshes `meta.holder.heartbeat_at` so the
`steal_holder` TTL gate measures staleness from a live timestamp instead of the
acquire time (`since`). Before this verb it had no production caller, so an agent
on a phase running longer than `HOLDER_TTL_SECONDS` (e.g. a long build) became
stealable while still working. This verb is that caller.

Design (see .klc/tickets/KLC-064/design.md):

- **Feature-OFF → pure no-op.** In single-user mode nobody steals, so a heartbeat
  has no value and MUST NOT write `meta.json` (byte-parity). The `state_feature`
  guard returns before any read.

- **Feature-ON → throttled propagation.** For each ticket the current identity
  holds in a `<phase>:work` state, `heartbeat_at` reaches origin (the `klc-state`
  branch) via a `state_tx` CAS-push — reusing the KLC-061 holder envelope, never a
  bare out-of-`state_tx` write. Propagation is THROTTLED to at most once per
  `holder.HEARTBEAT_PUSH_INTERVAL_SECONDS` per ticket: within that window the call
  is a read-only no-op (no write, no commit, no push), so the per-prompt hook adds
  no `klc-state` churn (KLC-062). `heartbeat_at` in the CAS-pushed `meta.holder`
  is BOTH the peer-visible liveness and the "last-pushed" throttle marker.

- **Advisory / best-effort.** Wired into a non-blocking UserPromptSubmit hook, so
  it ALWAYS returns 0 and swallows every error (missing identity, unreadable meta,
  absent holder, pull/push failure) — it must never crash or block the prompt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import holder  # noqa: E402
import identity as _identity  # noqa: E402
import lifecycle as _lc  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from _paths import klc_tickets_dir, project_root  # noqa: E402
from artefacts import acquire_lock  # noqa: E402


def _current_identity_or_none() -> str | None:
    """The acting identity, or None if it cannot be resolved.

    Uses the same source that WROTE the holder (`identity.current()` →
    `git config user.email`) so the comparison against `holder.id` is exact, but
    swallows the `SystemExit` that `identity.current()` raises when nothing is
    configured — the advisory hook degrades to silence rather than crashing.
    """
    try:
        return _identity.current()
    except BaseException:
        return None


def _held_work_tickets(identity: str):
    """Yield ticket ids the given identity holds in a `<phase>:work` state.

    Read-only: uses `read_meta_ro` so the throttle probe never persists a
    legacy-phase migration (KLC-062). Any unreadable/corrupt ticket is skipped.
    """
    tickets_dir = klc_tickets_dir()
    if not tickets_dir.exists():
        return
    for tdir in sorted(tickets_dir.iterdir()):
        if not tdir.is_dir() or not (tdir / "meta.json").exists():
            continue
        ticket = tdir.name
        try:
            meta = _lc.read_meta_ro(ticket)
        except Exception:
            continue
        h = meta.get("holder")
        if not isinstance(h, dict) or h.get("id") != identity:
            continue
        phase = meta.get("phase", "")
        if not isinstance(phase, str) or not phase.endswith(":work"):
            continue
        yield ticket, h


def _within_window(h: dict) -> bool:
    """True iff the holder's liveness (heartbeat_at, else since) is younger than
    the throttle window — i.e. a propagation would be premature. An unusable
    liveness stamp falls through to False so we propagate a fresh one to fix it."""
    try:
        return holder._holder_age_seconds(h) < holder.HEARTBEAT_PUSH_INTERVAL_SECONDS
    except ValueError:
        return False


def _propagate(ticket: str, identity: str) -> None:
    """Refresh + CAS-push this ticket's heartbeat_at through the state_tx envelope.

    Ownership can change under us between the throttle probe and the in-tx pull:
    a peer may steal the ticket. TWO guards make that safe, in order:

      * state_tx's post-pull stale-guard (PRIMARY steal guard): a concurrent
        steal advances the ticket subtree hash, so state_tx raises
        `StaleStateError` BEFORE this body runs — the heartbeat never touches the
        stolen holder.
      * an in-body ownership re-check (defense-in-depth): `heartbeat_holder`
        refreshes WHOEVER holds, so we re-read the pulled meta and only refresh
        when we still hold it (id == identity, `<phase>:work`, still out-of-window).
        If it does not hold we write nothing, so state_tx raises
        `NothingToCommitError` (same-holder / no-delta no-op).

    The broad `except Exception: pass` below is LOAD-BEARING — do NOT narrow it to
    `except NothingToCommitError`. It must swallow `StaleStateError` (the steal
    path), `NothingToCommitError` (the no-op path), and any pull / CAS-push failure
    so the advisory hook stays best-effort and always returns 0 (AC-4). Narrowing
    it would let a concurrent steal crash the verb with a traceback.
    """
    with acquire_lock(ticket):
        try:
            with state_tx.state_tx(ticket, f"heartbeat {ticket}") as tx:
                if tx is None:
                    return  # feature turned off between guard and here → no-op
                meta = _lc.read_meta_ro(ticket)
                h = meta.get("holder")
                if (isinstance(h, dict) and h.get("id") == identity
                        and isinstance(meta.get("phase"), str)
                        and meta["phase"].endswith(":work")
                        and not _within_window(h)):
                    holder.heartbeat_holder(ticket)
                # else: nothing to write → NothingToCommitError on exit (swallowed)
        except state_sync.NothingToCommitError:
            pass
        except Exception:
            # LOAD-BEARING (see docstring): StaleStateError from a concurrent
            # steal, plus any pull/CAS-push failure — all swallowed so the hook
            # never crashes. Do not narrow this.
            pass


def run(argv: list[str]) -> int:
    """Throttled, feature-ON heartbeat for every identity-held :work ticket.

    ALWAYS returns 0 (advisory). Feature-OFF and within-window calls are pure
    no-ops. `argv` is accepted for CLI/hook uniformity and ignored.
    """
    prev_cwd = None
    try:
        # FIX-3: getcwd is guarded — a deleted/unreadable process cwd must not
        # crash the advisory verb (AC-4). None → the finally restore is skipped.
        try:
            prev_cwd = os.getcwd()
        except Exception:
            prev_cwd = None
        # Feature-OFF: nobody steals in single-user mode → hard no-op, byte parity.
        if not state_feature.enabled():
            return 0
        # Match remind: run from the project root so the identity and meta reads
        # target the project repo regardless of the hook's cwd. Restored in finally.
        try:
            os.chdir(project_root())
        except Exception:
            return 0
        identity = _current_identity_or_none()
        if not identity:
            return 0
        for ticket, h in _held_work_tickets(identity):
            # FIX-1: the WHOLE per-ticket unit (incl. acquire_lock) is best-effort.
            # One locked/failing ticket (e.g. a live peer process holds its .lock)
            # must NOT abort the scan and starve later identity-held :work tickets
            # of their heartbeat — that would let an unrelated active holder go
            # stale and become stealable. Skip the offender, keep scanning.
            try:
                if _within_window(h):
                    continue  # throttled: no write, no commit, no push (no churn)
                _propagate(ticket, identity)
            except Exception:
                continue
        return 0
    except Exception:
        return 0
    finally:
        if prev_cwd is not None:
            try:
                os.chdir(prev_cwd)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
