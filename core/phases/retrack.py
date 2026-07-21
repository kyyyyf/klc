#!/usr/bin/env python3
"""`klc retrack <KEY> <track> --reason "..."` — sanctioned track change.

The route heuristic (KLC-013/KLC-018) is upward-biased and downgrade-forbidden
to prevent under-scoping. But a thorough write-up of a small task over-routes
the track (the `raw length` signal uses word count as a complexity proxy), and
there was no sanctioned way to correct it. retrack is the operator-only, audited
mechanism that changes the track in BOTH directions.

It records {from_track, to_track, reason, ts} in meta.phase_history (audit trail)
and stamps meta.track_source="operator" so nothing downstream treats the stale
route_hint as the authoritative track. It refuses if the new track's phase set
does not include the current phase (would corrupt the state machine).

Operator-only by design: this verb is never embedded in an agent prompt, so an
agent cannot silently game the track downward — preserving KLC-018's intent.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402

_VALID_TRACKS = ("XS", "S", "M", "L")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc retrack", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("track", choices=_VALID_TRACKS,
                    help="target track (XS/S/M/L); downgrade allowed")
    ap.add_argument("--reason", required=True,
                    help="why the track is being changed (recorded in the audit trail)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc retrack: unknown ticket {args.ticket!r}; run `klc intake` first\n"
        )
        return 1

    try:
        meta = _lc.read_meta(args.ticket)
    except FileNotFoundError as e:
        sys.stderr.write(f"klc retrack: {e}\n")
        return 1

    old_track = meta.get("track") or "M"
    new_track = args.track

    if new_track == old_track:
        sys.stderr.write(
            f"klc retrack: ticket {args.ticket} is already on track {new_track}; "
            f"nothing to do.\n"
        )
        return 1

    # Compatibility guard: the current phase must exist in the target track.
    phase_value = meta.get("phase") or ""
    if _ph.is_terminal(phase_value):
        sys.stderr.write(
            f"klc retrack: ticket {args.ticket} is {phase_value}; cannot retrack "
            f"a terminal ticket.\n"
        )
        return 1
    try:
        cur_pid, _ = _ph.parse_state(phase_value)
    except ValueError:
        sys.stderr.write(
            f"klc retrack: meta.json:phase is unparseable: {phase_value!r}\n"
        )
        return 1

    target_phase_ids = {p.id for p in _ph.load_phases().track_phases(new_track)}
    if cur_pid not in target_phase_ids:
        sys.stderr.write(
            f"klc retrack: cannot move {args.ticket} to track {new_track} — its "
            f"phase set does not include the current phase {cur_pid!r}. "
            f"Advance or jump to a phase common to both tracks first.\n"
        )
        return 1

    # Apply: change track, stamp source, append audit entry.
    meta["track"] = new_track
    meta["track_source"] = "operator"
    history = meta.setdefault("phase_history", [])
    history.append({
        "event":      "retrack",
        "phase":      phase_value,
        "from_track": old_track,
        "to_track":   new_track,
        "reason":     args.reason,
        "ts":         _now_iso(),
    })

    # Persist. Feature-ON (a bound klc-state worktree), the track change is a
    # write to the SHARED branch, so it must be durable immediately — wrapped in
    # the SAME acquire_lock → state_tx envelope ack/jira-sync use (preserve →
    # stale-guard → glob-commit the ticket subtree → CAS-push to the BOUND
    # upstream). Without it a retrack committed only to the local worktree would
    # not reach peers until a LATER ack's state_tx swept it, so a track change
    # made without a following ack was silently non-durable on the shared branch
    # (the reported defect). retrack is an operator correction, NOT a
    # phase/ownership move, so — exactly like `jira sync --apply` (KLC-065) — it
    # takes NO holder authorization. Feature-OFF, state_tx is a pure no-op: the
    # direct local write in the else-branch runs with no lock and no git,
    # byte-identical to before this ticket.
    if state_feature.enabled():
        try:
            with acquire_lock(args.ticket):
                with state_tx.state_tx(
                    args.ticket,
                    f"retrack {args.ticket} {old_track}->{new_track}",
                ):
                    _lc.write_meta(args.ticket, meta)
        except state_sync.NothingToCommitError:
            # A genuine post-sync no-op (the write produced no tracked change):
            # nothing to push, treat as clean success — mirroring `jira sync
            # --apply` (jira.py). In practice retrack always changes the track,
            # so the stale-guard fires first on a moved ticket; this clause is
            # the defensive clean-no-op path.
            print(f"→ {args.ticket} already on track {new_track}; "
                  f"nothing to change.")
            return 0
        except state_sync.StaleStateError:
            sys.stderr.write(
                f"klc retrack: remote state advanced since you started — re-run "
                f"`klc retrack {args.ticket} {new_track}`.\n")
            return 1
        except state_sync.StashConflictError:
            sys.stderr.write(
                "klc retrack: local changes conflict with the remote — resolve "
                "manually; your work is saved in the git stash.\n")
            return 1
        except state_sync.StateConflictError:
            sys.stderr.write(
                "klc retrack: concurrent update — another writer moved this "
                "ticket; retry.\n")
            return 1
        except LockedError as e:
            sys.stderr.write(f"klc retrack: {e}\n")
            return 1
        except Exception as e:
            # Broad terminal handler (mirrors jira.py): besides the named
            # state_sync.* sync errors, commit_and_push_cas_subtree can raise a
            # BARE ValueError when `git add -A` refuses the subtree (corrupt
            # index / disk-full / permission; state_sync.py). ValueError is NOT a
            # RuntimeError, so a specific tuple would let it escape as a raw
            # traceback. state_tx has already rolled the subtree back, so this is
            # data-safe: surface the friendly message and return 1.
            sys.stderr.write(f"klc retrack: state sync failed — {e}\n")
            return 1
    else:
        _lc.write_meta(args.ticket, meta)

    if args.json:
        print(json.dumps({
            "ticket":     args.ticket,
            "track":      new_track,
            "from_track": old_track,
            "phase":      phase_value,
            "reason":     args.reason,
        }))
    else:
        print(f"→ {args.ticket} retracked {old_track} → {new_track}")
        print(f"  reason: {args.reason}")
        print(f"  (track_source=operator; recorded in phase_history)")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
