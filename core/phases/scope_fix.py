#!/usr/bin/env python3
"""`klc scope-fix <KEY> (--modules a,b,c | --add a,b | --remove a,b) [--reason ...]`

Deprecated alias of `klc fix <KEY> modules --set/--add/--remove ... --reason ...`
(KLC-178). It is no longer archived-only: `fix` edits affected_modules in any
state. This module keeps the shared helpers (`_parse_modules`,
`_known_module_names`) and the KLC-111 vocabulary migration (`_run_migrate`)
that `fix` reuses.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file, klc_index_dir, klc_tickets_dir  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
import module_vocabulary as _mv  # noqa: E402  (KLC-111: the one vocabulary/mapper module)
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
    """Hidden alias of `klc fix <KEY> modules ...` (KLC-178). The dispatcher prints
    the one deprecation line; this only translates argv and delegates, so the edit,
    the lock envelope and the meta.fixes[] audit record are fix's own."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fix as _fix  # lazy: fix imports this module's helpers
    ap = argparse.ArgumentParser(prog="klc scope-fix", description=__doc__)
    ap.add_argument("ticket", nargs="?")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--modules", help="replace affected_modules with this comma list")
    grp.add_argument("--add", help="union these comma-listed modules into affected_modules")
    grp.add_argument("--remove", help="drop these comma-listed modules from affected_modules")
    grp.add_argument("--migrate-vocabulary", action="store_true",
                     help="batch-rewrite every archived ticket's affected_modules "
                          "to the module vocabulary; takes no ticket argument")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.migrate_vocabulary:
        if args.ticket is not None:
            ap.error("--migrate-vocabulary is a batch mode and takes no ticket argument")
        out = (["--migrate-vocabulary"] + (["--dry-run"] if args.dry_run else [])
               + (["--json"] if args.json else []))
        return _fix.run(out)
    if args.ticket is None:
        ap.error("the following arguments are required: ticket")
    if args.dry_run:
        ap.error("--dry-run is only valid with --migrate-vocabulary")
    flag, raw = next((f, v) for f, v in (("--set", args.modules), ("--add", args.add),
                                         ("--remove", args.remove)) if v is not None)
    out = [args.ticket, "modules", flag, raw, "--reason",
           args.reason.strip() or "(no reason given; via deprecated klc scope-fix)"]
    if args.json:
        out.append("--json")
    return _fix.run(out)



def _classify_ticket(old: list, modules_data: dict):
    """One ticket's (new_list, verdicts, after_representative) triple.
    `after_representative` substitutes each OLD entry with one resolved
    module when it maps, or leaves it as-is otherwise — one output per
    input entry, so the before/after share arithmetic counts entries, not
    the deduplicated/fanned-out new list (KLC-111 AC-18)."""
    new, verdicts = _mv.migrate_modules(old, modules_data)
    after_repr = [v["modules"][0] if v["modules"] else v["name"] for v in verdicts]
    return new, verdicts, after_repr


def _plan_one(tdir: Path, modules_data: dict, before: list, after: list,
              unmappable: dict, ambiguous: dict, mapping: dict):
    """Read-only per-ticket dry-run row. Never writes; a corrupt or missing
    `meta.json` is reported and skipped rather than aborting the walk."""
    meta_path = tdir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:                              # noqa: BLE001
        return {"ticket": tdir.name, "status": "error",
                "reason": f"meta.json unreadable: {type(exc).__name__}"}
    phase0 = (meta.get("phase") or "").split(":")[0]
    old = list(meta.get("affected_modules") or [])
    if phase0 != _ph.STATE_ARCHIVED:
        return {"ticket": tdir.name, "status": "not-archived",
                "reason": f"phase {meta.get('phase', '')}"}
    new, verdicts, after_repr = _classify_ticket(old, modules_data)
    before.extend(old)
    after.extend(after_repr)
    for v in verdicts:
        if v["status"] == "unmappable":
            unmappable[v["name"]] = unmappable.get(v["name"], 0) + 1
        elif v["status"] == "ambiguous":
            ambiguous.setdefault(v["name"], v["candidates"])
        elif v["status"] == "mapped":
            mapping.setdefault(v["name"], v["modules"])
    status = "noop" if new == old else "would-rewrite"
    return {"ticket": tdir.name, "status": status, "from_modules": old, "to_modules": new}


