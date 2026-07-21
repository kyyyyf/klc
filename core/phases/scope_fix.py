#!/usr/bin/env python3
"""`klc scope-fix <KEY> (--modules a,b,c | --add a,b | --remove a,b) [--reason ...]`

A first-class, durable path for correcting an ARCHIVED ticket's planning slice
(`meta.affected_modules`).

Why this verb exists (KLC-075 defect-2): once a ticket is `archived` no further
`ack` runs, so there is no state_tx to sweep an out-of-band edit to
`affected_modules` (e.g. dropping a temporarily-widened scope-guard entry). The
correction previously needed a manual `klc-state` commit + push. This verb wraps
the edit in the SAME `acquire_lock → state_tx` envelope ack/jira-sync use, so
the correction is durable and CAS-pushed to the bound upstream immediately
(feature-ON) and a byte-identical direct local write (feature-OFF).

Archived-only by design. `affected_modules` is enforcement input (it drives the
scope-expansion hard-fail at ack), so a LIVE ticket must correct its slice at
ack — the sanctioned flow where the change rides ack's own state_tx and holder
discipline. scope-fix refuses any non-archived ticket. An archived ticket holds
no holder, so — like `jira sync --apply` (KLC-065) — scope-fix takes NO holder
authorization; the archived gate is what closes the authority hole. The three
edit modes are mutually exclusive:

    --modules a,b,c   replace affected_modules with exactly this set
    --add a,b         union the listed modules into affected_modules
    --remove a,b      drop the listed modules from affected_modules

Malformed module lists (empty entries such as `a,,b` or `a, ,b`) are rejected
before any write. Unknown module names (not in the project's modules.json) are a
non-fatal advisory — the index may be absent or stale, and correcting an
archived ticket must not be blocked by a drifted index.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file, klc_index_dir  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_modules(raw: str) -> list[str]:
    """Split a comma list into cleaned, de-duplicated module names.

    Rejects malformed input: an empty entry (``a,,b``/``a, ,b``/trailing comma)
    is almost always a typo that would silently corrupt the slice, so it hard
    fails rather than being swallowed.
    """
    parts = [p.strip() for p in raw.split(",")]
    if any(p == "" for p in parts):
        raise ValueError(
            f"malformed module list {raw!r}: contains an empty entry "
            f"(check for a stray or trailing comma)")
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _known_module_names() -> set[str] | None:
    """Module names from the project's modules.json, or None if unavailable."""
    p = klc_index_dir() / "modules.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    mods = data.get("modules") if isinstance(data, dict) else data
    if not isinstance(mods, list):
        return None
    return {m.get("name") for m in mods if isinstance(m, dict) and m.get("name")}


# Control-flow signals used ONLY feature-ON to ABORT the state_tx body. state_tx
# glob-commits + CAS-pushes the ENTIRE tickets/<KEY>/ subtree on a CLEAN exit and
# only rolls back on an exception. The refusal and the genuine no-op must write
# and push NOTHING — but a clean exit would sweep any UNRELATED pre-existing
# subtree change (or a read_meta migration write) onto the shared branch. Raising
# to abort the tx is therefore the only way to honour no-write/no-push for those
# paths: it drives state_tx's rollback (restore post-pull snapshot + reset index)
# and discards the deferred Jira push. Only the `applied` path exits cleanly.
class _Refuse(Exception):
    """Ticket is not archived (decided on SYNCED meta) — abort, push nothing."""
    def __init__(self, phase: str):
        self.phase = phase


