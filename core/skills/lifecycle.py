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

import datetime as _dt
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import klc_ticket_dir, klc_ticket_meta_file  # noqa: E402
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


# --- low-level state write ----------------------------------------------------

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
    nxt = ph.next_phase(track, pid)
    if nxt is None:
        # Last phase of track → archived.
        set_state(ticket, _ph.STATE_ARCHIVED, _ph.STATE_ARCHIVED,
                  event="advance", note=note or "terminal")
        return _ph.STATE_ARCHIVED
    set_state(ticket, nxt.id, _ph.STATE_WORK, event="advance", note=note)
    return _ph.format_state(nxt.id, _ph.STATE_WORK)


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