def _as_list(d: dict) -> list:
    """A dict keyed by name into a stable, sorted list of records — a
    `count` for the unmappable table, `candidates` for the ambiguous one."""
    out = []
    for name in sorted(d):
        value = d[name]
        if isinstance(value, list):
            out.append({"name": name, "candidates": value})
        else:
            out.append({"name": name, "count": value})
    return out


def _migrate_one(ticket: str, modules_data: dict, vocab: set) -> dict:
    """One ticket's write, inside its own `acquire_lock` + `state_tx`
    (KLC-111 AC-9, AC-10, AC-13). The archived decision and the
    already-migrated check are both taken on the SYNCED (post-pull) meta,
    exactly like the three shipped modes (C-001). `vocab` is accepted for
    interface symmetry with the read-only planning path; the write itself
    only needs `modules_data` to re-derive the mapping.

    review-fix (HIGH, AC-9/AC-10): a SINGLE flat try/except, mirroring
    `run()`'s own structure (~226-302), so every `state_sync.*` error class
    — not just `NothingToCommitError`/`StaleStateError` — and a final bare
    `except Exception` (for the same un-named `ValueError`
    `commit_and_push_cas_subtree` can raise that `run()` already guards
    against) all degrade to one `skipped` row instead of propagating out of
    the whole batch walk. `_Refuse`/`_NoChange` are listed FIRST — they are
    plain `Exception` subclasses, so they must be matched before the broad
    terminal clause or they would be swallowed by it (spec Assumptions: "a
    lock held by another writer... skips that ticket... leaves every other
    ticket's result intact"; ADR point 5)."""
    del vocab
    try:
        with acquire_lock(ticket):
            with state_tx.state_tx(ticket, f"migrate-vocabulary {ticket}"):
                meta = _lc.read_meta_ro(ticket)
                phase0 = (meta.get("phase") or "").split(":")[0]
                if phase0 != _ph.STATE_ARCHIVED:
                    raise _Refuse(meta.get("phase", ""))
                history = meta.get("phase_history") or []
                if any(e.get("event") == _mv.AUDIT_EVENT for e in history):
                    raise _NoChange(list(meta.get("affected_modules") or []))
                old = list(meta.get("affected_modules") or [])
                new, _verdicts = _mv.migrate_modules(old, modules_data)
                if new == old:
                    raise _NoChange(old)
                wmeta = _lc.read_meta(ticket)  # writable copy to mutate
                wmeta["affected_modules"] = new
                # Bare `ts` ONLY: metrics._ct() computes cycle time from
                # started_at/finished_at across every phase_history entry
                # and would silently make this the new end of the
                # lifecycle otherwise (C-003, D-008).
                wmeta.setdefault("phase_history", []).append({
                    "phase": wmeta.get("phase"), "event": _mv.AUDIT_EVENT,
                    "from_modules": old, "to_modules": new,
                    "note": "KLC-111: affected_modules migrated to the module vocabulary",
                    "ts": _now_iso(),
                })
                _lc.write_meta(ticket, wmeta)
                return {"ticket": ticket, "status": "rewritten",
                        "from_modules": old, "to_modules": new, "reason": ""}
    except _Refuse as r:
        return {"ticket": ticket, "status": "refused", "reason": f"phase {r.phase}"}
    except _NoChange as n:
        return {"ticket": ticket, "status": "noop", "to_modules": n.modules, "reason": ""}
    except state_sync.NothingToCommitError:
        return {"ticket": ticket, "status": "noop", "reason": "no net change"}
    except state_sync.StaleStateError:
        return {"ticket": ticket, "status": "skipped", "reason": "stale — retry"}
    except state_sync.StashConflictError as e:
        return {"ticket": ticket, "status": "skipped", "reason": f"stash conflict: {e}"}
    except state_sync.StateConflictError as e:
        return {"ticket": ticket, "status": "skipped", "reason": f"concurrent update: {e}"}
    except state_sync.RebaseConflictError as e:
        return {"ticket": ticket, "status": "skipped", "reason": f"rebase conflict: {e}"}
    except state_sync.RetryExhaustedError as e:
        return {"ticket": ticket, "status": "skipped", "reason": f"retry exhausted: {e}"}
    except state_sync.ConfigError as e:
        return {"ticket": ticket, "status": "skipped", "reason": f"config error: {e}"}
    except LockedError as e:
        return {"ticket": ticket, "status": "skipped", "reason": f"locked: {e}"}
    except Exception as e:                                # noqa: BLE001
        # FIX-3 parity (mirror run()'s own terminal handler, ~294-302): a
        # bare ValueError from commit_and_push_cas_subtree (corrupt index /
        # disk-full / permission) is not a state_sync.* class; state_tx has
        # already rolled the subtree back, so this is data-safe to skip.
        return {"ticket": ticket, "status": "skipped", "reason": f"state sync failed: {e}"}


