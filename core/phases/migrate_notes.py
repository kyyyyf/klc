#!/usr/bin/env python3
"""`klc migrate-notes` — the one-time over-cap phase-history note migration
(KLC-117 AC-15/AC-16).

Walks every ticket directory under `.klc/tickets/` — active AND archived, since
an archived ticket keeps `phase: archived` in the same tree; there is no
separate archive directory (verified 2026-09-17) — and replaces every
`phase_history[].note` over `advisories.NOTE_CAP` with a truncated note plus a
pointer to that entry's phase artifact, via `advisories.cap_note`. Exactly one
`note-migration` audit entry is appended per migrated ticket, and a re-run over
an already-migrated tree is a true no-op (idempotent, C-005).

Lossy by design (design D-005): the discarded prose is not copied anywhere. It
stays recoverable from the `klc-state` branch's git history of `meta.json`, and
the audit entry records how much was reclaimed, so the loss is measured.

impl-plan-review F-1 (HIGH): every other meta-mutating verb in this codebase
wraps its write in `acquire_lock` + `state_tx.state_tx(...)` — this migration,
which is a bulk walk exactly like `heartbeat.py`'s per-ticket loop, follows the
same envelope per ticket, swallowing `StaleStateError` (a concurrent steal —
skip and move on) and `NothingToCommitError` (nothing changed — a true no-op)
so one locked/racing ticket never aborts the whole walk. Feature-OFF (no
`.klc/` git worktree, or no klc-state upstream), `state_tx` is a pure
pass-through: the body still runs and writes meta.json locally, which is what
this migration needs in a single-user install.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import lifecycle as _lc  # noqa: E402
import advisories as _adv  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from _paths import klc_tickets_dir  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402

_AUDIT_EVENT = "note-migration"
_POINTER = "see {phase_id}/ack-advisories.json"


def _migrate_history(history: list[dict]) -> tuple[int, int]:
    """Mutate `history` in place. Returns (migrated_count, chars_reclaimed).

    C-005: touches ONLY the `note` field of entries over the cap; every other
    field (`phase`, `event`, timestamps, `pick`) is left byte-identical.
    """
    migrated = 0
    reclaimed = 0
    for entry in history:
        note = entry.get("note") or ""
        if len(note) <= _adv.NOTE_CAP:
            continue
        phase_id = str(entry.get("phase", "")).split(":", 1)[0]
        new_note = _adv.cap_note(note, _POINTER.format(phase_id=phase_id))
        reclaimed += len(note) - len(new_note)
        entry["note"] = new_note
        migrated += 1
    return migrated, reclaimed


def migrate_ticket(ticket: str, dry_run: bool = False) -> dict:
    """Migrate one ticket's over-cap notes. Idempotent, archive-aware.

    A ticket that already carries a `note-migration` audit entry is skipped
    outright — this is what makes a second run byte-identical rather than
    merely non-crashing (AC-16).

    review-fix (HIGH, AC-15): `--dry-run` never enters `state_tx` at all — a
    dry-run has nothing to commit BY DEFINITION (it never calls
    `_lc.write_meta`), so in a feature-ON (multi-user) deployment the
    envelope's exit `commit_and_push_cas_subtree` would see a byte-identical
    subtree and raise `NothingToCommitError`, which `migrate_ticket`'s own
    except-clause caught and turned into `{"migrated": 0, "skipped": "no-op"}`
    — discarding the correctly-computed counts and always reporting 0
    migrated, breaking the documented `--dry-run` contract in exactly the
    deployment mode this project runs in. A plain `read_meta_ro` plus the
    pure `_migrate_history` simulation (on a private copy — nothing is
    mutated in place) is all a dry-run needs.
    """
    if dry_run:
        meta = _lc.read_meta_ro(ticket)
        history = meta.get("phase_history") or []
        if any(e.get("event") == _AUDIT_EVENT for e in history):
            return {"ticket": ticket, "migrated": 0, "skipped": "already migrated"}
        migrated, reclaimed = _migrate_history(
            [dict(e) for e in history])  # private copy — never mutates meta
        return {"ticket": ticket, "migrated": migrated, "reclaimed": reclaimed}
    try:
        with acquire_lock(ticket):
            try:
                with state_tx.state_tx(ticket, f"migrate-notes {ticket}"):
                    meta = _lc.read_meta_ro(ticket)
                    history = meta.get("phase_history") or []
                    if any(e.get("event") == _AUDIT_EVENT for e in history):
                        return {"ticket": ticket, "migrated": 0,
                                "skipped": "already migrated"}
                    migrated, reclaimed = _migrate_history(history)
                    if migrated:
                        # review-fix (HIGH, AC-15): an audit-only entry uses a
                        # bare `ts` field, like retrack.py/scope_fix.py — NEVER
                        # `started_at`/`finished_at`. metrics._ct() computes
                        # cycle time from those two keys over every
                        # phase_history entry unconditionally; stamping them
                        # with the migration's own run time would silently
                        # make this audit entry the new "end" of the ticket's
                        # lifecycle, corrupting cycle_time_sec_median/p95 for
                        # every migrated ticket (including already-archived
                        # ones) with no error or symptom.
                        history.append({
                            "phase": meta.get("phase"), "ts": _lc._now(),
                            "event": _AUDIT_EVENT,
                            "note": (f"KLC-117: {migrated} over-cap note(s) "
                                    f"truncated, {reclaimed} chars reclaimed"),
                        })
                        _lc.write_meta(ticket, meta)
                    return {"ticket": ticket, "migrated": migrated,
                            "reclaimed": reclaimed}
            except state_sync.NothingToCommitError:
                return {"ticket": ticket, "migrated": 0, "skipped": "no-op"}
            except state_sync.StaleStateError:
                return {"ticket": ticket, "migrated": 0,
                        "skipped": "stale — remote state advanced, retry"}
    except LockedError as e:
        return {"ticket": ticket, "migrated": 0, "skipped": f"locked: {e}"}


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc migrate-notes", description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would migrate; write nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    tickets_dir = klc_tickets_dir()
    results: list[dict] = []
    if tickets_dir.exists():
        for tdir in sorted(tickets_dir.iterdir()):
            if not tdir.is_dir() or not (tdir / "meta.json").exists():
                continue
            ticket = tdir.name
            try:
                results.append(migrate_ticket(ticket, dry_run=args.dry_run))
            except Exception as exc:  # noqa: BLE001 — one bad ticket must not abort the walk
                results.append({"ticket": ticket, "migrated": 0,
                                "error": f"{type(exc).__name__}: {exc}"})

    total_migrated = sum(r.get("migrated", 0) for r in results)
    total_reclaimed = sum(r.get("reclaimed", 0) for r in results)
    if args.json:
        print(json.dumps({"results": results, "total_migrated": total_migrated,
                          "total_reclaimed": total_reclaimed}))
    else:
        for r in results:
            if r.get("migrated"):
                print(f"{r['ticket']}: migrated {r['migrated']} note(s), "
                     f"reclaimed {r.get('reclaimed', 0)} chars"
                     f"{' (dry-run)' if args.dry_run else ''}")
        print(f"total: {total_migrated} ticket(s) migrated, "
             f"{total_reclaimed} chars reclaimed")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
