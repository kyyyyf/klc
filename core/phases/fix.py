#!/usr/bin/env python3
"""`klc fix <KEY> <field> <value...> --reason TEXT [--dry-run] [--json]`

The one audited editor for a ticket's meta.json planning fields (KLC-178). It
replaces two older verbs (`retrack`, `scope-fix`) that each had their own
persist path and no common audit trail.

    track        XS|S|M|L        downgrade allowed, refused for a terminal ticket;
                                 stamps track_source=operator and appends the
                                 `retrack` event to phase_history. XS and S are the
                                 `light` lane, M and L the `full` lane; a change of lane
                                 keeps the ticket's facts and moves it to the first
                                 missing one of the new lane (never to `archived`)
    modules      --add a,b | --remove a,b | --set a,b
                                 edits affected_modules in ANY state (merged and
                                 archived included); appends the `scope-fix` event
    risk-tags    a,b | -         replaces meta.risk_tags (`-` clears)
    kind         feature|bug|tech
    epic         KEY | -         sets or clears meta.epic
    blocked-by   SPEC... | -     epic_deps edge specs (replaces the list; `-` clears)

    klc fix --migrate-vocabulary [--dry-run]   the KLC-110 batch mode, no ticket

Every change appends {field, before, after, reason, at, by} to meta.fixes[] in
one state transaction (feature-ON: acquire_lock -> state_tx -> CAS push; feature-OFF:
a direct local write). `--dry-run` takes no lock and writes nothing. Bad input
(unknown field, blank reason, empty module entry, unknown ticket, invalid value)
fails with exit 2 before any lock or write. Refusals of a valid request (a terminal
ticket) exit 1.

Operator-only by design: the verb is never embedded in an agent prompt and takes
no holder authorization, exactly like retrack and scope-fix before it.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import klc_ticket_meta_file  # noqa: E402
import epic_deps as _edeps  # noqa: E402
import ticket_id as _ticket_id  # noqa: E402
import identity  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402
import retrack as _retrack  # noqa: E402
import rules as _rules  # noqa: E402  (KLC-179: facts.track mirrors meta.track)
import scope_fix as _scope_fix  # noqa: E402

_VALID_TRACKS = ("XS", "S", "M", "L")
_KINDS = ("feature", "bug", "tech")
FIELDS = ("track", "modules", "risk-tags", "kind", "epic", "blocked-by")
# CLI field name -> meta.json key.
_FIELD_KEYS = {
    "track": "track", "modules": "affected_modules", "risk-tags": "risk_tags",
    "kind": "kind", "epic": "epic", "blocked-by": "blocked_by",
}


class _Refuse(Exception):
    """A valid request the rules refuse (decided on SYNCED meta): exit 1, write nothing."""


class _NoChange(Exception):
    """The synced value already equals the request: write nothing."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _before(meta: dict, field: str):
    if field == "track":
        return meta.get("track") or "M"
    if field in ("modules", "risk-tags", "blocked-by"):
        return list(meta.get(_FIELD_KEYS[field]) or [])
    return meta.get(_FIELD_KEYS[field])


def apply_fix(meta: dict, field: str, value, reason: str, by: str, at: str) -> dict:
    """Set `field` to `value` on `meta`, append the audit record, return it.

    Mutates `meta` only. The legacy audit events that existing readers rely on
    (`retrack`, `scope-fix` in phase_history, `track_source`) are written here
    too, so fix keeps them byte-compatible with the verbs it replaces."""
    key = _FIELD_KEYS[field]
    before = _before(meta, field)
    if value is None:
        meta.pop(key, None)
    else:
        meta[key] = value
    if field == "track":
        meta["track_source"] = "operator"
        meta.setdefault("phase_history", []).append({
            "event": "retrack", "phase": meta.get("phase") or "",
            "from_track": before, "to_track": value, "reason": reason, "ts": at})
    elif field == "modules":
        meta.setdefault("phase_history", []).append({
            "event": "scope-fix", "phase": meta.get("phase", ""),
            "from_modules": before, "to_modules": value, "reason": reason, "ts": at})
    rec = {"field": field, "before": before, "after": value,
           "reason": reason, "at": at, "by": by}
    meta.setdefault("fixes", []).append(rec)
    return rec


