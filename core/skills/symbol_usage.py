#!/usr/bin/env python3
"""symbol_usage.py — derived impact-radius view (KLC-071 step-6).

Answers "if a feature changes this function/class/type, who are its consumers and
tests?". It is a DERIVED VIEW over ``inventory.json`` (definitions, kind, visibility —
KLC-070 frozen schema) + ``callgraph/<lang>.json`` (``called_by``), NOT a third parser
of the same data (planning_indexer.md §5). No LLM.

``inventory.json`` is the REQUIRED input (defines the symbol universe) — absent → exit 2.

Degraded mode (planning_indexer.md §5): the callgraph is built on-demand and not
guaranteed. When it is absent, ``used_by`` falls back to FILE-LEVEL usage from the
import graph (a consumer file that imports the defining file), marked
``usage_type:"import"`` / ``confidence:"low"``, and the view still exists rather than
disappearing. Full symbol-level ``used_by`` (``usage_type:"call"``) returns once the
callgraph is built. All per-language callgraph files are merged via the KLC-070
``load_callgraph_dir`` pattern, so ``call`` usage works on non-Python projects too.

Output schema (planning_indexer.md §5); symbols are keyed ``<file>::<name>`` — the same
convention the callgraph/test_map use (the plan's dotted example key is not
language-portable, so the file::name key is used deterministically instead):

    {
      "symbols": {
        "<file>::<name>": {
          "kind": str, "defined_in": str, "module_name": str|null,
          "visibility": "public"|"private",
          "used_by": [ {"file","module_name","usage_type","confidence"} ],
          "tested_by": [ "<test file>" ],
          "change_risk": "low"|"medium"|"high"
        }
      },
      "errors": [str], "notes": [str]
    }

Every file→module attribution routes through ``module_membership.file_to_module``
(KLC-066) — no private matcher (C-002).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))
from core.shared.paths import klc_index_dir  # noqa: E402
import module_membership as _mm  # noqa: E402
import test_map as _tm  # noqa: E402  (reuse is_test_file + load_callgraph_dir)

# Re-export the KLC-070 loader so callers/tests use one merge implementation.
load_callgraph_dir = _tm.load_callgraph_dir


def _caller_file(caller: str) -> str:
    """A callgraph caller token ``file::symbol`` (or bare file) → the file."""
    return caller.split("::", 1)[0] if "::" in caller else caller


def _unqualify(name: str) -> str:
    """Strip a class / namespace qualifier from a symbol name so a callgraph's
    qualified method key matches the UNQUALIFIED inventory symbol (FIX-1):
    ``Class.method`` → ``method``, ``Ns::Class::run`` → ``run``, ``fn`` → ``fn``."""
    tail = name
    for sep in ("::", "."):
        if sep in tail:
            tail = tail.rsplit(sep, 1)[-1]
    return tail or name


def _callgraph_index(callgraph: dict | None) -> dict[str, list[str]]:
    """Map ``<file>::<name>`` → called_by, indexing BOTH the qualified name and its
    unqualified tail (FIX-1). Inventory records exported methods unqualified
    (``method``) while the callgraph key is qualified (``a.py::Class.method`` / C++
    ``a.cpp::Ns::Class::run``); without the unqualified alias every caller of a public
    method is dropped and its change_risk wrongly collapses to ``low``. Entries are
    MERGED (not overwritten) so two same-named methods in one file keep all callers."""
    idx: dict[str, list[str]] = {}

    def _add(k: str, callers: list[str]) -> None:
        bucket = idx.setdefault(k, [])
        for c in callers:
            if c not in bucket:
                bucket.append(c)

    symbols = (callgraph or {}).get("symbols") or {}
    if not isinstance(symbols, dict):
        return idx
    for key, meta in symbols.items():
        called_by = list((meta or {}).get("called_by") or [])
        _add(key, called_by)
        f = (meta or {}).get("file") or (key.split("::", 1)[0] if "::" in key else "")
        name = key.split("::", 1)[1] if "::" in key else key
        if f and name:
            _add(f"{f}::{name}", called_by)          # qualified alias
            unq = _unqualify(name)
            if unq != name:
                _add(f"{f}::{unq}", called_by)        # unqualified alias
    return idx


def _import_consumers(depgraph: dict | None) -> dict[str, list[str]]:
    """file → list of files that import it (file-level, for degraded mode)."""
    consumers: dict[str, list[str]] = {}
    for g in ((depgraph or {}).get("import_graphs") or {}).values():
        for e in g.get("edges") or []:
            frm, to = e.get("from"), e.get("to")
            if frm and to:
                consumers.setdefault(to, []).append(frm)
    return consumers


def _change_risk(visibility: str, n_users: int) -> str:
    """Deterministic risk from visibility + consumer fan-out."""
    if visibility == "public":
        if n_users >= 3:
            return "high"
        if n_users >= 1:
            return "medium"
        return "low"
    # private symbols: only many internal consumers lift the risk.
    return "medium" if n_users >= 3 else "low"


def build_symbol_usage(inventory: dict, modules: dict,
                       callgraph: dict | None, depgraph: dict | None) -> dict:
    """Deterministic symbol impact-radius map. Pure; no timestamp (AC-8)."""
    errors: list[str] = []
    notes: list[str] = []

    cg_idx = _callgraph_index(callgraph)
    degraded = not cg_idx
    import_consumers = _import_consumers(depgraph) if degraded else {}
    if degraded:
        notes.append("callgraph absent — used_by falls back to file-level import "
                     "usage (usage_type='import', confidence='low')")
        if not import_consumers:
            errors.append("no callgraph and no import graph — used_by will be empty")

    def _mod(path: str) -> str | None:
        return _mm.primary_module(path, modules or {})

    symbols_out: dict[str, dict] = {}
    for s in inventory.get("symbols") or []:
        name = s.get("name")
        defined_in = s.get("file")
        if not name or not defined_in:
            continue
        key = f"{defined_in}::{name}"
        visibility = s.get("visibility") or "public"

        used_by: list[dict] = []
        tested_by: set[str] = set()
        if not degraded:
            for caller in cg_idx.get(key, []):
                cf = _caller_file(caller)
                if not cf:
                    continue
                if _tm.is_test_file(cf):
                    tested_by.add(cf)
                else:
                    used_by.append({"file": cf, "module_name": _mod(cf),
                                    "usage_type": "call", "confidence": "medium"})
        else:
            for cf in import_consumers.get(defined_in, []):
                if _tm.is_test_file(cf):
                    tested_by.add(cf)
                else:
                    used_by.append({"file": cf, "module_name": _mod(cf),
                                    "usage_type": "import", "confidence": "low"})

        # dedupe used_by by file (keep first/highest signal), sort deterministically.
        seen: dict[str, dict] = {}
        for u in used_by:
            seen.setdefault(u["file"], u)
        used_by = sorted(seen.values(), key=lambda u: u["file"])

        symbols_out[key] = {
            "kind": s.get("kind") or "symbol",
            "defined_in": defined_in,
            "module_name": _mod(defined_in),
            "visibility": visibility,
            "used_by": used_by,
            "tested_by": sorted(tested_by),
            "change_risk": _change_risk(visibility, len(used_by)),
        }

    return {"symbols": dict(sorted(symbols_out.items())),
            "errors": errors, "notes": notes}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    idx = klc_index_dir()
    ap = argparse.ArgumentParser(description="Derived symbol impact-radius view")
    ap.add_argument("--in-inventory", type=Path, default=idx / "inventory.json")
    ap.add_argument("--in-modules", type=Path, default=idx / "modules.json")
    ap.add_argument("--in-callgraph-dir", type=Path, default=idx / "callgraph")
    ap.add_argument("--in-depgraph", type=Path, default=idx / "depgraph.json")
    ap.add_argument("--out", type=Path, default=idx / "symbol_usage.json")
    args = ap.parse_args(argv)

    if not args.in_inventory.exists():
        sys.stderr.write(
            f"symbol-usage: required input inventory.json not found at "
            f"{args.in_inventory}\n")
        return 2
    inventory = _load(args.in_inventory)
    if not isinstance(inventory, dict) or "symbols" not in inventory:
        sys.stderr.write(
            f"symbol-usage: inventory.json malformed at {args.in_inventory}\n")
        return 2

    modules = _load(args.in_modules)
    if not isinstance(modules, dict):
        modules = {"modules": modules}
    callgraph = load_callgraph_dir(args.in_callgraph_dir)  # merges all languages
    depgraph = _load(args.in_depgraph)

    result = build_symbol_usage(inventory, modules, callgraph, depgraph)
    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for e in result["errors"]:
        sys.stderr.write(f"symbol-usage: warning: {e}\n")
    print(f"symbol-usage: mapped {len(result['symbols'])} symbol(s) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