class _NoChange(Exception):
    """Synced affected_modules already equals the request — abort, push nothing."""
    def __init__(self, modules: list):
        self.modules = modules


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc scope-fix", description=__doc__)
    ap.add_argument("ticket")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--modules", help="replace affected_modules with this comma list")
    grp.add_argument("--add", help="union these comma-listed modules into affected_modules")
    grp.add_argument("--remove", help="drop these comma-listed modules from affected_modules")
    ap.add_argument("--reason", default="",
                    help="why the slice is being corrected (recorded in the audit trail)")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc scope-fix: unknown ticket {args.ticket!r}; run `klc intake` first\n")
        return 1

    # Structural validation FIRST. Malformed syntax (an empty entry from a stray
    # comma) needs no state, so hard-fail before reading meta / acquiring the
    # lock / touching git — the guard the AC asks for. JSON-aware (P2-B).
    raw = (args.modules if args.modules is not None
           else args.add if args.add is not None else args.remove)
    try:
        _parse_modules(raw)
    except ValueError as e:
        if args.json:
            print(json.dumps({"ticket": args.ticket, "status": "error",
                              "reason": "malformed-modules", "detail": str(e)}))
        else:
            sys.stderr.write(f"klc scope-fix: {e}\n")
        return 1

    def _apply(old: list) -> list:
        if args.modules is not None:
            return _parse_modules(args.modules)
        if args.add is not None:
            add = _parse_modules(args.add)
            return old + [x for x in add if x not in old]
        drop = set(_parse_modules(args.remove))  # --remove
        return [x for x in old if x not in drop]

    def _warn_unknown(new: list) -> None:
        # Advisory only: warn about names unknown to the module index but do NOT
        # block — the index may be absent/stale and an archived correction must
        # still go through (the whole point of this verb).
        known = _known_module_names()
        if known is not None:
            unknown = [x for x in new if x not in known]
            if unknown:
                sys.stderr.write(
                    f"klc scope-fix: note — module(s) not found in modules.json: "
                    f"{unknown} (proceeding; verify the names)\n")

    def _write(m: dict, old: list, new: list) -> None:
        _warn_unknown(new)
        m["affected_modules"] = new
        m.setdefault("phase_history", []).append({
            "event":        "scope-fix",
            "phase":        m.get("phase", ""),
            "from_modules": old,
            "to_modules":   new,
            "reason":       args.reason,
            "ts":           _now_iso(),
        })
        _lc.write_meta(args.ticket, m)

    # --- JSON-aware emit helpers, shared by the feature-ON and feature-OFF
    #     paths so every exit route (applied / noop / refused) has one schema.
    def _emit_refused(phase: str) -> int:
        if args.json:
            print(json.dumps({"ticket": args.ticket, "status": "refused",
                              "reason": "not-archived", "phase": phase}))
        else:
            sys.stderr.write(
                f"klc scope-fix: is for post-archive correction; ticket "
                f"{args.ticket} is at {phase!r} — correct scope at ack instead.\n")
        return 1

    def _emit_noop(modules: list) -> int:
        if args.json:
            print(json.dumps({"ticket": args.ticket, "status": "noop",
                              "affected_modules": modules,
                              "from_modules": modules, "reason": args.reason}))
        else:
            print(f"→ {args.ticket} affected_modules already {modules}; "
                  f"nothing to change.")
        return 0

    def _emit_applied(old: list, new: list) -> int:
        if args.json:
            print(json.dumps({"ticket": args.ticket, "status": "applied",
                              "affected_modules": new, "from_modules": old,
                              "reason": args.reason}))
        else:
            print(f"→ {args.ticket} affected_modules: {old} → {new}")
            if args.reason:
                print(f"  reason: {args.reason}")
        return 0

    # Persist. Feature-ON, the slice correction is a write to the SHARED branch,
    # so it must be durable immediately — the SAME acquire_lock → state_tx
    # envelope ack/jira-sync use (preserve → stale-guard → glob-commit the ticket
    # subtree → CAS-push to the BOUND upstream). This is what removes the manual
    # klc-state commit for post-archive corrections.
    if state_feature.enabled():
        # P2 (re-review): the archived gate + no-op decision run INSIDE the
        # envelope, against the SYNCED (post-pull) meta — never a stale local read
        # (FIX-1/P2-A). The non-applied paths RAISE to abort the tx (see _Refuse/
        # _NoChange) so state_tx rolls back and pushes nothing; only `applied`
        # exits cleanly and is committed + CAS-pushed. The decision read is
        # READ-ONLY so a legacy-phase migration is never written during a decision
        # that may refuse/no-op; only the applied branch takes a writable read.
        holder: dict = {"old": None, "new": None}
        try:
            with acquire_lock(args.ticket):
                with state_tx.state_tx(args.ticket, f"scope-fix {args.ticket}"):
                    meta = _lc.read_meta_ro(args.ticket)
                    phase0 = (meta.get("phase") or "").split(":")[0]
                    if phase0 != _ph.STATE_ARCHIVED:
                        raise _Refuse(meta.get("phase", ""))
                    old = list(meta.get("affected_modules") or [])
                    new = _apply(old)
                    holder["old"], holder["new"] = old, new
                    if new == old:
                        raise _NoChange(new)
                    wmeta = _lc.read_meta(args.ticket)  # writable copy to mutate
                    _write(wmeta, old, new)
                    # clean exit → state_tx commits + CAS-pushes (applied only)
            return _emit_applied(holder["old"], holder["new"])
        except _Refuse as r:
            return _emit_refused(r.phase)
        except _NoChange as n:
            return _emit_noop(n.modules)
        except state_sync.StaleStateError:
            sys.stderr.write(
                f"klc scope-fix: remote state advanced since you started — "
                f"re-run `klc scope-fix {args.ticket}`.\n")
            return 1
        except state_sync.NothingToCommitError:
            # Harmless safety net: the applied write produced no net change. Not
            # expected (new != old is checked), but treat as a clean no-op.
            return _emit_noop(holder.get("new") or [])
        except state_sync.StashConflictError:
            sys.stderr.write(
                "klc scope-fix: local changes conflict with the remote — "
                "resolve manually; your work is saved in the git stash.\n")
            return 1
        except state_sync.StateConflictError:
            sys.stderr.write(
                "klc scope-fix: concurrent update — another writer moved this "
                "ticket; retry.\n")
            return 1
        except LockedError as e:
            sys.stderr.write(f"klc scope-fix: {e}\n")
            return 1
        except Exception as e:
            # FIX-3: broad terminal handler (mirror jira.py). Besides the named
            # state_sync.* errors, commit_and_push_cas_subtree can raise a BARE
            # ValueError when `git add -A` refuses the subtree (corrupt index /
            # disk-full / permission). ValueError is NOT a RuntimeError, so a
            # specific tuple would let it escape as a raw traceback. state_tx has
            # already rolled the subtree back, so this is data-safe.
            sys.stderr.write(f"klc scope-fix: state sync failed — {e}\n")
            return 1

    # Feature-OFF: no upstream to be stale against and no tx that could sweep the
    # subtree, so decide + write directly against the local read (no lock, no
    # git). Same archived gate for contract parity — non-archived is refused too.
    meta = _lc.read_meta(args.ticket)
    phase0 = (meta.get("phase") or "").split(":")[0]
    if phase0 != _ph.STATE_ARCHIVED:
        return _emit_refused(meta.get("phase", ""))
    old = list(meta.get("affected_modules") or [])
    new = _apply(old)
    if new == old:
        return _emit_noop(new)
    _write(meta, old, new)
    return _emit_applied(old, new)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