def _parse_value(ap, args) -> dict:
    """Validate the request shape with no state. Returns a spec; exits 2 on bad input."""
    field, vals, ticket = args.field, args.value, args.ticket
    if field == "modules":
        ops = {k: getattr(args, k) for k in ("add", "remove", "set")
               if getattr(args, k) is not None}
        if len(ops) != 1 or vals:
            ap.error("modules needs exactly one of --add, --remove, --set (and no "
                     "positional value)")
        (op, raw), = ops.items()
        try:
            return {"op": op, "names": _scope_fix._parse_modules(raw)}
        except ValueError as e:
            ap.error(str(e))
    if any(getattr(args, k) is not None for k in ("add", "remove", "set")):
        ap.error("--add/--remove/--set are only valid for the modules field")
    if field == "blocked-by":
        if not vals:
            ap.error("blocked-by needs at least one edge spec, or `-` to clear")
        if vals == ["-"]:
            return {"value": []}
        if "-" in vals:
            ap.error("`-` clears blocked-by and cannot be mixed with edge specs")
        known = {p.id for p in _ph.load_phases().ordered}
        edges = []
        for spec in vals:
            try:
                edge = _edeps.parse_edge(spec, self_key=ticket)
            except ValueError as e:
                ap.error(str(e))
            if edge["phase"] not in known:
                ap.error(f"bad blocked-by {spec!r}: unknown downstream phase "
                         f"{edge['phase']!r} (not in config/phases.yml)")
            edges.append(edge)
        return {"value": edges}
    if len(vals) != 1:
        ap.error(f"{field} takes exactly one value")
    v = vals[0].strip()
    if field == "track":
        if v not in _VALID_TRACKS:
            ap.error(f"track must be one of {', '.join(_VALID_TRACKS)}, got {v!r}")
        return {"value": v}
    if field == "kind":
        if v not in _KINDS:
            ap.error(f"kind must be one of {', '.join(_KINDS)}, got {v!r}")
        return {"value": v}
    if field == "risk-tags":
        if v == "-":
            return {"value": []}
        try:
            return {"value": _scope_fix._parse_modules(v)}
        except ValueError as e:
            ap.error(str(e).replace("module list", "risk-tags list"))
    # epic
    if v == "-":
        return {"value": None}
    if not v or not _ticket_id.key_pattern().match(v):
        ap.error(f"epic must be a ticket key or `-`, got {vals[0]!r}")
    if v == ticket:
        ap.error(f"{ticket} cannot be its own epic")
    return {"value": v}


def _decide(ticket: str, meta: dict, field: str, spec: dict):
    """The after-value for `meta`, or raises _Refuse / _NoChange."""
    if field == "track":
        if spec["value"] == (meta.get("track") or "M"):
            raise _NoChange()
        problem = _retrack.check_track_change(ticket, meta, spec["value"])
        if problem:
            raise _Refuse(problem)
        return spec["value"]
    before = _before(meta, field)
    if field == "modules":
        names = spec["names"]
        if spec["op"] == "set":
            after = list(names)
        elif spec["op"] == "add":
            after = before + [x for x in names if x not in before]
        else:
            after = [x for x in before if x not in set(names)]
    else:
        after = spec["value"]
    if after == before or (after is None and before is None):
        raise _NoChange()
    return after


def _warn_unknown_modules(spec: dict) -> None:
    known = _scope_fix._known_module_names()
    if known is not None and spec.get("op") != "remove":
        unknown = [x for x in spec["names"] if x not in known]
        if unknown:
            sys.stderr.write(f"klc fix: note — module(s) not found in modules.json: "
                             f"{unknown} (proceeding; verify the names)\n")


def _emit(args, rec: dict, *, dry: bool) -> None:
    if args.json:
        print(json.dumps(rec))
        return
    tag = "would fix" if dry else "fixed"
    print(f"→ {args.ticket} {tag} {rec['field']}: {rec['before']} → {rec['after']}")
    print(f"  reason: {rec['reason']}")


def _emit_noop(args) -> int:
    if args.json:
        print(json.dumps({"ticket": args.ticket, "field": args.field, "status": "noop"}))
    else:
        print(f"→ {args.ticket} {args.field} already has that value; nothing to change.")
    return 0


