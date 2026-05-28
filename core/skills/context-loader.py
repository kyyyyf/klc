#!/usr/bin/env python3
"""context-loader.py — lazy context loader for the task agent.

Given a set of modules (by name) and a traversal depth, return the minimum set
of files and public-API signatures that the task agent needs to reason about a
feature or bug. The goal is to stay well below 5% of the project's total
symbols.

Usage:
    context-loader.py --modules auth,payments [--depth 2] [--format json|markdown]

Output:
- Default JSON on stdout:
    {
      "requested_modules": [...],
      "included_modules":  [...],
      "depth":             2,
      "claude_md":         ["<abs path>", ...],
      "public_api":        { "<module>": [ {name, kind, file, line, signature} ] },
      "referenced_symbols":[ {name, file, line, signature} ],
      "stats": {
        "total_symbols_project": N,
        "selected_symbols":       M,
        "percent_of_project":     0.0xx,
        "budget_ok":              true | false
      },
      "warnings": [ "..." ]
    }

The skill is deterministic: it computes the set of module paths, their
CLAUDE.md files, and — using the dep-graph already captured in
inventory.json — the referenced symbols of immediate neighbours up to
`depth`. The task agent may then use LSP for full symbol lookup on this
narrowed scope.

Reads .klc/index/symbols_by_module.json (materialized by
public-api-filter.py) instead of walking inventory.json on every run.
Falls back to building the index on the fly when the materialized file
is missing — this keeps ad-hoc runs working without forcing a full
re-decompose first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import framework_root, klc_index_dir, project_root  # noqa: E402, F401


def load_json(p: Path) -> dict:
    if not p.exists():
        sys.stderr.write(f"context-loader: missing {p}\n")
        sys.exit(1)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_modules(requested: list[str], modules: list[dict]) -> list[dict]:
    by_name = {m["name"]: m for m in modules}
    out, unknown = [], []
    for name in requested:
        if name in by_name:
            out.append(by_name[name])
        else:
            unknown.append(name)
    if unknown:
        candidates = ", ".join(sorted(by_name)[:10])
        sys.stderr.write(
            "context-loader: unknown modules: "
            + ", ".join(unknown)
            + f". Known (first 10): {candidates}\n"
        )
        sys.exit(1)
    return out


def bfs_neighbours(
    seeds: list[str], modules: list[dict], depth: int
) -> list[str]:
    by_name = {m["name"]: m for m in modules}
    visited = {}
    queue = deque((s, 0) for s in seeds)
    while queue:
        name, d = queue.popleft()
        if name in visited:
            continue
        visited[name] = d
        if d >= depth:
            continue
        m = by_name.get(name)
        if not m:
            continue
        for neighbour in m.get("depends_on", []) + m.get("depended_by", []):
            if neighbour not in visited:
                queue.append((neighbour, d + 1))
    return list(visited.keys())


def load_symbols_by_module(
    modules: list[dict], inventory: dict | None = None
) -> dict[str, list[dict]]:
    """Load the per-module symbol index. Prefers the materialized file at
    .klc/index/symbols_by_module.json (written by public-api-filter.py);
    if it is missing or stale-looking, rebuilds it on the fly from
    `inventory` so ad-hoc runs still work."""
    sbm_path = klc_index_dir() / "symbols_by_module.json"
    if sbm_path.exists():
        try:
            payload = json.loads(sbm_path.read_text(encoding="utf-8"))
            idx = payload.get("modules") or {}
            # Sanity: every module in modules.json should appear as a key.
            # Missing keys are fine (module had zero authored symbols); an
            # extra key means someone renamed modules without re-running
            # public-api-filter — prefer the on-disk data anyway and let
            # periodic/docgen surface the drift.
            if all(m["name"] in idx or idx.get(m["name"]) == [] for m in modules):
                return {m["name"]: idx.get(m["name"], []) for m in modules}
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                f"context-loader: could not read {sbm_path} ({exc}); "
                "falling back to on-the-fly build from inventory\n"
            )
    return _build_symbols_by_module_from_inventory(inventory or {}, modules)


def _build_symbols_by_module_from_inventory(
    inventory: dict, modules: list[dict]
) -> dict[str, list[dict]]:
    """Fallback path when symbols_by_module.json is absent. One pass over
    inventory.symbols with longest-prefix assignment."""
    sorted_modules = sorted(modules, key=lambda m: -len(m.get("path", "")))
    index: dict[str, list[dict]] = {m["name"]: [] for m in modules}
    for _lang, entry in inventory.get("symbols", {}).items():
        for item in entry.get("items", []):
            f = item.get("file", "")
            if not f:
                continue
            for m in sorted_modules:
                p = m.get("path", "")
                if p and f.startswith(p):
                    index[m["name"]].append(item)
                    break
    return index


def module_public_api(
    name: str, by_module: dict[str, list[dict]], modules: list[dict]
) -> list[dict]:
    mod = next((m for m in modules if m["name"] == name), None)
    if not mod:
        return []
    api_names = set(mod.get("public_api", []))
    items = by_module.get(name, [])
    if not api_names:
        return items
    return [it for it in items if it.get("name") in api_names]


def total_project_symbols_from_sbm(sbm: dict[str, list[dict]]) -> int:
    """Sum of authored symbols across all modules. Used as the budget
    denominator; does not need to match inventory.symbols.count exactly
    (the latter includes forward-decls and engine-imported symbols that
    the materialized index drops on purpose)."""
    total = sum(len(v) for v in sbm.values())
    return total or 1


def total_project_symbols(inventory: dict) -> int:
    """Fallback denominator when symbols_by_module.json is missing."""
    total = 0
    for entry in inventory.get("symbols", {}).values():
        total += int(entry.get("count", 0) or 0)
    return total or 1


def collect_claude_mds(module_names: list[str], modules: list[dict]) -> list[str]:
    paths = []
    root_md = project_root() / "CLAUDE.md"
    if root_md.exists():
        paths.append(str(root_md))
    for m in modules:
        if m["name"] not in module_names:
            continue
        p = project_root() / m["path"] / "CLAUDE.md"
        if p.exists():
            paths.append(str(p))
    return paths


def collect_adrs_from_claude_mds(claude_md_paths: list[str], budget_bytes: int) -> tuple[list[str], dict[str, str], list[str]]:
    """Phase 2.1: Extract ADR links from `## ADRs` sections, inline contents.

    Returns (adr_files, adr_inlined, warnings):
      adr_files:    list of absolute ADR paths
      adr_inlined:  dict {path: contents}
      warnings:     list of warning messages (e.g., over budget, unresolvable links)

    Budget: `budget_bytes` is the max total bytes of ADR content to inline.
    Drop newest-first when over budget.
    """
    import re

    adr_candidates: list[Path] = []
    warnings: list[str] = []

    # Parse each CLAUDE.md for `## ADRs` or `## Architecture Decision Records` section
    for md_path_str in claude_md_paths:
        md_path = Path(md_path_str)
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        in_adr_section = False
        for line in lines:
            stripped = line.strip()
            if stripped in ("## ADRs", "## Architecture Decision Records"):
                in_adr_section = True
                continue
            if in_adr_section:
                if stripped.startswith("## "):  # next section
                    break
                # Match markdown links: [ADR-NNN](path) or [ADR-NNN: title](path)
                m = re.match(r"^-?\s*\[ADR-\d+[^\]]*\]\(([^)]+)\)", stripped)
                if m:
                    link_target = m.group(1)
                    # Resolve relative to the CLAUDE.md directory
                    resolved = (md_path.parent / link_target).resolve()
                    if resolved.exists():
                        adr_candidates.append(resolved)
                    else:
                        warnings.append(f"ADR link unresolvable: {link_target} (from {md_path})")

    # Deduplicate by absolute path
    adr_paths = sorted(set(adr_candidates), key=lambda p: p.name)

    # Apply budget: compute cumulative sizes, drop newest-first when over
    adr_with_size: list[tuple[Path, int]] = []
    for p in adr_paths:
        try:
            size = p.stat().st_size
            adr_with_size.append((p, size))
        except OSError:
            warnings.append(f"ADR file unreadable: {p}")

    # Sort by name descending (newest ADR-NNN first), then take oldest-first up to budget
    adr_with_size.sort(key=lambda x: x[0].name, reverse=True)
    cumulative = 0
    selected: list[Path] = []
    dropped: list[Path] = []
    for p, size in adr_with_size:
        if cumulative + size <= budget_bytes:
            selected.append(p)
            cumulative += size
        else:
            dropped.append(p)

    if dropped:
        warnings.append(
            f"ADR budget exceeded ({cumulative}/{budget_bytes} bytes used); "
            f"dropped {len(dropped)} ADRs: {', '.join(d.name for d in dropped)}"
        )

    # Inline contents
    adr_inlined: dict[str, str] = {}
    for p in selected:
        try:
            adr_inlined[str(p)] = p.read_text(encoding="utf-8")
        except OSError as e:
            warnings.append(f"Failed to read ADR {p}: {e}")

    adr_files = [str(p) for p in selected]
    return adr_files, adr_inlined, warnings


def load_call_graph(language: str) -> dict | None:
    """Load call graph for given language from index/callgraph/<lang>.json.

    Returns None if file doesn't exist (call graph not built for this language).
    """
    cg_path = klc_index_dir() / "callgraph" / f"{language}.json"
    if not cg_path.exists():
        return None
    try:
        with cg_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("symbols", {})
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"context-loader: error loading {cg_path}: {e}\n")
        return None


def detect_language_from_file(file_path: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": "python",
        ".rs": "rust",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".h": "cpp",
        ".hpp": "cpp",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "typescript",
        ".jsx": "typescript",
    }
    return mapping.get(ext)


def bfs_call_graph(
    start_symbol: str,
    call_graph: dict,
    depth: int
) -> list[dict]:
    """BFS over call graph from start_symbol to depth.

    Returns list of symbol entries: [{qualified_name, kind, file, line, calls, called_by}]
    """
    if start_symbol not in call_graph:
        return []

    visited = {}
    queue = deque([(start_symbol, 0)])

    while queue:
        sym_name, d = queue.popleft()
        if sym_name in visited:
            continue
        visited[sym_name] = d

        sym_data = call_graph.get(sym_name)
        if not sym_data:
            continue

        if d >= depth:
            continue

        # Traverse both calls and called_by
        for callee in sym_data.get("calls", []):
            if callee not in visited:
                queue.append((callee, d + 1))

        for caller in sym_data.get("called_by", []):
            if caller not in visited:
                queue.append((caller, d + 1))

    # Collect symbol entries
    result = []
    for sym_name in visited:
        if sym_name in call_graph:
            entry = call_graph[sym_name].copy()
            entry["qualified_name"] = sym_name
            entry["depth"] = visited[sym_name]
            result.append(entry)

    return result


def run_symbol_mode(args) -> int:
    """Phase 4.5: symbol-level context via call graph BFS."""
    symbol = args.symbol
    depth = args.depth or 1

    # Parse symbol (format: file::name or file::Class.method)
    if "::" not in symbol:
        sys.stderr.write(f"context-loader: invalid symbol format '{symbol}' (expected file::name)\n")
        return 1

    file_part, name_part = symbol.split("::", 1)

    # Detect language
    language = detect_language_from_file(file_part)
    if not language:
        sys.stderr.write(f"context-loader: cannot detect language from {file_part}\n")
        return 1

    # Load call graph
    call_graph = load_call_graph(language)
    if call_graph is None:
        # Fallback: no call graph available
        sys.stderr.write(
            f"context-loader: no call graph for {language} (file: index/callgraph/{language}.json missing)\n"
            f"  falling back to whole-file context\n"
        )
        # Return minimal context: just the requested file
        result = {
            "mode": "symbol",
            "requested_symbol": symbol,
            "depth": depth,
            "call_graph_available": False,
            "fallback": "whole-file",
            "files": [file_part],
            "symbols": [],
            "warnings": [f"Call graph for {language} not available — returning whole file"]
        }
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # BFS over call graph
    symbols = bfs_call_graph(symbol, call_graph, depth)

    if not symbols:
        sys.stderr.write(f"context-loader: symbol '{symbol}' not found in call graph\n")
        return 1

    # Collect unique files
    files = sorted(set(s["file"] for s in symbols))

    # Stats
    total_symbols_in_graph = len(call_graph)
    selected_count = len(symbols)
    pct = selected_count / total_symbols_in_graph if total_symbols_in_graph else 0.0

    result = {
        "mode": "symbol",
        "requested_symbol": symbol,
        "depth": depth,
        "call_graph_available": True,
        "language": language,
        "files": files,
        "symbols": symbols,
        "stats": {
            "total_symbols_in_graph": total_symbols_in_graph,
            "selected_symbols": selected_count,
            "percent_of_graph": round(pct, 4),
            "files_touched": len(files),
        },
        "warnings": []
    }

    if args.format == "json":
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        # Markdown output
        sys.stdout.write(f"# Call graph context for: {symbol}\n\n")
        sys.stdout.write(f"Depth: {depth}, language: {language}\n")
        sys.stdout.write(f"Selected {selected_count} symbols across {len(files)} files\n\n")
        sys.stdout.write("## Files\n")
        for f in files:
            sys.stdout.write(f"- {f}\n")
        sys.stdout.write("\n## Symbols\n")
        for s in symbols:
            sys.stdout.write(f"- `{s['qualified_name']}` ({s['kind']}) — {s['file']}:{s['line']} (depth {s['depth']})\n")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--modules", required=False,
        help="comma-separated module names (mutually exclusive with --symbol)"
    )
    ap.add_argument(
        "--symbol", type=str, default=None,
        help="Phase 4.5: symbol-level context via call graph (format: file::name)"
    )
    ap.add_argument("--depth", type=int, default=None,
                    help="fixed BFS depth; if omitted, start at 1 and grow up "
                         "to --max-depth while the budget holds")
    ap.add_argument("--max-depth", type=int, default=3,
                    help="upper bound for dynamic-depth expansion (default 3)")
    ap.add_argument("--budget", type=float, default=0.05,
                    help="max fraction of project symbols to pull in (default 0.05)")
    ap.add_argument("--format", choices=["json", "markdown"], default="json")
    ap.add_argument("--test-plan", type=Path, default=None,
                    help="Optional path to test-plan.md; inlined if present (Phase 2.1)")
    args = ap.parse_args()

    # Phase 4.5: symbol mode vs module mode
    if args.symbol and args.modules:
        sys.stderr.write("context-loader: --symbol and --modules are mutually exclusive\n")
        return 1

    if args.symbol:
        return run_symbol_mode(args)

    if not args.modules:
        sys.stderr.write("context-loader: either --modules or --symbol required\n")
        return 1

    requested = [s.strip() for s in args.modules.split(",") if s.strip()]
    if not requested:
        sys.stderr.write("context-loader: --modules is empty\n")
        return 1

    modules_doc = load_json(klc_index_dir() / "modules.json")
    modules = modules_doc.get("modules", [])

    _ = resolve_modules(requested, modules)  # validates names

    # Prefer the materialized per-module index. Only fall back to loading
    # the full inventory.json when the materialized file is missing — keeps
    # cost flat in module count instead of growing with project size.
    sbm_path = klc_index_dir() / "symbols_by_module.json"
    if sbm_path.exists():
        by_module = load_symbols_by_module(modules)
        total = total_project_symbols_from_sbm(by_module)
    else:
        inventory = load_json(klc_index_dir() / "inventory.json")
        by_module = load_symbols_by_module(modules, inventory=inventory)
        total = total_project_symbols(inventory)

    # Depth: honour --depth if the caller insisted; otherwise grow from 1
    # up to --max-depth while the selected-symbol budget holds. Stop early
    # at the first depth that blows the budget and stick with the previous
    # (under-budget) result — pulling fewer modules is strictly cheaper.
    budget_abs = args.budget * total if total else 0
    warnings = []
    depth_used = 0
    included: list[str] = []
    public_api: dict = {}
    selected = 0

    if args.depth is not None:
        depths = [args.depth]
    else:
        depths = list(range(1, args.max_depth + 1))

    previous_good = None  # (depth, included, public_api, selected)
    for d in depths:
        inc_now = bfs_neighbours(requested, modules, d)
        api_now = {n: module_public_api(n, by_module, modules) for n in inc_now}
        sel_now = sum(len(v) for v in api_now.values())
        under_budget = sel_now <= budget_abs
        if args.depth is not None:
            # Caller pinned the depth — use it regardless of budget.
            included, public_api, selected, depth_used = inc_now, api_now, sel_now, d
            break
        if under_budget:
            previous_good = (d, inc_now, api_now, sel_now)
            continue
        # depth d busts the budget → stick with the previous successful depth.
        break

    if args.depth is None:
        if previous_good:
            depth_used, included, public_api, selected = previous_good
        else:
            # Even depth=1 (seed-only) exceeded budget; return it anyway
            # and warn — caller must narrow --modules.
            d = depths[0]
            included = bfs_neighbours(requested, modules, d)
            public_api = {n: module_public_api(n, by_module, modules) for n in included}
            selected = sum(len(v) for v in public_api.values())
            depth_used = d

    referenced_symbols = [
        s for symbols in public_api.values() for s in symbols
    ]
    pct = selected / total if total else 0.0
    budget_ok = pct < args.budget
    if not budget_ok:
        warnings.append(
            f"selected {selected}/{total} symbols = {pct:.2%} "
            f"(> {args.budget:.0%} budget) at depth={depth_used}; "
            "narrow --modules"
        )

    claude_mds = collect_claude_mds(included, modules)

    # Phase 2.1: ADR discovery + inline (dedicate 50% of remaining budget to ADRs)
    adr_budget_bytes = int((budget_abs - selected) * 0.5 * 100) if budget_abs > selected else 0
    adr_files, adr_inlined, adr_warnings = collect_adrs_from_claude_mds(claude_mds, adr_budget_bytes)
    warnings.extend(adr_warnings)

    # Phase 2.1: test plan (opportunistic — only if --test-plan provided and file exists)
    test_plan_file = None
    test_plan_inlined = None
    if args.test_plan and args.test_plan.exists():
        try:
            test_plan_file = str(args.test_plan.resolve())
            test_plan_inlined = args.test_plan.read_text(encoding="utf-8")
        except OSError as e:
            warnings.append(f"Failed to read test plan {args.test_plan}: {e}")

    result = {
        "requested_modules": requested,
        "included_modules":  included,
        "depth":             depth_used,
        "depth_mode":        "fixed" if args.depth is not None else "dynamic",
        "claude_md":         claude_mds,
        "public_api":        public_api,
        "referenced_symbols": referenced_symbols,
        "adr_files":         adr_files,
        "adr_inlined":       adr_inlined,
        "test_plan_file":    test_plan_file,
        "test_plan_inlined": test_plan_inlined,
        "stats": {
            "total_symbols_project": total,
            "selected_symbols":      selected,
            "percent_of_project":    round(pct, 4),
            "budget":                args.budget,
            "budget_ok":             budget_ok,
        },
        "warnings": warnings,
    }

    if args.format == "json":
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"# Context for: {', '.join(requested)}\n\n")
        sys.stdout.write(
            f"Depth: {depth_used} ({result['depth_mode']}), "
            f"included {len(included)} modules, "
            f"{selected} symbols ({pct:.2%} of project).\n\n"
        )
        for md in result["claude_md"]:
            sys.stdout.write(f"- CLAUDE.md: {md}\n")
        sys.stdout.write("\n## Public API per included module\n")
        for mod, syms in public_api.items():
            sys.stdout.write(f"\n### {mod}\n")
            for s in syms:
                sig = s.get("signature") or ""
                sys.stdout.write(
                    f"- `{s['name']}` ({s.get('kind','?')}) — {s.get('file','?')}"
                    f":{s.get('line','?')}  {sig}\n"
                )
        for w in warnings:
            sys.stderr.write(f"WARN: {w}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
