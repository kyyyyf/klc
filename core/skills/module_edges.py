"""module_edges.py — deterministic module edge aggregation (coarse + v2 detailed).

Two layers, one aggregator (planning_indexer.md §2 "во избежание двух источников
рёбер"):

  - COARSE (unchanged): ``aggregate_module_edges(modules_data, depgraph)`` maps
    file-to-file import edges to module-level ``depends_on`` / ``depended_by`` and
    writes them back into ``modules.json``. Imported by ``scripts/init.py`` and
    ``scripts/update.py`` — its signature and behaviour are FROZEN.
  - DETAILED v2 (KLC-070 step-3): ``build_detailed_edges()`` emits ranked,
    evidence-backed edges to a SEPARATE ``module_edges.json``. Ranking is by the
    number of DISTINCT ``(source, type)`` evidence classes — not raw edge count, and
    never by LLM/decompose guesses (those go only into ``advisory_reason`` and are not
    counted). ``main()`` writes both outputs; the CLI is built on top of the coarse
    aggregator, never replacing it.

Deterministic and authoritative; the LLM decompose agent's hand-written edges are
advisory (the coarse layer overwrites them; the detailed layer never counts them).
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))

# KLC-066: the ONE file→module resolver. The private longest-prefix copy that
# used to live here (boundary-aware `startswith(mpath + "/")`) is deleted so
# module_edges attributes files to exactly the same module set as scope_delta /
# diff-modules / public-api-filter / update. That reconciliation also fixes a
# latent bug: file-module paths (e.g. `core/phases/intake` owning
# `core/phases/intake.py`) are now attributed to the file-module, not its parent
# dir-module, which the boundary-aware match missed.
import module_membership as _mm


def aggregate_module_edges(modules_data: dict, depgraph: dict) -> dict:
    """Return a new modules_data dict with depends_on/depended_by filled
    deterministically from depgraph file edges.

    Args:
        modules_data: dict with {"modules": [...]} shape (object form).
        depgraph: dict with {"import_graphs": {lang: {"edges": [...]}}} shape.

    Returns:
        A deep copy of modules_data with depends_on/depended_by overwritten.
    """
    result = copy.deepcopy(modules_data)
    modules: list[dict] = result.get("modules", [])

    # Collect all file-edge pairs from every language's import_graphs
    all_edges: list[tuple[str, str]] = []
    for lang_data in (depgraph.get("import_graphs") or {}).values():
        for edge in (lang_data.get("edges") or []):
            src = edge.get("from") or ""
            tgt = edge.get("to") or ""
            if src and tgt:
                all_edges.append((src, tgt))

    # Map file edges to module edges (deduplicated, self-edges dropped)
    depends_on: dict[str, set[str]] = {m["name"]: set() for m in modules}
    depended_by: dict[str, set[str]] = {m["name"]: set() for m in modules}

    for src_file, tgt_file in all_edges:
        src_mod = _mm.primary_module(src_file, result)
        tgt_mod = _mm.primary_module(tgt_file, result)
        if src_mod is None or tgt_mod is None:
            continue
        if src_mod == tgt_mod:
            continue
        depends_on[src_mod].add(tgt_mod)
        depended_by[tgt_mod].add(src_mod)

    # Write back (sorted for determinism)
    for m in modules:
        name = m["name"]
        m["depends_on"] = sorted(depends_on.get(name, set()))
        m["depended_by"] = sorted(depended_by.get(name, set()))

    return result


# --- v2 detailed edges (KLC-070 step-3) --------------------------------------

# Per-evidence confidence by relationship type (planning_indexer.md example).
_EVIDENCE_CONFIDENCE = {
    "runtime_import": "high", "test_import": "high",
    "call": "medium", "build_time": "medium", "dependency_api": "medium",
}


def _is_test_file(path: str) -> bool:
    """Local, cheap test-file check (kept private; test_map owns the richer one)."""
    import re
    return bool(re.search(r"(^|/)(tests?|__tests__|spec)(/|$)", path)
                or re.match(r"(test_.*|.*_test|conftest)$", Path(path).stem))


def _confidence_from_classes(n_classes: int) -> str:
    """Edge confidence enum from the count of DISTINCT evidence classes."""
    if n_classes >= 3:
        return "high"
    if n_classes == 2:
        return "medium"
    return "low"


def _collect_evidence(modules_data: dict, depgraph: dict,
                      callgraph: dict | None) -> list[dict]:
    """Evidence records from DETERMINISTIC sources only.

    Each record is ``{source, type, from(file), to(file), confidence, from_module,
    to_module}`` for a file edge that crosses two distinct modules. LLM/decompose
    ``depends_on`` in modules.json is deliberately NOT a source here.
    """
    records: list[dict] = []

    def _emit(source: str, type_: str, frm: str, to: str) -> None:
        fm = _mm.primary_module(frm, modules_data)
        tm = _mm.primary_module(to, modules_data)
        if fm is None or tm is None or fm == tm:
            return
        records.append({
            "source": source, "type": type_, "from": frm, "to": to,
            "confidence": _EVIDENCE_CONFIDENCE.get(type_, "low"),
            "from_module": fm, "to_module": tm,
        })

    # import graph → runtime_import / test_import
    for g in (depgraph.get("import_graphs") or {}).values():
        for e in g.get("edges") or []:
            frm, to = e.get("from"), e.get("to")
            if frm and to:
                _emit("import_graph",
                      "test_import" if _is_test_file(frm) else "runtime_import",
                      frm, to)

    # package graph → build_time (coarse; module-level packages absent here)
    for g in (depgraph.get("package_graphs") or {}).values():
        for e in g.get("edges") or []:
            frm, to = e.get("from"), e.get("to")
            if frm and to:
                _emit("package_graph", "build_time", frm, to)

    # call graph → call
    symbols = (callgraph or {}).get("symbols") or {}
    if isinstance(symbols, dict):
        for key, meta in symbols.items():
            defined_in = (meta or {}).get("file") or (
                key.split("::", 1)[0] if "::" in key else "")
            for caller in (meta or {}).get("called_by") or []:
                caller_file = caller.split("::", 1)[0] if "::" in caller else caller
                if defined_in and caller_file:
                    _emit("callgraph", "call", caller_file, defined_in)

    return records


def build_detailed_edges(modules_data: dict, depgraph: dict,
                         callgraph: dict | None = None,
                         advisory: dict | None = None) -> dict:
    """Ranked, evidence-backed module edges. Pure; no timestamp (AC-11).

    ``advisory`` maps ``(from_module, to_module) -> reason`` (an LLM/decompose hint).
    It is attached as ``advisory_reason`` for context but NEVER contributes to
    ``evidence_count`` or ``confidence`` — the model guess must not re-enter the
    planning graph (planning_indexer.md §2 "LLM/decompose evidence в ранжирование не
    входит").
    """
    records = _collect_evidence(modules_data, depgraph, callgraph)

    by_pair: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        by_pair.setdefault((r["from_module"], r["to_module"]), []).append(r)

    edges: list[dict] = []
    for (frm, to), recs in by_pair.items():
        classes = {(r["source"], r["type"]) for r in recs}
        evidence = sorted(
            ({"source": r["source"], "type": r["type"], "from": r["from"],
              "to": r["to"], "confidence": r["confidence"]} for r in recs),
            key=lambda e: (e["source"], e["type"], e["from"], e["to"]),
        )
        edge_types = sorted({r["type"] for r in recs})
        edge = {
            "from": frm, "to": to,
            "edge_types": edge_types,
            "evidence": evidence,
            "evidence_count": len(classes),
            "confidence": _confidence_from_classes(len(classes)),
            "direction": "outbound",
            "expand_by_default": (len(classes) >= 2
                                  or "runtime_import" in edge_types),
        }
        if advisory and (frm, to) in advisory:
            edge["advisory_reason"] = advisory[(frm, to)]
        edges.append(edge)

    edges.sort(key=lambda e: (-e["evidence_count"], e["from"], e["to"]))
    return {"edges": edges}


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_callgraph_dir(cg_dir: Path) -> dict | None:
    """Merge ALL per-language callgraph files (FIX-3: not just python.json), so
    non-Python ``call`` evidence contributes to edge_types / evidence_count / rank."""
    if not cg_dir.is_dir():
        return None
    merged: dict[str, dict] = {}
    for f in sorted(cg_dir.glob("*.json")):
        data = _load_json(f)
        syms = data.get("symbols") if isinstance(data, dict) else None
        if isinstance(syms, dict):
            merged.update(syms)
    return {"symbols": merged} if merged else None


def main(argv: list[str] | None = None) -> int:
    from core.shared.paths import klc_index_dir
    idx = klc_index_dir()
    ap = argparse.ArgumentParser(
        description="Module edges: coarse (modules.json) + detailed v2 (module_edges.json)")
    ap.add_argument("--in-modules", type=Path, default=idx / "modules.json")
    ap.add_argument("--in-depgraph", type=Path, default=idx / "depgraph.json")
    ap.add_argument("--in-callgraph-dir", type=Path, default=idx / "callgraph")
    ap.add_argument("--out-modules", type=Path, default=idx / "modules.json")
    ap.add_argument("--out-edges", type=Path, default=idx / "module_edges.json")
    ap.add_argument("--edges-only", action="store_true",
                    help="write only module_edges.json; do NOT re-aggregate/rewrite "
                         "modules.json (FIX-4 — the planning-views pipeline mode, so "
                         "modules.json is written exactly once, by its own step)")
    args = ap.parse_args(argv)

    modules_data = _load_json(args.in_modules)
    if not modules_data:
        sys.stderr.write(
            f"module_edges: required input {args.in_modules} missing/empty\n")
        return 2
    if not isinstance(modules_data, dict):
        modules_data = {"modules": modules_data}
    depgraph = _load_json(args.in_depgraph)
    callgraph = _load_callgraph_dir(args.in_callgraph_dir)

    if args.edges_only:
        # Pipeline mode: modules.json is untouched (AC-13). Membership resolution
        # only needs paths, not the coarse depends_on, so pass modules_data as-is.
        base = modules_data
    else:
        # Standalone CLI: also refresh the coarse depends_on in modules.json.
        base = aggregate_module_edges(modules_data, depgraph)
        args.out_modules.parent.mkdir(parents=True, exist_ok=True)
        args.out_modules.write_text(
            json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")

    # Detailed layer.
    detailed = build_detailed_edges(base, depgraph, callgraph)
    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **detailed,
    }
    args.out_edges.parent.mkdir(parents=True, exist_ok=True)
    args.out_edges.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    coarse_note = ("modules.json untouched (--edges-only)" if args.edges_only
                   else f"coarse → {args.out_modules}")
    print(f"module_edges: {len(detailed['edges'])} detailed edge(s) → {args.out_edges}; "
          f"{coarse_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