def _fail(msg: str, rc: int = 1) -> int:
    sys.stderr.write(f"klc fix: {msg}\n")
    return rc


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc fix", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticket", nargs="?")
    ap.add_argument("field", nargs="?", choices=FIELDS)
    ap.add_argument("value", nargs="*")
    ap.add_argument("--add", help="modules: union these comma-listed modules in")
    ap.add_argument("--remove", help="modules: drop these comma-listed modules")
    ap.add_argument("--set", help="modules: replace affected_modules with this list")
    ap.add_argument("--reason", default="",
                    help="why the field is corrected (recorded in meta.fixes[])")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the would-be record and write nothing")
    ap.add_argument("--json", action="store_true", help="print the record as JSON")
    ap.add_argument("--migrate-vocabulary", action="store_true",
                    help="KLC-110 batch mode: rewrite archived tickets' modules to the "
                         "module vocabulary; takes no ticket")
    args = ap.parse_args(argv)

    if args.migrate_vocabulary:
        if args.ticket is not None or args.field is not None:
            ap.error("--migrate-vocabulary is a batch mode and takes no ticket argument")
        return _scope_fix._run_migrate(args)
    if args.ticket is None or args.field is None:
        ap.error("usage: klc fix <KEY> <field> <value...> --reason TEXT")
    if not args.reason.strip():
        ap.error("--reason is required and must not be blank")
    spec = _parse_value(ap, args)
    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(f"klc fix: unknown ticket {args.ticket!r}; run `klc intake` first\n")
        return 2

    field, reason = args.field, args.reason.strip()
    by = identity.current()

    if args.dry_run:
        try:
            meta = _lc.read_meta_ro(args.ticket)
            after = _decide(args.ticket, meta, field, spec)
        except _Refuse as r:
            return _fail(str(r))
        except _NoChange:
            return _emit_noop(args)
        rec = apply_fix(copy.deepcopy(meta), field, after, reason, by, _now_iso())
        _emit(args, rec, dry=True)
        return 0

    holder: dict = {}

    def _body(ro_read) -> None:
        meta = ro_read(args.ticket)
        after = _decide(args.ticket, meta, field, spec)
        wmeta = _lc.read_meta(args.ticket)  # writable copy to mutate
        if field == "modules":
            _warn_unknown_modules(spec)
        if field == "track":
            # facts first: `facts.track` must still name the OLD lane when switch_track
            # compares it with the new one (apply_fix rewrites the letter right below)
            _lc._ensure_facts(args.ticket, wmeta)
        holder["rec"] = apply_fix(wmeta, field, after, reason, by, _now_iso())
        _lc.write_meta(args.ticket, wmeta)
        if field == "track":
            # KLC-179: a lane change keeps the facts and moves to the first missing one
            # (it never archives); the letter the operator typed stays as the mirror.
            _lc.switch_track(args.ticket, _rules.legacy_track(after), letter=after)

    try:
        if state_feature.enabled():
            # Decision + write both run inside the envelope against SYNCED meta;
            # the non-applied paths raise to abort the tx so it pushes nothing.
            with acquire_lock(args.ticket):
                with state_tx.state_tx(args.ticket, f"fix {args.ticket} {field}"):
                    _body(_lc.read_meta_ro)
        else:
            _body(_lc.read_meta)
    except _Refuse as r:
        return _fail(str(r))
    except _NoChange:
        return _emit_noop(args)
    except state_sync.NothingToCommitError:
        return _emit_noop(args)
    except state_sync.StaleStateError:
        return _fail(f"remote state advanced since you started — re-run "
                     f"`klc fix {args.ticket} {field}`.")
    except state_sync.StashConflictError:
        return _fail("local changes conflict with the remote — resolve manually; "
                     "your work is saved in the git stash.")
    except state_sync.StateConflictError:
        return _fail("concurrent update — another writer moved this ticket; retry.")
    except LockedError as e:
        return _fail(str(e))
    except Exception as e:  # noqa: BLE001 — state_tx already rolled the subtree back
        return _fail(f"state sync failed — {e}")

    _emit(args, holder["rec"], dry=False)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
