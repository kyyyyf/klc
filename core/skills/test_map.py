#!/usr/bin/env python3
"""test_map.py — deterministic production↔tests map (KLC-070 step-2).

Fills the real hole in the klc index: there is currently no mapping from tests to the
production code they exercise. This builder derives that mapping deterministically from
the import graph, the call graph (when built), module membership, and filename
similarity. No LLM is involved (planning_indexer.md §"test_map.json").

Every test→production link is classified by the highest-priority relationship that
holds, in this order (planning_indexer.md §4):

    direct_import > call > same_module > name_similarity > cochange

``cochange`` (git-history co-change) is a v1 non-goal — it is documented in the enum
and recorded in ``notes`` but not computed, so the output stays byte-deterministic and
offline (AC-11 / degrade-not-fail).

Output schema (production_to_tests is an OBJECT per file so coverage/tests share one
shape and a fallback never changes the type):

    {
      "production_to_tests": {
        "<prod file>": {
          "coverage": "direct" | "module" | "none",
          "tests": [ {"test_file","relationship","confidence"} ]
        }
      },
      "module_to_tests": { "<module name>": ["<test file>", ...] },
      "errors": [str],
      "notes":  [str]
    }

A file with no tests gets an explicit ``{"coverage": "none", "tests": []}`` record —
never omission — so the test-planner sees the hole rather than assuming "no tests
needed". FIX-6: ``coverage`` is derived only from FILE-SPECIFIC signals
(``direct_import`` / ``call`` → ``direct``; ``name_similarity`` → ``module``); a file
whose only association is a co-located test (``same_module``) reports ``none`` so a
true per-file hole in a partly-tested module is not masked. ``same_module`` lives in
``module_to_tests`` instead. All membership comparisons route through
``module_membership.file_to_module`` (KLC-066) — no private matcher.

Callgraph loading (FIX-2/FIX-3): ALL per-language callgraph files present in the
callgraph dir are merged (``rust.json`` / ``cpp.json`` / ``python.json`` / …), so
``call`` links work on non-Python projects too.
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
from core.shared.paths import klc_index_dir, project_root  # noqa: E402
import module_membership as _mm  # noqa: E402
import index_coverage  # noqa: E402
import test_conventions as _tc  # noqa: E402  (KLC-109: the shared test-path table)
import file_universe as _fu  # noqa: E402  (KLC-105: the one universe resolver)

# Full relationship enum + confidence (planning_indexer.md §4). Priority high→low:
#   direct_import > call > same_module > name_similarity > cochange
_REL_CONFIDENCE = {
    "direct_import": "high", "call": "high",
    "same_module": "medium", "name_similarity": "medium", "cochange": "low",
}
# FIX-6: only FILE-SPECIFIC relationships become per-file production_to_tests rows.
# same_module (co-located) and cochange are MODULE-level signals — they populate
# module_to_tests instead, so (a) a genuinely-untested file inside a partly-tested
# module stays visible as coverage:"none" (the test-planner sees the real hole), and
# (b) we avoid an O(N_prod × N_test) same_module cross-product exploding the file.
_FILE_REL_ORDER = ["direct_import", "call", "name_similarity"]
_DIRECT_COVERAGE = {"direct_import", "call"}
_MODULE_COVERAGE = {"name_similarity"}
# KLC-109 AC-8: every row's provenance, independent of its (unchanged) relationship
# name/confidence tier — "name_similarity" is now driven by the shared convention
# table (test_conventions.production_candidates), not a private stem matcher.
_REL_SOURCE = {"direct_import": "import", "call": "callgraph",
              "name_similarity": "convention"}

def _candidate_files(depgraph: dict) -> set[str]:
    files: set[str] = set()
    for g in (depgraph.get("import_graphs") or {}).values():
        for node in g.get("nodes") or []:
            nid = node.get("id") if isinstance(node, dict) else node
            if nid:
                files.add(nid)
        for e in g.get("edges") or []:
            for k in ("from", "to"):
                if e.get(k):
                    files.add(e[k])
    return files


def _import_edges(depgraph: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for g in (depgraph.get("import_graphs") or {}).values():
        for e in g.get("edges") or []:
            frm, to = e.get("from"), e.get("to")
            if frm and to:
                out.append((frm, to))
    return out


def _callgraph_call_links(callgraph: dict, prod_files: set[str],
                          test_files: set[str]) -> set[tuple[str, str]]:
    """(prod_file, test_file) pairs where a test symbol calls a prod symbol."""
    links: set[tuple[str, str]] = set()
    symbols = (callgraph or {}).get("symbols") or {}
    if not isinstance(symbols, dict):
        return links
    for key, meta in symbols.items():
        defined_in = (meta or {}).get("file") or (
            key.split("::", 1)[0] if "::" in key else "")
        if defined_in not in prod_files:
            continue
        for caller in (meta or {}).get("called_by") or []:
            caller_file = caller.split("::", 1)[0] if "::" in caller else caller
            if caller_file in test_files:
                links.add((defined_in, caller_file))
    return links


def build_test_map(structural: dict, depgraph: dict, modules: dict,
                   callgraph: dict | None, *, universe: list[str] | None = None,
                   table=None) -> dict:
    """Deterministic production↔tests map. Pure; no timestamp (AC-11).

    KLC-109 (D-201): the file universe comes from the caller-supplied
    ``universe=`` (``main()`` fills it from ``file_universe.resolve``) or else
    ``structural["files_rel"]`` — the field ``file_scanner.scan()`` ships
    (KLC-074) — and from NOWHERE else. There is deliberately NO
    filesystem-walk fallback: when neither is available, the convention layer
    degrades to graph-derived candidates only (or empty, with no depgraph
    either), with an honest ``errors[]`` note, never a guessed file list.
    ``table=`` (KLC-109 D-203) is the profile-extended test-path table;
    ``main()`` passes ``test_conventions.active_table()``, every other caller
    defaults to the built-in table (purity/determinism, C-002)."""
    errors: list[str] = []
    notes: list[str] = []

    graph_files = _candidate_files(depgraph or {})
    # KLC-109/D-201: the declared universe (when present) is AUTHORITATIVE — it
    # is the full convention base layer, not merely a filter over graph-derived
    # candidates (which is empty on exactly the unindexed project AC-7 exists
    # for). A depgraph node OUTSIDE the declared universe still gets dropped
    # (KLC-105's own closure guarantee, kept verbatim).
    declared = universe if universe is not None else (structural or {}).get("files_rel")
    if isinstance(declared, list) and declared:
        files = {f for f in declared if f}
        dropped = sorted(f for f in graph_files if f not in files)
        if dropped:
            notes.append(f"{len(dropped)} out-of-universe candidate file(s) dropped "
                         f"(not in structural.files_rel)")
    else:
        files = graph_files
        errors.append("structural.files_rel unavailable — convention layer empty; "
                      "production_to_tests covers graph-derived edges only")

    if not files:
        errors.append("depgraph absent/empty — no import-graph file listing; "
                      "production_to_tests will be empty")
    tbl = table if table is not None else _tc.builtin_table()
    # KLC-109 review-fix round 2 (D-109-11, MEDIUM): exists= is membership in
    # `files` — the SAME KLC-105 universe this function already resolved
    # above — so a basename-only match (Foo.spec.js, foo_test.go, ...) is
    # confirmed against the declared universe, never the live filesystem
    # (AC-1 holds: this is a pure set lookup). This is what makes AC-7's
    # "convention alone, no callgraph/import-graph" per-language pairs work
    # under D-109-9's conservative default, and what stops test_map.py/
    # test_conventions.py from self-classifying as tests (no map.py/
    # conventions.py sibling anywhere in `files`).
    test_files = {f for f in files if _tc.is_test_path(f, table=tbl, exists=files.__contains__)}
    prod_files = {f for f in files if f not in test_files}

    # FILE-SPECIFIC relationships only (FIX-6): rel[(prod, test)] = set of names.
    rel: dict[tuple[str, str], set[str]] = {}

    def add(prod: str, test: str, name: str) -> None:
        rel.setdefault((prod, test), set()).add(name)

    # 1. direct_import — test imports production file.
    for frm, to in _import_edges(depgraph or {}):
        if frm in test_files and to in prod_files:
            add(to, frm, "direct_import")

    # 2. call — test symbol calls a production symbol (callgraph, if present).
    if callgraph:
        for prod, test in _callgraph_call_links(callgraph, prod_files, test_files):
            add(prod, test, "call")
    else:
        notes.append("callgraph absent — 'call' relationship skipped "
                     "(import/name/module signals only)")

    # 3. name_similarity — the ALWAYS-AVAILABLE convention base layer (AC-7),
    # driven by the SHARED test_conventions.production_candidates (KLC-109),
    # not a private python-only stem matcher — works for every AC-2 language
    # with no callgraph and no import graph at all.
    prod_by_key: dict[tuple[str, str], list[str]] = {}
    for p in prod_files:
        prod_by_key.setdefault((Path(p).stem, Path(p).suffix), []).append(p)
    for t in sorted(test_files):
        for cand in _tc.production_candidates(t, table=tbl):
            if cand in prod_files:
                add(cand, t, "name_similarity")
                continue
            key = (Path(cand).stem, Path(cand).suffix)
            for p in sorted(prod_by_key.get(key, [])):
                add(p, t, "name_similarity")

    prod_mod = {p: _mm.primary_module(p, modules or {}) for p in prod_files}
    test_mod = {t: _mm.primary_module(t, modules or {}) for t in test_files}

    # production_to_tests: highest FILE-SPECIFIC relationship per (prod, test).
    prod_to_tests: dict[str, dict] = {}
    for p in sorted(prod_files):
        rows = []
        for t in sorted(test_files):
            names = rel.get((p, t))
            if not names:
                continue
            best = min(names, key=_FILE_REL_ORDER.index)
            rows.append({"test_file": t, "relationship": best,
                         "source": _REL_SOURCE[best],
                         "confidence": _REL_CONFIDENCE[best]})
        rel_names = {r["relationship"] for r in rows}
        cov = "direct" if (rel_names & _DIRECT_COVERAGE) else (
            "module" if (rel_names & _MODULE_COVERAGE) else "none")
        prod_to_tests[p] = {"coverage": cov, "tests": rows}

    # module_to_tests: file-specific links PLUS the module-level same_module signal
    # (co-located tests). O(N_prod + N_test) — no cross-product.
    modules_with_prod = {prod_mod[p] for p in prod_files if prod_mod[p] is not None}
    module_to_tests: dict[str, set[str]] = {}
    for p, entry in prod_to_tests.items():
        pm = prod_mod[p]
        if pm is None:
            continue
        for row in entry["tests"]:
            module_to_tests.setdefault(pm, set()).add(row["test_file"])
    for t in test_files:                       # same_module: co-located test files
        tm = test_mod[t]
        if tm is not None and tm in modules_with_prod:
            module_to_tests.setdefault(tm, set()).add(t)

    notes.append("same_module & cochange are module-level signals (module_to_tests "
                 "only); a file with no direct/call/name link stays coverage:none. "
                 "cochange not computed in v1.")

    # KLC-106 AC-8 / D-212 (review round 1, HIGH finding #1): a bare-absent
    # callgraph is NOT by itself a degraded input — scripts/init.py and
    # scripts/update.py never build one (Q-103), so that would be the
    # default, permanent state of every ordinary index. It only counts when
    # this consumer's own production_to_tests output is genuinely vacuous
    # (no file-specific coverage came from ANY signal, callgraph included) —
    # or when the callgraph was actually built and turned out unusable, via
    # the one shared rule in index_coverage.callgraph_degraded_input.
    produced_coverage = any(
        entry["coverage"] != "none" for entry in prod_to_tests.values())
    degraded_inputs = index_coverage.degraded_inputs([
        ("depgraph.json", depgraph, not files),
        ("callgraph", callgraph,
         index_coverage.callgraph_degraded_input(callgraph, produced_coverage)),
        ("structural.json", structural, not structural),
    ])
    return {
        "production_to_tests": prod_to_tests,
        "module_to_tests": {m: sorted(v) for m, v in sorted(module_to_tests.items())},
        "errors": errors,
        "notes": notes,
        "degraded": bool(degraded_inputs),
        "degraded_inputs": degraded_inputs,
    }


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_callgraph_dir(cg_dir: Path) -> dict | None:
    """Merge ALL per-language callgraph files in *cg_dir* into one {"symbols": {...}}.

    FIX-2 (codex P2): loading only ``python.json`` loses every ``call`` link on a
    Rust/C++ project (whose callgraph is ``rust.json`` / ``cpp.json``). Merge every
    ``*.json`` present; returns None when the dir is absent/empty so callers degrade.
    """
    if not cg_dir.is_dir():
        return None
    merged: dict[str, dict] = {}
    for f in sorted(cg_dir.glob("*.json")):
        data = _load(f)
        syms = data.get("symbols") if isinstance(data, dict) else None
        if isinstance(syms, dict):
            merged.update(syms)
    return {"symbols": merged} if merged else None


def main(argv: list[str] | None = None) -> int:
    idx = klc_index_dir()
    ap = argparse.ArgumentParser(description="Deterministic production↔tests map")
    # FIX-5: default to project_root() (PROJECT_ROOT from env, C-002), not cwd.
    ap.add_argument("--root", type=Path, default=project_root())
    ap.add_argument("--in-structural", type=Path, default=idx / "structural.json")
    ap.add_argument("--in-depgraph", type=Path, default=idx / "depgraph.json")
    ap.add_argument("--in-modules", type=Path, default=idx / "modules.json")
    ap.add_argument("--in-callgraph-dir", type=Path, default=idx / "callgraph")
    ap.add_argument("--out", type=Path, default=idx / "test_map.json")
    args = ap.parse_args(argv)

    if not args.root.is_dir():
        sys.stderr.write(f"test_map: not a directory: {args.root}\n")
        return 2

    structural = _load(args.in_structural)
    depgraph = _load(args.in_depgraph)
    modules = _load(args.in_modules)
    callgraph = load_callgraph_dir(args.in_callgraph_dir)  # merges all languages

    # KLC-109: the ONE universe resolver (file_universe.resolve, KLC-105) and the
    # ONE profile-table resolution point (test_conventions.active_table, D-203) —
    # main() never enumerates files or reads a manifest itself.
    resolved = _fu.resolve(args.root, structural=structural)
    result = build_test_map(structural, depgraph, modules, callgraph,
                            universe=resolved["files"], table=_tc.active_table())
    result["notes"] = [f"file universe source: {resolved['source']}",
                       *resolved["notes"], *result["notes"]]
    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for e in result["errors"]:
        sys.stderr.write(f"test_map: warning: {index_coverage.render_error(e)}\n")
    print(f"test_map: mapped {len(result['production_to_tests'])} production file(s) "
          f"to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
