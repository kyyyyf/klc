#!/usr/bin/env python3
"""lifecycle.py — ticket state machine over config/phases.yml.

Each ticket's `meta.json:phase` holds `"<phase-id>:<state>"`, where
state ∈ {work, ack-needed, ack}, plus the terminal sentinel `archived`.

Transitions happen via five operations:

  set_state(ticket, phase_id, state)
    Low-level: write meta.json and append a phase_history entry.

  advance_to_next(ticket)
    From `:ack` (or `intake:ack-needed` at ticket creation) → next
    track-applicable phase's `:work` state.

  apply_ack(ticket, pick_id)
    From `:ack-needed` → goto target (either `next` or `<phase>:work`).
    Honours supersede lists and pick_records_to.

  jump(ticket, target_phase, pick_id=None, dry_run=False)
    Cross-cut: from any `:ack` state to any other phase's `:work`.
    Always resets budget counters; optionally supersedes downstream.

  abort(ticket)
    From `:work` → previous `:ack` (or `intake:ack-needed` if first).
    Supersedes current phase artefacts.

Old-format meta.json (lifecycle states like `discovery-running`,
`build-pending`) is auto-migrated on read via _migrate_legacy_phase.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import shutil
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # core/skills -> core -> project root
sys.path.insert(0, str(_project_root))

from core.shared.paths import klc_ticket_dir, klc_ticket_meta_file  # noqa: E402
import phases as _ph  # noqa: E402


# --- legacy migration --------------------------------------------------------

# Old lifecycle state → new `<phase-id>:<state>` mapping. One-shot on
# read: if a ticket's meta.json still has an old value, rewrite it.
_LEGACY_MAP = {
    "intake":                     "intake:ack-needed",
    "discovery-running":          "discovery:work",
    "discovery-pending-ack":      "discovery:ack-needed",
    "test-plan-pending":          "acceptance-test-plan:work",
    "design-pending":             "design:work",
    "design-pending-ack":         "design:ack-needed",
    "detailed-test-plan-pending": "detailed-test-plan:work",
    "build-pending":              "build:work",
    "review-pending":             "review:work",
    "review-pending-ack":         "review:ack-needed",
    "manual-pending":             "manual:work",
    "manual-pending-ack":         "manual:ack-needed",
    "integrate-pre":              "integrate:work",
    "integrate-post":             "integrate:work",
    "observe":                    "observe:work",
    "learn":                      "learn:work",
    "archived":                   "archived",
}


def _migrate_legacy_phase(meta: dict) -> bool:
    """If meta has an old-format phase string, rewrite it in place.
    Returns True iff migration happened (caller should persist)."""
    cur = meta.get("phase")
    if not isinstance(cur, str):
        return False
    if ":" in cur or cur == _ph.STATE_ARCHIVED:
        return False
    new = _LEGACY_MAP.get(cur)
    if new:
        meta["phase"] = new
        return True
    return False


# --- I/O ----------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_meta(ticket: str) -> dict:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        raise FileNotFoundError(
            f"ticket {ticket!r} has no meta.json; run `klc intake` first"
        )
    meta = json.loads(p.read_text(encoding="utf-8"))
    if _migrate_legacy_phase(meta):
        write_meta(ticket, meta)
    return meta


def write_meta(ticket: str, meta: dict) -> None:
    p = klc_ticket_meta_file(ticket)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def current_state(ticket: str) -> str:
    return read_meta(ticket).get("phase", "intake:ack-needed")


# Holder liveness (KLC-058). AC-2 documents these on the `lifecycle` interface,
# but the real implementations live in holder.py (which layers on read_meta /
# write_meta). These are thin delegating wrappers so both
# `lifecycle.heartbeat_holder(...)` and `holder.heartbeat_holder(...)` work with
# NO duplicated logic. The `from holder import ...` is FUNCTION-LEVEL on purpose:
# holder.py imports this module at module load, so a top-level import here would
# be a cycle.
def heartbeat_holder(ticket: str):
    """Delegate to holder.heartbeat_holder (see holder.py)."""
    from holder import heartbeat_holder as _impl
    return _impl(ticket)


def steal_holder(ticket: str, identity: dict, *args, **kwargs):
    """Delegate to holder.steal_holder (see holder.py)."""
    from holder import steal_holder as _impl
    return _impl(ticket, identity, *args, **kwargs)


# --- low-level state write ----------------------------------------------------

# --- Jira push deferral (KLC-057 P1: order after the CAS push) ----------------
# While `defer_jira_pushes()` is active (set by `state_tx` around a feature-on
# op), `set_state` COLLECTS the intended Jira transition instead of firing it
# immediately. `state_tx` flushes the collected transition ONLY after
# `commit_and_push_cas_subtree` succeeds — and never on rollback — so a rejected
# / conflicting CAS push can no longer leave Jira advanced ahead of klc.
_jira_deferral: "list | None" = None


@contextlib.contextmanager
def defer_jira_pushes():
    """Collect Jira pushes instead of firing them; yields the collection list.
    Save/restore the previous state so nested use (e.g. ack manual-completion
    then its recursion) is safe."""
    global _jira_deferral
    prev = _jira_deferral
    _jira_deferral = []
    try:
        yield _jira_deferral
    finally:
        _jira_deferral = prev


def flush_jira_pushes(pending) -> None:
    """Fire the deferred Jira push for the FINAL collected transition exactly
    once, after a successful CAS push. Intermediate transitions within one atomic
    op (e.g. ack's :ack then :work) collapse to the net phase. Never raises."""
    if not pending:
        return
    ticket, phase, source = pending[-1]
    try:
        _jira_push_after_state(ticket, phase, source=source)
    except Exception as _e:
        sys.stderr.write(f"[jira-sync] non-fatal: {_e}\n")


def _jira_push_after_state(ticket: str, phase: str, *, source: str) -> None:
    """Dispatch Jira sync after a state write.

    mirror mode → legacy auto-push (unchanged behaviour).
    managed mode → interactive prompt (TTY) or record-divergence (non-TTY),
                   but ONLY for ack/next decision points (source in
                   {"ack", "advance", "set_state"}).
                   abort/jump bypass the interactive path — they are
                   internal lifecycle operations, not human decision points.
    Never raises — all errors are warnings.
    """
    # D-001: managed prompts only at ack/next decision points.
    # abort and jump are internal operations — mirror-push only.
    # jira-pull / jira-force-pull are Jira→klc moves: suppress ALL Jira push
    # to avoid circular klc→Jira push triggered by an incoming pull.
    _NO_PUSH_SOURCES = {"jira-pull", "jira-force-pull"}
    if source in _NO_PUSH_SOURCES:
        return

    _MANAGED_SOURCES = {"ack", "advance", "set_state"}

    try:
        from jira_config import load as _load_cfg
        cfg = _load_cfg()
        if not cfg.enabled:
            return
    except Exception:
        # Config unavailable or disabled — fall through to legacy path
        try:
            import jira_sync as _js
            _js.push_phase(ticket, phase, source=source)
        except Exception as _e2:
            sys.stderr.write(f"[jira-sync] non-fatal: {_e2}\n")
        return

    if (cfg.mode == "mirror"
            or not cfg.is_managed_ticket(ticket)
            or source not in _MANAGED_SOURCES):
        # Mirror mode, non-managed ticket, or non-decision-point event:
        # auto-push (legacy behaviour).
        try:
            import jira_sync as _js
            _js.push_phase(ticket, phase, source=source)
        except Exception as _e:
            sys.stderr.write(f"[jira-sync] non-fatal: {_e}\n")
        return

    # Managed mode: interactive or record-divergence
    _managed_jira_push(ticket, phase, cfg)


def _managed_jira_push(ticket: str, phase: str, cfg: Any) -> None:
    """Handle Jira sync in managed mode: prompt if TTY, record if not."""
    try:
        from jira_client import make_client
        from jira_sync import build_plan, push_to_jira, _record_conflict_in_meta, _now
        client = make_client(cfg)
        plan = build_plan(ticket, client, cfg)
    except Exception as exc:
        sys.stderr.write(f"[jira] managed sync unavailable: {exc}\n")
        return

    if plan.in_sync:
        return  # Nothing to do, no prompt needed

    is_tty = sys.stdin.isatty() and sys.stdout.isatty()

    if plan.has_conflict("jira-moved-externally"):
        # PM moved Jira — three-option conflict prompt
        if is_tty:
            _prompt_conflict(ticket, plan, client, cfg)
        else:
            _record_divergence_non_tty(ticket, plan)
    else:
        # klc moved, Jira is behind
        if is_tty:
            _prompt_klc_moved(ticket, plan, client, cfg)
        else:
            _record_divergence_non_tty(ticket, plan)


def _prompt_klc_moved(ticket: str, plan: "SyncPlan",  # type: ignore[name-defined]
                       client: Any, cfg: Any) -> None:
    """Prompt: push Jira to match klc, or leave as-is."""
    from jira_sync import push_to_jira
    sys.stderr.write(
        f"\n[jira] {ticket}: klc moved to {plan.klc_phase!r}, "
        f"Jira is {plan.jira_status!r}.\n"
        f"  1) Push Jira → {plan.target_status!r}  (recommended)\n"
        f"  2) Leave Jira as-is\n"
        f"  [1/2, default=1]: "
    )
    try:
        choice = input().strip() or "1"
    except EOFError:
        choice = "2"

    if choice == "1":
        result = push_to_jira(ticket, client, cfg)
        if result["ok"]:
            sys.stderr.write(f"[jira] {result['detail']}\n")
        else:
            sys.stderr.write(f"[jira] push failed: {result['detail']}\n")


def _prompt_conflict(ticket: str, plan: "SyncPlan",  # type: ignore[name-defined]
                      client: Any, cfg: Any) -> None:
    """Prompt: Jira changed externally — three options.

    AC-7 (KLC-022): when Jira moved BACKWARD (rework signal), option 1 becomes
    pull klc→target from jira_to_klc candidates instead of push Jira back.
    """
    from jira_sync import push_to_jira, _record_conflict_in_meta, _now
    import phases as _ph

    # Detect backward direction: Jira status maps to phases earlier than current
    is_backward = False
    pull_candidates: list[str] = []
    if plan.jira_status:
        candidates = (cfg.jira_to_klc or {}).get(plan.jira_status, [])
        if candidates:
            try:
                meta = read_meta(ticket)
                track = meta.get("track") or "M"
                track_ids = [p.id for p in _ph.load_phases().track_phases(track)]
                cur_id = (plan.klc_phase.split(":")[0]
                          if ":" in plan.klc_phase else plan.klc_phase)
                cur_idx = track_ids.index(cur_id) if cur_id in track_ids else -1
                pull_candidates = [c for c in candidates
                                   if c in track_ids
                                   and track_ids.index(c) < cur_idx]
                is_backward = bool(pull_candidates)
            except Exception:
                pass

    if is_backward:
        candidates_str = ", ".join(pull_candidates)
        sys.stderr.write(
            f"\n[jira] CONFLICT: {ticket} Jira moved to {plan.jira_status!r} "
            f"(possible rework signal).\n"
            f"  klc is at {plan.klc_phase!r}.\n"
            f"  1) Accept rework: pull klc → one of [{candidates_str}]\n"
            f"  2) Reject: push Jira back → {plan.target_status!r}  (klc wins)\n"
            f"  3) Skip — write [!CONFLICT] to meta, show in doctor\n"
            f"  [1/2/3, default=3]: "
        )
    else:
        sys.stderr.write(
            f"\n[jira] CONFLICT: {ticket} Jira changed from "
            f"{plan.last_jira_status!r} → {plan.jira_status!r} outside klc.\n"
            f"  klc is at {plan.klc_phase!r}, wants Jira at {plan.target_status!r}.\n"
            f"  1) Push Jira back → {plan.target_status!r}  (klc wins)\n"
            f"  2) Keep Jira at {plan.jira_status!r}, record divergence\n"
            f"  3) Skip — write [!CONFLICT] to meta, show in doctor\n"
            f"  [1/2/3, default=3]: "
        )

    try:
        choice = input().strip() or "3"
    except EOFError:
        choice = "3"

    if choice == "1":
        if is_backward and pull_candidates:
            # Ask which candidate to pull to
            if len(pull_candidates) == 1:
                target = pull_candidates[0]
            else:
                sys.stderr.write(
                    f"  Choose target phase: {pull_candidates}\n  Phase name: "
                )
                try:
                    target = input().strip()
                except EOFError:
                    target = pull_candidates[0]
            sys.stderr.write(
                f"  This will supersede artefacts from {target!r} onward. Confirm? [y/N]: "
            )
            try:
                confirm = input().strip().lower()
            except EOFError:
                confirm = "n"
            if confirm == "y":
                from jira_sync import pull as _jira_pull
                result = _jira_pull(ticket, target,
                                    reason=f"rework: Jira moved to {plan.jira_status!r}")
                if result["ok"]:
                    sys.stderr.write(f"[jira] {result['detail']}\n")
                else:
                    sys.stderr.write(f"[jira] pull failed: {result['detail']}\n")
            else:
                sys.stderr.write("[jira] Pull cancelled.\n")
        else:
            result = push_to_jira(ticket, client, cfg)
            if result["ok"]:
                sys.stderr.write(f"[jira] {result['detail']}\n")
            else:
                sys.stderr.write(f"[jira] push failed: {result['detail']}\n")
    elif choice == "2":
        if is_backward:
            # "2" = reject, push Jira back
            result = push_to_jira(ticket, client, cfg)
            if result["ok"]:
                sys.stderr.write(f"[jira] {result['detail']}\n")
            else:
                sys.stderr.write(f"[jira] push failed: {result['detail']}\n")
        else:
            _record_conflict_in_meta(ticket, {
                "type": "jira-moved-externally",
                "detail": plan.conflicts[0]["detail"] if plan.conflicts else "divergence",
                "detected_at": _now(),
                "suggested": f"klc jira reconcile {ticket} push",
            })
            sys.stderr.write("[jira] Divergence recorded in meta.jira_sync.conflicts\n")
    else:
        _record_conflict_in_meta(ticket, {
            "type": "jira-moved-externally",
            "detail": plan.conflicts[0]["detail"] if plan.conflicts else "divergence",
            "detected_at": _now(),
            "suggested": f"klc jira reconcile {ticket} push",
        })
        sys.stderr.write(
            "[jira] [!CONFLICT] recorded. Run `klc doctor` to see conflicts.\n"
        )


def _record_divergence_non_tty(ticket: str, plan: "SyncPlan") -> None:  # type: ignore[name-defined]
    """Non-TTY: record divergence in meta, warn to stderr. Never push."""
    from jira_sync import _record_conflict_in_meta, _now
    sys.stderr.write(
        f"[jira] managed non-TTY: {ticket} divergence detected "
        f"(klc={plan.klc_phase!r}, Jira={plan.jira_status!r}). "
        f"Run `klc jira sync {ticket}` to review.\n"
    )
    _record_conflict_in_meta(ticket, {
        "type": "jira-moved-externally" if plan.has_conflict("jira-moved-externally")
                 else "klc-ahead",
        "detail": (f"klc at {plan.klc_phase!r}, Jira at {plan.jira_status!r}, "
                   f"target {plan.target_status!r}"),
        "detected_at": _now(),
        "suggested": f"klc jira reconcile {ticket} push",
    })


def set_state(ticket: str, phase_id: str, state: str, *,
              event: str = "set_state", note: str = "",
              extra: dict | None = None) -> None:
    meta = read_meta(ticket)
    new = _ph.format_state(phase_id, state)
    history = meta.setdefault("phase_history", [])
    if history and "finished_at" not in history[-1]:
        history[-1]["finished_at"] = _now()
    entry = {"phase": new, "started_at": _now(), "event": event}
    if note:
        entry["note"] = note
    if extra:
        entry.update(extra)
    history.append(entry)
    meta["phase"] = new
    write_meta(ticket, meta)
    if _jira_deferral is not None:
        # Inside a state_tx: defer until the CAS push confirms (P1). Skipped
        # entirely if the tx rolls back — no Jira/klc divergence.
        _jira_deferral.append((ticket, new, event))
    else:
        try:
            _jira_push_after_state(ticket, new, source=event)
        except Exception as _e:
            sys.stderr.write(f"[jira-sync] non-fatal: {_e}\n")


def jira_pull(ticket: str, target_phase: str, *,
              jira_status: str,
              force: bool = False,
              reason: str | None = None,
              missing_artifacts: list[str] | None = None,
              skipped_phases: list[str] | None = None) -> str:
    """Move klc to target_phase with Jira provenance.

    Uses a dedicated event type (jira-pull / jira-force-pull) so the move
    is auditable and distinguishable from normal ack/jump operations.
    Does NOT route through the normal ack/picks path.
    Returns the new full phase:state string.
    """
    event = "jira-force-pull" if force else "jira-pull"
    extra: dict = {
        "jira_status": jira_status,
        "target_phase": target_phase,
        "missing_artifacts": missing_artifacts or [],
        "skipped_phases": skipped_phases or [],
    }
    if reason:
        extra["note"] = reason
    set_state(ticket, target_phase, _ph.STATE_WORK, event=event, extra=extra)
    return _ph.format_state(target_phase, _ph.STATE_WORK)


# --- superseding downstream artefacts ----------------------------------------

def supersede_phases(ticket: str, phase_ids: list[str]) -> list[Path]:
    """Move each phase's artefacts to _superseded/<ts>/<phase>/.
    Artefacts are resolved from phases.yml outputs[] + the phase-named
    sub-directory (e.g. design/). Returns the list of moved paths."""
    if not phase_ids:
        return []
    ph = _ph.load_phases()
    tdir = klc_ticket_dir(ticket)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_root = tdir / "_superseded" / ts
    moved: list[Path] = []
    for pid in phase_ids:
        try:
            p = ph.by_id(pid)
        except KeyError:
            continue
        # Paths to consider: each output file + the phase's own
        # sub-directory (e.g. discovery/, design/) if it exists.
        targets: list[Path] = []
        for out in p.outputs:
            t = tdir / out
            if t.exists():
                targets.append(t)
        phase_subdir = tdir / pid
        if phase_subdir.is_dir():
            targets.append(phase_subdir)
        if not targets:
            continue
        bucket = dest_root / pid
        bucket.mkdir(parents=True, exist_ok=True)
        for t in targets:
            dest = bucket / t.name
            shutil.move(str(t), str(dest))
            moved.append(dest)
    if moved:
        meta = read_meta(ticket)
        rec = meta.setdefault("superseded", [])
        rec.append({
            "at":     _now(),
            "phases": phase_ids,
            "dir":    str(dest_root.relative_to(tdir)),
        })
        write_meta(ticket, meta)
    return moved


def _reset_budgets(meta: dict) -> None:
    """Zero every counter in meta.budgets. Jump/abort reset all."""
    budgets = meta.get("budgets")
    if isinstance(budgets, dict):
        for k in list(budgets.keys()):
            budgets[k] = 0


# --- operations ---------------------------------------------------------------

def advance_to_next(ticket: str, *, note: str = "") -> str:
    """Move from `<X>:ack` to the next track-applicable phase's `:work`.
    Phases whose `condition` evaluates to False are skipped automatically
    (recorded in phase_history as event=skipped).
    Returns the new state string. Raises if not in an `:ack` state."""
    meta = read_meta(ticket)
    cur = meta.get("phase", "")
    if cur == _ph.STATE_ARCHIVED:
        raise ValueError("ticket is archived; no further transitions")
    pid, st = _ph.parse_state(cur)
    if st != _ph.STATE_ACK:
        raise ValueError(
            f"advance_to_next: current state is {cur!r}; expected an :ack state"
        )
    track = meta.get("track") or "M"
    ph = _ph.load_phases()

    # Walk forward, skipping phases whose condition is not met.
    candidate_pid = pid
    while True:
        nxt = ph.next_phase(track, candidate_pid)
        if nxt is None:
            set_state(ticket, _ph.STATE_ARCHIVED, _ph.STATE_ARCHIVED,
                      event="advance", note=note or "terminal")
            return _ph.STATE_ARCHIVED
        meta = read_meta(ticket)
        if nxt.should_run(meta):
            break
        # Skip this phase — record it.
        _record_skipped(ticket, nxt.id, nxt.condition or "")
        candidate_pid = nxt.id

    set_state(ticket, nxt.id, _ph.STATE_WORK, event="advance", note=note)
    return _ph.format_state(nxt.id, _ph.STATE_WORK)


def _record_skipped(ticket: str, phase_id: str, reason: str) -> None:
    """Append a skipped event to phase_history without changing phase."""
    meta = read_meta(ticket)
    history = meta.setdefault("phase_history", [])
    if history and "finished_at" not in history[-1]:
        history[-1]["finished_at"] = _now()
    history.append({
        "phase":      _ph.format_state(phase_id, _ph.STATE_WORK),
        "started_at": _now(),
        "event":      "skipped",
        "note":       f"condition not met: {reason}",
        "finished_at": _now(),
    })
    write_meta(ticket, meta)


def apply_ack(ticket: str, pick_id: int | None) -> str:
    """From :ack-needed apply the selected pick. Returns new state."""
    meta = read_meta(ticket)
    cur = meta.get("phase", "")
    pid, st = _ph.parse_state(cur)
    if st != _ph.STATE_ACK_NEEDED:
        raise ValueError(
            f"apply_ack: current state is {cur!r}; expected :ack-needed"
        )
    ph = _ph.load_phases()
    phase = ph.by_id(pid)

    if phase.pick_required and pick_id is None:
        opts = ", ".join(f"{pk.id}={pk.label}" for pk in phase.picks)
        raise ValueError(f"pick required for {pid}:ack-needed; options: {opts}")

    if pick_id is None:
        if len(phase.picks) != 1:
            opts = ", ".join(f"{pk.id}={pk.label}" for pk in phase.picks)
            raise ValueError(f"pick required (ambiguous); options: {opts}")
        pick = phase.picks[0]
    else:
        pick = phase.pick_by_id(pick_id)
        if pick is None:
            opts = ", ".join(f"{pk.id}={pk.label}" for pk in phase.picks)
            raise ValueError(f"unknown pick {pick_id} for {pid}; options: {opts}")

    # Record pick if configured.
    if phase.pick_records_to:
        meta[phase.pick_records_to] = pick.label
        write_meta(ticket, meta)

    # Move to `<pid>:ack` first (so the ack is auditable even if the
    # subsequent goto immediately overwrites it).
    set_state(ticket, pid, _ph.STATE_ACK,
              event="ack", note=f"pick={pick.id}:{pick.label}")

    # Supersede if requested.
    if pick.supersede:
        supersede_phases(ticket, pick.supersede)

    if pick.goto == "next":
        return advance_to_next(ticket, note=f"ack:{pick.label}")

    if pick.goto == _ph.STATE_ARCHIVED:
        set_state(ticket, _ph.STATE_ARCHIVED, _ph.STATE_ARCHIVED,
                  event="ack", note=f"pick={pick.label}")
        return _ph.STATE_ARCHIVED

    # Explicit <phase>:<state> jump.
    tgt_id, tgt_state = _ph.parse_state(pick.goto)
    meta = read_meta(ticket)
    _reset_budgets(meta)
    write_meta(ticket, meta)
    set_state(ticket, tgt_id, tgt_state,
              event="ack-jump", note=f"pick={pick.label}")
    return pick.goto


def jump(ticket: str, target_phase: str, *, dry_run: bool = False) -> dict:
    """Cross-cut jump to `<target_phase>:work`. Always from some `:ack`.
    Returns a plan dict regardless of dry_run; when dry_run=False the
    plan has been applied."""
    meta = read_meta(ticket)
    cur = meta.get("phase", "")
    if cur == _ph.STATE_ARCHIVED:
        raise ValueError("cannot jump from archived")
    cur_pid, cur_state = _ph.parse_state(cur)
    if cur_state != _ph.STATE_ACK:
        raise ValueError(
            f"jump requires current state to be :ack; got {cur!r}. "
            f"Use `klc abort` to leave :work or `klc ack` to leave :ack-needed."
        )

    ph = _ph.load_phases()
    track = meta.get("track") or "M"
    track_ids = [p.id for p in ph.track_phases(track)]

    # Target must exist.
    try:
        tgt = ph.by_id(target_phase)
    except KeyError:
        raise ValueError(f"unknown target phase {target_phase!r}")
    if target_phase not in track_ids:
        # Not in track — warn, don't block.
        pass

    # Determine direction and downstream to supersede (only for
    # backward jumps — forward skips past phases where there's no
    # artefact yet, so nothing to move).
    cur_idx = track_ids.index(cur_pid) if cur_pid in track_ids else -1
    tgt_idx = track_ids.index(target_phase) if target_phase in track_ids else -1
    to_supersede: list[str] = []
    if cur_idx >= 0 and tgt_idx >= 0 and tgt_idx <= cur_idx:
        # Backward (or same) jump: supersede phases from tgt..cur (inclusive).
        to_supersede = track_ids[tgt_idx: cur_idx + 1]

    # Missing inputs warning.
    tdir = klc_ticket_dir(ticket)
    missing_inputs = [i for i in tgt.inputs if not (tdir / i).exists()]

    plan = {
        "from":            cur,
        "to":              _ph.format_state(target_phase, _ph.STATE_WORK),
        "missing_inputs":  missing_inputs,
        "supersede":       to_supersede,
        "reset_budgets":   True,
        "applied":         False,
    }
    if dry_run:
        return plan

    if to_supersede:
        supersede_phases(ticket, to_supersede)
    meta = read_meta(ticket)
    _reset_budgets(meta)
    write_meta(ticket, meta)
    set_state(ticket, target_phase, _ph.STATE_WORK,
              event="jump", note=f"from={cur}")
    plan["applied"] = True
    return plan


def abort(ticket: str) -> str:
    """Cancel current :work. Move artefacts of current phase to
    _superseded/, reset budgets, return to previous phase's :ack
    (or intake:ack-needed if the current phase is the first)."""
    meta = read_meta(ticket)
    cur = meta.get("phase", "")
    cur_pid, cur_state = _ph.parse_state(cur)
    if cur_state != _ph.STATE_WORK:
        raise ValueError(f"abort: current state is {cur!r}; expected :work")

    ph = _ph.load_phases()
    track = meta.get("track") or "M"
    prev = ph.prev_phase(track, cur_pid)

    # Supersede current phase's artefacts.
    supersede_phases(ticket, [cur_pid])

    # Reset budgets.
    meta = read_meta(ticket)
    _reset_budgets(meta)
    write_meta(ticket, meta)

    if prev is None:
        # Current is the first phase of the track — fall back to
        # intake:ack-needed so the ticket is still recoverable.
        set_state(ticket, "intake", _ph.STATE_ACK_NEEDED,
                  event="abort", note=f"from={cur}")
        return _ph.format_state("intake", _ph.STATE_ACK_NEEDED)

    set_state(ticket, prev.id, _ph.STATE_ACK,
              event="abort", note=f"from={cur}")
    return _ph.format_state(prev.id, _ph.STATE_ACK)


# --- convenience --------------------------------------------------------------

def can_ack(ticket: str) -> bool:
    """True iff current state is :ack-needed."""
    cur = current_state(ticket)
    if cur == _ph.STATE_ARCHIVED:
        return False
    try:
        _, st = _ph.parse_state(cur)
    except ValueError:
        return False
    return st == _ph.STATE_ACK_NEEDED


def is_work(ticket: str) -> bool:
    cur = current_state(ticket)
    if cur == _ph.STATE_ARCHIVED:
        return False
    try:
        _, st = _ph.parse_state(cur)
    except ValueError:
        return False
    return st == _ph.STATE_WORK


# --- CLI ---------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("show", help="print current state")
    p.add_argument("--ticket", required=True)

    p = sub.add_parser("ack", help="apply pick")
    p.add_argument("--ticket", required=True)
    p.add_argument("--pick", type=int, default=None)

    p = sub.add_parser("advance", help="ack → next phase :work")
    p.add_argument("--ticket", required=True)

    p = sub.add_parser("jump", help="jump to any phase :work")
    p.add_argument("--ticket", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("abort", help="cancel :work, return to prev :ack")
    p.add_argument("--ticket", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "show":
        print(current_state(args.ticket)); return 0
    if args.cmd == "ack":
        print(apply_ack(args.ticket, args.pick)); return 0
    if args.cmd == "advance":
        print(advance_to_next(args.ticket)); return 0
    if args.cmd == "jump":
        plan = jump(args.ticket, args.target, dry_run=args.dry_run)
        print(json.dumps(plan, indent=2)); return 0
    if args.cmd == "abort":
        print(abort(args.ticket)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