def _migrate_report(dry_run: bool) -> dict:
    """Walk every ticket. A dry-run stops at the read-only plan: it never
    acquires a lock and never enters `state_tx`, so there is nothing to
    commit and nothing that could raise `NothingToCommitError` (C-002). A
    real run additionally writes every plannable ticket through
    `_migrate_one`, one lock and one transaction at a time; the before/after
    share and the mapping/unmappable/ambiguous tables are always computed
    from the pre-write `_plan_one` pass, so the arithmetic never double-
    counts a write racing its own read."""
    data, reason = _mv.load_modules()
    if data is None:
        return {"mode": "migrate-vocabulary", "dry_run": dry_run, "tickets": [],
                "mapping": [], "unmappable": [], "ambiguous": [],
                "skipped": f"index unavailable: {reason}", "rewritten": 0}
    vocab = _mv.vocabulary(data)
    before: list = []
    after: list = []
    rows: list = []
    unmappable: dict = {}
    ambiguous: dict = {}
    mapping: dict = {}
    tickets_dir = klc_tickets_dir()
    tdirs = sorted(p for p in tickets_dir.iterdir() if p.is_dir()) if tickets_dir.exists() else []
    for tdir in tdirs:
        plan_row = _plan_one(tdir, data, before, after, unmappable, ambiguous, mapping)
        if plan_row is None:
            continue
        if dry_run or plan_row["status"] == "error":
            rows.append(plan_row)
        else:
            rows.append(_migrate_one(tdir.name, data, vocab))
    return {
        "mode": "migrate-vocabulary", "dry_run": dry_run, "tickets": rows,
        "mapping": [{"name": k, "modules": v} for k, v in sorted(mapping.items())],
        "unmappable": _as_list(unmappable), "ambiguous": _as_list(ambiguous),
        "in_vocabulary_share": {
            "before": _mv.vocabulary_share(before, vocab),
            "after": _mv.vocabulary_share(after, vocab),
        },
        "rewritten": sum(1 for r in rows if r["status"] == "rewritten"),
    }


def _print_migrate_report(report: dict) -> None:
    share = report.get("in_vocabulary_share") or {}
    before = share.get("before", {}).get("share")
    after = share.get("after", {}).get("share")
    print(f"→ migrate-vocabulary: {len(report['tickets'])} ticket(s) scanned, "
         f"{report['rewritten']} rewritten, "
         f"{len(report.get('unmappable') or [])} unmappable, "
         f"{len(report.get('ambiguous') or [])} ambiguous")
    if before is not None and after is not None:
        print(f"  in-vocabulary share: {before:.1%} -> {after:.1%}")
    if report.get("skipped"):
        print(f"  skipped: {report['skipped']}")


def _run_migrate(args) -> int:
    """The batch mode's one entry point (KLC-111 AC-6, AC-11). The dispatch
    and the ticket-less argument surface are step-4's; this step (step-5)
    backs it with the real read-only walk. Step-6 adds the write path for
    a non-dry-run invocation."""
    report = _migrate_report(bool(args.dry_run))
    if args.json:
        print(json.dumps(report))
    else:
        _print_migrate_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
