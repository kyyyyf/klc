#!/usr/bin/env python3
"""file_roles.py — deterministic per-file role classification (KLC-071 step-5).

Answers "what ROLE does each file play?" so retrieval ranks files with the right
role for planning (domain logic, public surface, entrypoint) and never starts a plan
from a fixture, a generated file, or a shared helper. Derived deterministically from
``inventory.json`` (KLC-070, FROZEN schema) + ``modules.json`` + ``structural.json``.
No LLM (planning_indexer.md §3): the classification is a fixed rule table.

``inventory.json`` is the REQUIRED input — the file universe and every file's symbols
come from it, so its absence is a hard exit-2 (fail-closed). ``modules.json`` and
``structural.json`` are optional: their absence degrades into ``errors[]`` (a file
still gets roles from inventory alone), never a hard fail (planning_indexer.md
§"CLI / API контракты").

Output schema (planning_indexer.md §3):

    {
      "files": {
        "<path>": {
          "module_name":        str | null,   # via file_to_module() (KLC-066)
          "roles":              [str],        # every matching role
          "is_entrypoint":      bool,
          "is_test":            bool,
          "is_generated":       bool,
          "is_config":          bool,
          "eligible_as_primary": bool,
          "keywords":           [str],
          "symbols":            [str],
          "confidence":         "high" | "medium" | "low"
        }
      },
      "errors": [str], "notes": [str]
    }

Eligibility rule (planning_indexer.md §3, "generated и test/shared побеждают и
запрещают eligibility"): a file is eligible_as_primary ONLY when it has a positive
role (entrypoint / public_surface / domain_logic / adapter / persistence /
integration / ui / types) AND none of the disqualifiers (generated / test / config /
shared) fire. The disqualifiers WIN over any positive role a file might also carry —
a shared helper with public symbols is still not eligible.

``confidence``: ``high`` when the deciding signal is inventory/graph/membership
(public symbols, shared membership, entrypoint); ``medium`` when only a path heuristic
(generated path, config extension, adapter dir); ``low`` when only a bare filename
convention (a ``test_*``/``*_test`` name outside any test directory). It is computed
from the highest-priority DECIDING rule, not the last rule that appended a role.

Every file→module attribution routes through ``module_membership.file_to_module``
(KLC-066) — there is NO private longest-prefix matcher here (C-002).
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
from core.shared.paths import klc_index_dir  # noqa: E402
import module_membership as _mm  # noqa: E402
import test_map as _tm  # noqa: E402  (reuse the one is_test_file convention)

# Generated / vendored path markers (deterministic; the profile excludes already keep
# most of these out of inventory, but a path check catches the rest without a subprocess).
_GENERATED_RE = re.compile(
    r"(^|/)(vendor|third[_-]?party|node_modules|generated|__generated__|dist|build|"
    r"migrations?)(/|$)"
    r"|\.(pb|generated)\.|_pb2\.|\.min\.",
    re.IGNORECASE,
)
_CONFIG_EXT = {".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".conf"}
_PUBLIC_SURFACE_NAMES = {"__init__.py", "index.ts", "index.js", "mod.rs", "lib.rs"}
_TYPE_KINDS = {"type", "interface", "enum"}
# Path heuristics → (role) (planning_indexer.md §3 adapter/persistence/integration/ui).
_PATH_ROLE_RES = (
    (re.compile(r"(^|/)adapters?(/|$)", re.IGNORECASE), "adapter"),
    (re.compile(r"(^|/)(persistence|db|store|dao|repositor(y|ies))(/|$)", re.IGNORECASE),
     "persistence"),
    (re.compile(r"(^|/)integration(s)?(/|$)", re.IGNORECASE), "integration"),
    (re.compile(r"(^|/)(ui|views?|components?|widgets?)(/|$)", re.IGNORECASE), "ui"),
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOP_KEYWORDS = {"the", "and", "for", "def", "class", "self", "test", "py", "ts",
                  "get", "set", "init", "main", "value", "data"}


def _split_tokens(text: str) -> list[str]:
    """Lowercase alnum tokens, splitting snake_case and camelCase deterministically."""
    out: list[str] = []
    for word in _TOKEN_RE.findall(text):
        # split camelCase / PascalCase into words
        for part in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", word):
            p = part.lower()
            if len(p) >= 3 and p not in _STOP_KEYWORDS:
                out.append(p)
    return out


def _keywords(path: str, symbol_names: list[str]) -> list[str]:
    """Deterministic keyword set from the file stem + symbol names (no LLM)."""
    toks = _split_tokens(Path(path).stem)
    for s in symbol_names:
        toks += _split_tokens(s)
    seen: dict[str, None] = {}
    for t in toks:
        seen.setdefault(t, None)
    return sorted(seen)[:8]


def _symbols_by_file(inventory: dict) -> dict[str, list[dict]]:
    by_file: dict[str, list[dict]] = {}
    for s in inventory.get("symbols") or []:
        f = s.get("file")
        if f:
            by_file.setdefault(f, []).append(s)
    return by_file


def _entrypoints(modules: dict, structural: dict) -> set[str]:
    eps: set[str] = set(structural.get("entry_points") or [])
    for m in modules.get("modules") or []:
        for p in m.get("primary_entrypoints") or []:
            eps.add(p)
    return eps


def _public_surfaces(modules: dict) -> set[str]:
    surf: set[str] = set()
    for m in modules.get("modules") or []:
        for p in m.get("public_surfaces") or []:
            surf.add(p)
    return surf


def _file_universe(inventory: dict, modules: dict, structural: dict) -> set[str]:
    """Every file we can name deterministically from the three declared inputs."""
    files: set[str] = set(_symbols_by_file(inventory).keys())
    files |= _entrypoints(modules, structural)
    files |= _public_surfaces(modules)
    for m in modules.get("modules") or []:
        for key in ("test_files", "files"):
            for p in m.get(key) or []:
                files.add(p)
    for p in (modules.get("files") or {}):
        files.add(p)
    return files


def _confidence(path: str, roles: list[str], is_generated: bool, is_test: bool,
                is_config: bool, is_shared: bool, public_surface_backed: bool) -> str:
    """Confidence in the classification = strength of the DECIDING signal.

    Priority-based and independent of role-append order (the deciding rule is the one
    that fixes ``eligible_as_primary``): a disqualifier (generated/test/config/shared)
    wins, otherwise the strongest positive role. ``high`` = inventory/graph/membership
    evidence; ``medium`` = a path heuristic; ``low`` = only a filename convention.

    FIX-3: a ``public_surface`` role earns ``high`` ONLY when it is backed by public
    symbols (inventory) OR ``modules.public_surfaces`` membership. A bare name-only
    barrel (``__init__.py``/``index.ts``/``mod.rs``) with no symbols is a filename
    convention → ``medium``, not ``high``.
    """
    if is_generated:
        return "medium"            # generated/vendor is a path heuristic
    if is_test:
        # a test under a test dir is a path signal; a bare test-name only, filename.
        return "medium" if _tm._TEST_DIR_RE.search(path) else "low"
    if is_config:
        return "medium"            # config-by-extension is a path heuristic
    if is_shared:
        return "high"              # membership (modules.json) is authoritative
    role_set = set(roles)
    if {"entrypoint", "domain_logic", "types"} & role_set:
        return "high"              # from inventory / structural / membership
    if "public_surface" in role_set and public_surface_backed:
        return "high"              # backed by public symbols / modules membership
    if role_set & {"public_surface", "adapter", "persistence", "integration", "ui"}:
        return "medium"            # bare barrel name, or a path heuristic only
    return "low"


def _classify(path: str, syms: list[dict], modules: dict,
              entrypoints: set[str], public_surfaces: set[str]) -> dict:
    """Return the role record for one file (see module docstring)."""
    membership = _mm.file_to_module(path, modules)
    is_generated = bool(_GENERATED_RE.search(path))
    is_test = _tm.is_test_file(path)
    is_config = Path(path).suffix.lower() in _CONFIG_EXT
    is_entry = path in entrypoints
    is_shared = membership["is_shared"]

    has_symbols = bool(syms)
    public_syms = [s for s in syms if s.get("visibility") == "public"]
    all_types = has_symbols and all(
        (s.get("kind") or "") in _TYPE_KINDS for s in syms)

    roles: list[str] = []

    if is_generated:
        roles.append("generated")
    if is_test:
        roles.append("test")
    if is_config:
        roles.append("config")
    if is_entry:
        roles.append("entrypoint")
    # public_surface is EVIDENCE-BACKED when it comes from public symbols (inventory)
    # or modules.public_surfaces membership; a bare barrel NAME alone is not (FIX-3).
    in_modules_surfaces = path in public_surfaces
    is_barrel_name = Path(path).name in _PUBLIC_SURFACE_NAMES
    public_surface_backed = in_modules_surfaces or bool(public_syms)
    if is_barrel_name or in_modules_surfaces or public_syms:
        roles.append("public_surface")
    if all_types:
        roles.append("types")
    elif has_symbols and "public_surface" not in roles:
        roles.append("domain_logic")
    elif has_symbols and "domain_logic" not in roles and "public_surface" in roles:
        # a public surface with private-only helpers still carries domain logic
        roles.append("domain_logic")
    for rx, role in _PATH_ROLE_RES:
        if rx.search(path) and role not in roles:
            roles.append(role)
    if is_shared:
        roles.append("shared")

    signal = _confidence(path, roles, is_generated, is_test, is_config, is_shared,
                         public_surface_backed)

    # Eligibility: a positive role AND no disqualifier (disqualifiers WIN).
    positive = {"entrypoint", "public_surface", "domain_logic", "adapter",
                "persistence", "integration", "ui", "types"}
    disqualified = is_generated or is_test or is_config or is_shared
    eligible = (not disqualified) and bool(positive & set(roles))

    return {
        "module_name": membership["primary_module"],
        "roles": roles,
        "is_entrypoint": is_entry,
        "is_test": is_test,
        "is_generated": is_generated,
        "is_config": is_config,
        "eligible_as_primary": eligible,
        "keywords": _keywords(path, [s.get("name", "") for s in syms]),
        "symbols": sorted({s.get("name", "") for s in syms if s.get("name")}),
        "confidence": signal,
    }


def build_file_roles(inventory: dict, modules: dict, structural: dict) -> dict:
    """Deterministic per-file role map. Pure; no timestamp (AC-8)."""
    errors: list[str] = []
    notes: list[str] = []
    if not (modules.get("modules") or modules.get("files")):
        errors.append("modules.json absent/empty — files resolve to orphan "
                      "(module_name=null); shared/eligible membership flags unavailable")
    if not structural.get("entry_points"):
        notes.append("structural entry_points absent — entrypoint role from "
                     "modules.primary_entrypoints only")

    by_file = _symbols_by_file(inventory)
    entrypoints = _entrypoints(modules, structural)
    public_surfaces = _public_surfaces(modules)

    files_out: dict[str, dict] = {}
    for path in sorted(_file_universe(inventory, modules, structural)):
        files_out[path] = _classify(
            path, by_file.get(path, []), modules, entrypoints, public_surfaces)

    return {"files": files_out, "errors": errors, "notes": notes}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    idx = klc_index_dir()
    ap = argparse.ArgumentParser(description="Deterministic per-file role classification")
    ap.add_argument("--in-inventory", type=Path, default=idx / "inventory.json")
    ap.add_argument("--in-modules", type=Path, default=idx / "modules.json")
    ap.add_argument("--in-structural", type=Path, default=idx / "structural.json")
    ap.add_argument("--out", type=Path, default=idx / "file_roles.json")
    args = ap.parse_args(argv)

    if not args.in_inventory.exists():
        sys.stderr.write(
            f"file-roles: required input inventory.json not found at "
            f"{args.in_inventory}\n")
        return 2
    inventory = _load(args.in_inventory)
    if not isinstance(inventory, dict) or "symbols" not in inventory:
        sys.stderr.write(
            f"file-roles: inventory.json malformed at {args.in_inventory}\n")
        return 2

    modules = _load(args.in_modules)
    if not isinstance(modules, dict):
        modules = {"modules": modules}
    structural = _load(args.in_structural)

    result = build_file_roles(inventory, modules, structural)
    if not args.in_modules.exists():
        result["errors"].append(f"modules.json not found at {args.in_modules}")
    if not args.in_structural.exists():
        result["errors"].append(f"structural.json not found at {args.in_structural}")

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for e in result["errors"]:
        sys.stderr.write(f"file-roles: warning: {e}\n")
    print(f"file-roles: classified {len(result['files'])} file(s) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
