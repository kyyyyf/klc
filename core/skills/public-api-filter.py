#!/usr/bin/env python3
"""public-api-filter.py — trim each module's public_api + materialize
the per-module symbol index.

Applied after decompose builds modules.json with an unfiltered public_api.
Input: .klc/index/inventory.json + .klc/index/modules.json.
Output:
- rewrites modules.json in place, with per-module public_api reduced to
  symbols that are actually authored inside the module and ranked by
  likely relevance;
- writes .klc/index/symbols_by_module.json — a materialized per-module
  index keyed by module name, so context-loader can lazy-load a single
  module's symbols instead of walking inventory.json (tens of thousands
  of lines on large projects).

Two rules are applied to public_api:

1. **Locality.** A symbol qualifies only when its `file` starts with the
   module's `path`. This removes engine forward-declarations (AActor,
   UObject, FCollisionQueryParams, ...) that the inventory picks up but
   that are not owned by the module.

2. **Hard cap.** No more than N names (default 15; see --cap). Beyond
   the cap we prefer:
   - Symbols whose kind suggests a real definition (UCLASS, USTRUCT,
     UENUM, class/struct with body, function definition), not a
     forward-declaration.
   - Symbols whose name looks like a public entry point (matches the
     module name, ends with `Module`, `Interface`, `API`).
   - Everything else truncated; a note is recorded.

Each trimmed module records `public_api_total` (pre-filter count) and
`public_api_note` when the cap kicks in.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))  # so `import module_membership` resolves
from core.shared.paths import framework_root, klc_index_dir  # noqa: E402, F401
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)

FORWARD_KINDS = {"forward", "cpp-header-symbols-forward"}


def is_forward_decl(item: dict) -> bool:
    """Heuristic: one-line `class X;` / `struct X;` header entry."""
    sig = (item.get("signature") or "").strip()
    if not sig:
        return False
    # Ends with a semicolon and has no body — classic forward decl.
    if sig.endswith(";") and "{" not in sig:
        return True
    return False


def rank_symbol(item: dict, module_name: str) -> int:
    """Lower rank is kept first when capping. Rough priority order."""
    sig = (item.get("signature") or "").strip()
    name = item.get("name") or ""
    if is_forward_decl(item):
        return 9
    if name == module_name or name.endswith("Module"):
        return 0
    if name.endswith("Interface") or name.endswith("API"):
        return 1
    # UE macro-declared types or plain class/struct definitions.
    kind = (item.get("kind") or "").lower()
    if "uclass" in kind or "ustruct" in kind or "uinterface" in kind or "uenum" in kind:
        return 2
    if "class" in kind or "struct" in kind:
        return 3
    return 5


def trim_modules(
    inv: dict, mods: dict, cap: int
) -> tuple[int, int, dict[str, list[dict]]]:
    """Trim public_api on each module; return (trimmed_count, removed_count,
    symbols_by_module). The third element is the authored-here items per
    module (after forward-decl drop + dedupe), ready to be materialized
    as .klc/index/symbols_by_module.json."""
    # Build a quick per-lang {file: [items]} index.
    by_file: dict[str, list] = {}
    for lang, blob in inv.get("symbols", {}).items():
        for it in blob.get("items", []):
            by_file.setdefault(it["file"], []).append(it)

    # KLC-066: assignment of each file to its module(s) goes through the single
    # file_to_module() resolver (the private longest-prefix copy is deleted). A
    # normal file lands in its primary module; a shared file's symbols are shared
    # across every module in its member_of so they are not stranded. For a
    # modules.json with no `files` map this is byte-identical to the old
    # longest-prefix assignment.
    modules = mods.get("modules", [])
    symbols_by_module: dict[str, list[dict]] = {m["name"]: [] for m in modules}
    for f, items in by_file.items():
        res = _mm.file_to_module(f, mods)
        for name in (res["member_of"] or []):
            if name in symbols_by_module:
                symbols_by_module[name].extend(items)

    trimmed_modules = 0
    removed_total = 0

    for m in modules:
        path = m.get("path") or ""
        # Empty path happens for modules derived from import-graph nodes
        # that don't own a directory (e.g. UE modules resolved by name
        # only). They carry no authored symbols and must not swallow any.
        if not path:
            m.setdefault("public_api", [])
            m["public_api_total"] = 0
            m.pop("public_api_note", None)
            continue

        local_items = symbols_by_module[m["name"]]
        # Drop forward-declarations outright.
        local_items = [it for it in local_items if not is_forward_decl(it)]

        # Dedupe by name.
        seen = set()
        uniq = []
        for it in local_items:
            if it["name"] in seen:
                continue
            seen.add(it["name"])
            uniq.append(it)

        total = len(uniq)
        uniq.sort(key=lambda it: (rank_symbol(it, m["name"]), it["name"]))
        symbols_by_module[m["name"]] = uniq        # materialized index
        kept_items = uniq[:cap]
        kept_names = [it["name"] for it in kept_items]

        prior = m.get("public_api") or []
        if kept_names != prior:
            trimmed_modules += 1
            removed_total += len(prior) - len(kept_names)

        m["public_api"] = kept_names
        m["public_api_total"] = total
        if total > cap:
            m["public_api_note"] = (
                f"public_api truncated to {cap} of {total} authored symbols; "
                f"see .klc/index/symbols_by_module.json for the full list."
            )
        elif "public_api_note" in m:
            del m["public_api_note"]

    return trimmed_modules, removed_total, symbols_by_module


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cap", type=int, default=15,
                    help="maximum symbols per module (default 15). Module "
                         "CLAUDE.md lands in every task/review context; keep "
                         "the list short on purpose — the reviewer will pull "
                         "more via LSP when it needs detail.")
    ap.add_argument("--in-inventory", type=Path,
                    default=klc_index_dir() / "inventory.json")
    ap.add_argument("--in-modules", type=Path,
                    default=klc_index_dir() / "modules.json")
    ap.add_argument("--out-modules", type=Path, default=None,
                    help="where to write the trimmed modules.json "
                         "(defaults to --in-modules)")
    ap.add_argument("--out-symbols", type=Path, default=None,
                    help="where to write the per-module symbol index "
                         "(defaults to .klc/index/symbols_by_module.json)")
    args = ap.parse_args()

    if not args.in_inventory.exists() or not args.in_modules.exists():
        sys.stderr.write("public-api-filter: inventory.json or modules.json missing\n")
        return 1

    inv = json.loads(args.in_inventory.read_text(encoding="utf-8"))
    mods = json.loads(args.in_modules.read_text(encoding="utf-8"))

    trimmed, removed, symbols_by_module = trim_modules(inv, mods, args.cap)

    out = args.out_modules or args.in_modules
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mods, indent=2, ensure_ascii=False), encoding="utf-8")

    # Materialize the per-module symbol index so context-loader can read a
    # single module's slice without walking inventory.json. The index keeps
    # the same item shape (name/kind/file/line/signature) as inventory.
    sbm_out = args.out_symbols or (klc_index_dir() / "symbols_by_module.json")
    sbm_out.parent.mkdir(parents=True, exist_ok=True)
    sbm_payload = {
        "generated_at": inv.get("generated_at"),
        "git_sha":      inv.get("git_sha"),
        "source":       "public-api-filter",
        "modules":      symbols_by_module,
    }
    sbm_out.write_text(
        json.dumps(sbm_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    total_items = sum(len(v) for v in symbols_by_module.values())
    print(f"public-api-filter: trimmed {trimmed} module(s), "
          f"removed {removed} non-local / forward-decl symbol(s) total; "
          f"wrote {total_items} item(s) to {sbm_out}")

    # Refresh the per-module hash snapshot so periodic can diff against
    # a consistent baseline on the next run.
    import per_module_hash  # local skill, sys.path was set at import time
    import datetime as _dt_local
    hashes = per_module_hash.compute_hashes(mods.get("modules", []))
    hash_out = klc_index_dir() / "per-module-hash.json"
    hash_out.parent.mkdir(parents=True, exist_ok=True)
    hash_out.write_text(json.dumps({
        "generated_at": _dt_local.datetime.now(_dt_local.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha":      mods.get("git_sha"),
        "modules":      hashes,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"public-api-filter: refreshed per-module hash at {hash_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
