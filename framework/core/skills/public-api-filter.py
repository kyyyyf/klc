#!/usr/bin/env python3
"""public-api-filter.py — trim each module's public_api to signal only.

Applied after decompose builds modules.json with an unfiltered public_api.
Input: framework/index/inventory.json + framework/index/modules.json.
Output: rewrites modules.json in place, with per-module public_api reduced
to symbols that are actually authored inside the module and ranked by
likely relevance.

Two rules are applied:

1. **Locality.** A symbol qualifies only when its `file` starts with the
   module's `path`. This removes engine forward-declarations (AActor,
   UObject, FCollisionQueryParams, ...) that the inventory picks up but
   that are not owned by the module.

2. **Hard cap.** No more than N names (default 40). Beyond the cap we
   prefer:
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
import sys
from pathlib import Path

FORWARD_KINDS = {"forward", "cpp-header-symbols-forward"}


def framework_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


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


def trim_modules(inv: dict, mods: dict, cap: int) -> tuple[int, int]:
    # Build a quick per-lang {file: [items]} index.
    by_file: dict[str, list] = {}
    for lang, blob in inv.get("symbols", {}).items():
        for it in blob.get("items", []):
            by_file.setdefault(it["file"], []).append(it)

    trimmed_modules = 0
    removed_total = 0

    for m in mods.get("modules", []):
        path = m["path"]
        # All symbols authored inside this module.
        local_items: list[dict] = []
        for f, items in by_file.items():
            if f.startswith(path):
                local_items.extend(items)

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
                f"see framework/index/inventory.json for the full list."
            )
        elif "public_api_note" in m:
            del m["public_api_note"]

    return trimmed_modules, removed_total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cap", type=int, default=15,
                    help="maximum symbols per module (default 15). Module "
                         "CLAUDE.md lands in every task/review context; keep "
                         "the list short on purpose — the reviewer will pull "
                         "more via Serena when it needs detail.")
    ap.add_argument("--in-inventory", type=Path,
                    default=framework_root() / "index" / "inventory.json")
    ap.add_argument("--in-modules", type=Path,
                    default=framework_root() / "index" / "modules.json")
    ap.add_argument("--out-modules", type=Path, default=None,
                    help="where to write the trimmed modules.json "
                         "(defaults to --in-modules)")
    args = ap.parse_args()

    if not args.in_inventory.exists() or not args.in_modules.exists():
        sys.stderr.write("public-api-filter: inventory.json or modules.json missing\n")
        return 1

    inv = json.loads(args.in_inventory.read_text(encoding="utf-8"))
    mods = json.loads(args.in_modules.read_text(encoding="utf-8"))

    trimmed, removed = trim_modules(inv, mods, args.cap)

    out = args.out_modules or args.in_modules
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mods, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"public-api-filter: trimmed {trimmed} module(s), "
          f"removed {removed} non-local / forward-decl symbol(s) total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
