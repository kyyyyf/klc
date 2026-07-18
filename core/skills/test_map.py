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
import re
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))
from core.shared.paths import klc_index_dir, project_root  # noqa: E402
import module_membership as _mm  # noqa: E402

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

_TEST_BASENAME_RE = re.compile(
    r"(^test_.*|.*_test$|^conftest$|.*\.test$|.*\.spec$|.*_spec$)"
)
_TEST_DIR_RE = re.compile(r"(^|/)(tests?|__tests__|spec)(/|$)")


def is_test_file(path: str) -> bool:
    """True for a test/spec file by directory or basename convention."""
    if _TEST_DIR_RE.search(path):
        return True
    stem = Path(path).stem
    return bool(_TEST_BASENAME_RE.match(stem))


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


def _prod_stem_candidates(test_stem: str) -> set[str]:
    """The production stems a test filename could pair with by name similarity."""
    cands = set()
    if test_stem.startswith("test_"):
        cands.add(test_stem[len("test_"):])
    if test_stem.endswith("_test"):
        cands.add(test_stem[: -len("_test")])
    if test_stem.endswith(".test") or test_stem.endswith(".spec"):
        cands.add(test_stem.rsplit(".", 1)[0])
    if test_stem.endswith("_spec"):
        cands.add(test_stem[: -len("_spec")])
    return {c for c in cands if c}


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
                   callgraph: dict | None) -> dict:
    """Deterministic production↔tests map. Pure; no timestamp (AC-11)."""
    errors: list[str] = []
    notes: list[str] = []

    files = _candidate_files(depgraph or {})
    if not files:
        errors.append("depgraph absent/empty — no import-graph file listing; "
                      "production_to_tests will be empty")
    test_files = {f for f in files if is_test_file(f)}
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

    # 3. name_similarity — test stem pairs with production stem.
    prod_by_stem: dict[str, list[str]] = {}
    for p in prod_files:
        prod_by_stem.setdefault(Path(p).stem, []).append(p)
    for t in test_files:
        for stem in _prod_stem_candidates(Path(t).stem):
            for p in prod_by_stem.get(stem, []):
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

    return {
        "production_to_tests": prod_to_tests,
        "module_to_tests": {m: sorted(v) for m, v in sorted(module_to_tests.items())},
        "errors": errors,
        "notes": notes,
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

    result = build_test_map(structural, depgraph, modules, callgraph)
    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for e in result["errors"]:
        sys.stderr.write(f"test_map: warning: {e}\n")
    print(f"test_map: mapped {len(result['production_to_tests'])} production file(s) "
          f"to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
