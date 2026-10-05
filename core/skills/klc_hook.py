#!/usr/bin/env python3
"""klc_hook.py — the logic behind the single UserPromptSubmit hook (KLC-180).

The hook script stays thin; everything it decides lives here so it can be
tested without spawning the hook:

  active_ticket(cwd, tickets_dir)  which ticket the operator is working on
  pending_line(ticket)             one line when the ticket waits for a human
  held_tickets(identity)           every `:work` ticket this identity holds
  heartbeat_due(ticket, now)       whether a heartbeat push is worth a process
  refresh_heartbeat(ticket)        the heartbeat push itself (runs detached)
  spawn_heartbeat(ticket)          start that push in a detached process

Why one module: `remind` and `heartbeat` used to be two verbs, each scanning
every ticket on every prompt. The hook now picks ONE ticket and asks the three
cheap questions about it.

Unusual point: every public function is fail-safe. A hook must never block or
crash a prompt, so any error becomes "nothing to say" (None / False).
`refresh_heartbeat` is the `heartbeat` verb's logic moved here unchanged
(the broad `except` in `_propagate` is load-bearing, see its docstring).
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import holder  # noqa: E402
import identity as _identity  # noqa: E402
import lifecycle as _lc  # noqa: E402
import next_move as _nm  # noqa: E402
import phases as _ph  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
import ticket_id as _tid  # noqa: E402
from _paths import project_root  # noqa: E402
from artefacts import acquire_lock  # noqa: E402


def _identity_or_none() -> str | None:
    """The acting identity, or None. `identity.current()` raises SystemExit when
    nothing is configured; the hook degrades to silence instead."""
    try:
        return _identity.current()
    except BaseException:
        return None


def _meta_or_none(ticket: str) -> dict | None:
    """Read-only meta (never persists a legacy-phase migration), or None."""
    try:
        meta = _lc.read_meta_ro(ticket)
    except Exception:
        return None
    return meta if isinstance(meta, dict) else None


def _is_live(meta: dict) -> bool:
    phase = meta.get("phase")
    return isinstance(phase, str) and phase.split(":", 1)[0] not in _ph.TERMINAL_STATES


def _branch(cwd) -> str:
    # symbolic-ref also answers on an unborn branch (a fresh repo, no commit yet),
    # where `rev-parse --abbrev-ref HEAD` fails.
    r = subprocess.run(["git", "-C", str(cwd), "symbolic-ref", "--short", "-q", "HEAD"],
                       capture_output=True, text=True, timeout=1)
    return r.stdout.strip() if r.returncode == 0 else ""


def active_ticket(cwd, tickets_dir) -> str | None:
    """The ticket the operator is on: the checked-out `feature/<key>-*` branch,
    else the single live ticket held by this identity, else None. Never raises."""
    try:
        tickets = Path(tickets_dir)
        branch = _branch(cwd)
        if branch.startswith("feature/"):
            # Keys are upper-case in the pattern, branches are lower-case.
            for key in _tid.find_keys(branch.split("/", 1)[1].upper()):
                if (tickets / key / "meta.json").exists():
                    meta = _meta_or_none(key)
                    if meta is not None and _is_live(meta):
                        return key
        me = _identity_or_none()
        if not me or not tickets.is_dir():
            return None
        held = []
        for tdir in sorted(tickets.iterdir()):
            if not (tdir / "meta.json").exists():
                continue
            meta = _meta_or_none(tdir.name)
            h = meta.get("holder") if meta else None
            if meta and _is_live(meta) and isinstance(h, dict) and h.get("id") == me:
                held.append(tdir.name)
        return held[0] if len(held) == 1 else None
    except BaseException:
        return None


def pending_line(ticket: str) -> str | None:
    """One line when the ticket waits for a human (a decision, an `:ack-needed`,
    or a finished `:work`); None when nothing is pending. Read-only: it reuses
    `next_move.compute`, which never writes."""
    try:
        move = _nm.compute(ticket)
        if move.action == "pick":
            what = "waits for your decision"
            return (f"{ticket} {move.phase}: {what} — run /klc:go {ticket} --pick N "
                    f"(CLI: klc go {ticket} --pick N)")
        if move.state == _ph.STATE_ACK_NEEDED:
            return f"{ticket} {move.phase}: waits for your ack — run /klc:go {ticket}"
        if move.state == _ph.STATE_WORK and move.action == "ack":
            return f"{ticket} {move.phase}: is done — run /klc:go {ticket}"
        return None
    except BaseException:
        return None


def _within_window(h: dict, now: _dt.datetime | None = None) -> bool:
    """True iff the holder's liveness (heartbeat_at, else since) is younger than
    the throttle window. An unusable stamp is False so a fresh one is pushed."""
    try:
        if now is None:
            age = holder._holder_age_seconds(h)
        else:
            age = None
            for ref in (h.get("heartbeat_at"), h.get("since")):
                try:
                    age = (now - holder._parse_iso_z(ref)).total_seconds()
                    break
                except ValueError:
                    continue
            if age is None:
                return False
        return age < holder.HEARTBEAT_PUSH_INTERVAL_SECONDS
    except ValueError:
        return False


def _held_work(ticket: str, me: str) -> dict | None:
    """The holder dict when `me` holds `ticket` in a `<phase>:work` state."""
    meta = _meta_or_none(ticket)
    if not meta:
        return None
    h = meta.get("holder")
    phase = meta.get("phase")
    if (isinstance(h, dict) and h.get("id") == me
            and isinstance(phase, str) and phase.endswith(":work")):
        return h
    return None


def held_tickets(identity: str | None, tickets_dir=None) -> list[str]:
    """Every live ticket `identity` holds in a `<phase>:work` state (the retired
    `klc heartbeat` refreshed all of them, not one). Never raises."""
    try:
        if not identity:
            return []
        tickets = Path(tickets_dir) if tickets_dir else project_root() / ".klc" / "tickets"
        if not tickets.is_dir():
            return []
        return [t.name for t in sorted(tickets.iterdir())
                if (t / "meta.json").exists() and _held_work(t.name, identity) is not None
                and _is_live(_meta_or_none(t.name) or {})]
    except BaseException:
        return []


def heartbeat_due(ticket: str, now: _dt.datetime | None = None) -> bool:
    """Feature ON, this identity holds the ticket in `:work`, and the last
    heartbeat is older than the window. Never raises."""
    try:
        if not state_feature.enabled():
            return False
        me = _identity_or_none()
        h = _held_work(ticket, me) if me else None
        if h is None:
            return False
        return not _within_window(h, now)
    except BaseException:
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
    so the advisory hook stays best-effort and always returns 0. Narrowing
    it would let a concurrent steal crash the process with a traceback.
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
            # steal, plus any pull/CAS-push failure. Do not narrow this.
            pass


def refresh_heartbeat(ticket: str) -> None:
    """Throttled, feature-ON heartbeat push for one ticket; callable in a detached
    process. Feature OFF and within-window calls are pure no-ops (byte parity,
    KLC-062 no-churn). Never raises; restores the caller's cwd."""
    prev_cwd = None
    try:
        try:
            prev_cwd = os.getcwd()
        except Exception:
            prev_cwd = None
        if not state_feature.enabled():
            return
        # Run from the project root so identity and meta reads target the project
        # repo regardless of the hook's cwd.
        os.chdir(project_root())
        me = _identity_or_none()
        h = _held_work(ticket, me) if me else None
        if h is None or _within_window(h):
            return
        _propagate(ticket, me)
    except BaseException:
        return
    finally:
        if prev_cwd is not None:
            try:
                os.chdir(prev_cwd)
            except Exception:
                pass


def spawn_heartbeat(ticket: str) -> None:
    """Start `refresh_heartbeat(ticket)` in a detached process and return at once.

    The push does git network work that can take seconds, and the hook has a
    two-second budget, so the hook never waits for it. A new session keeps the
    child alive after the hook exits. Never raises."""
    try:
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import klc_hook; "
                "klc_hook.refresh_heartbeat(sys.argv[2])")
        subprocess.Popen([sys.executable, "-c", code, str(_SKILLS), ticket],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True)
    except BaseException:
        return


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("klc_hook.py is a library module; import it, don't run it")
