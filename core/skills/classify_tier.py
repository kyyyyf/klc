#!/usr/bin/env python3
"""classify_tier.py — assign risk tier to files in a diff.

Phase 3a: reads config/tiers.yml and modules.json, classifies each file in
the diff as critical/core/peripheral. Used by review.py to apply per-tier
blocking thresholds.

Usage:
    classify_tier.py --diff <path> [--format json|table]

Output (JSON):
    {
      "files": [
        {"path": "src/auth/jwt.py", "tier": "critical", "reason": "pattern match: **/*auth*/**"},
        {"path": "src/api/users.py", "tier": "core", "reason": "public_api symbol exported"},
        {"path": "tests/test_api.py", "tier": "peripheral", "reason": "pattern match: **/tests/**"}
      ],
      "summary": {"critical": 1, "core": 1, "peripheral": 1}
    }

Classification order (first match wins):
1. Module metadata: modules.json[].metadata.tier override
2. Explicit path patterns in tiers.yml
3. Public API membership: file exports symbol in modules.json[].public_api
4. Fallback: tiers.yml::fallback_tier (default: peripheral)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from fnmatch import fnmatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import framework_root, klc_index_dir  # noqa: E402
from _yaml import parse as load_yaml  # noqa: E402


def load_tiers_config() -> dict:
    """Load config/tiers.yml."""
    path = framework_root() / "config" / "tiers.yml"
    if not path.exists():
        sys.stderr.write(f"classify_tier: {path} not found\n")
        sys.exit(1)
    return load_yaml(path)


def load_modules() -> list[dict]:
    """Load .klc/index/modules.json."""
    path = klc_index_dir() / "modules.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("modules", [])
    except (OSError, json.JSONDecodeError):
        return []


def load_symbols_by_module() -> dict[str, list[dict]]:
    """Load .klc/index/symbols_by_module.json."""
    path = klc_index_dir() / "symbols_by_module.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("modules", {})
    except (OSError, json.JSONDecodeError):
        return {}


def parse_diff(diff_path: Path) -> list[str]:
    """Extract list of modified file paths from unified diff."""
    if not diff_path.exists():
        return []
    files: set[str] = set()
    try:
        for line in diff_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("+++") or line.startswith("---"):
                # unified diff: +++ b/path/to/file or --- a/path/to/file
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    path = parts[1]
                    if path.startswith("b/"):
                        path = path[2:]
                    elif path.startswith("a/"):
                        path = path[2:]
                    if path and path != "/dev/null":
                        files.add(path)
    except OSError:
        pass
    return sorted(files)


def module_tier_override(file_path: str, modules: list[dict]) -> str | None:
    """Check if file belongs to a module with metadata.tier override."""
    # Longest prefix match
    sorted_modules = sorted(modules, key=lambda m: -len(m.get("path", "")))
    for m in sorted_modules:
        mod_path = m.get("path", "")
        if mod_path and file_path.startswith(mod_path + "/"):
            tier = m.get("metadata", {}).get("tier")
            if tier in ("critical", "core", "peripheral"):
                return tier
    return None


def path_pattern_match(file_path: str, tiers_config: dict) -> tuple[str, str] | None:
    """Match file against tier patterns. Returns (tier, reason) or None."""
    for tier_name in ("critical", "core", "peripheral"):
        tier = tiers_config.get("tiers", {}).get(tier_name, {})
        patterns = tier.get("patterns", [])
        for pat in patterns:
            if fnmatch(file_path, pat):
                return tier_name, f"pattern match: {pat}"
    return None


def public_api_membership(file_path: str, modules: list[dict],
                          symbols_by_module: dict[str, list[dict]]) -> bool:
    """Check if file exports any symbol listed in module's public_api."""
    # Find module for this file
    sorted_modules = sorted(modules, key=lambda m: -len(m.get("path", "")))
    for m in sorted_modules:
        mod_path = m.get("path", "")
        if mod_path and file_path.startswith(mod_path + "/"):
            mod_name = m.get("name")
            public_api_names = set(m.get("public_api", []))
            if not public_api_names:
                return False
            # Check if any symbol from this file is in public_api
            symbols = symbols_by_module.get(mod_name, [])
            for sym in symbols:
                if sym.get("file") == file_path and sym.get("name") in public_api_names:
                    return True
    return False


def classify_file(file_path: str, tiers_config: dict, modules: list[dict],
                  symbols_by_module: dict[str, list[dict]]) -> tuple[str, str]:
    """Classify a single file. Returns (tier, reason)."""
    # 1. Module metadata override
    override = module_tier_override(file_path, modules)
    if override:
        return override, f"module metadata tier={override}"

    # 2. Path pattern match
    match = path_pattern_match(file_path, tiers_config)
    if match:
        return match

    # 3. Public API membership
    if public_api_membership(file_path, modules, symbols_by_module):
        return "core", "exports public_api symbol"

    # 4. Fallback
    fallback = tiers_config.get("fallback_tier", "peripheral")
    return fallback, "fallback"


def classify_diff(diff_path: Path, tiers_config: dict, modules: list[dict],
                  symbols_by_module: dict[str, list[dict]]) -> dict:
    """Classify all files in diff. Returns result dict."""
    files_list = parse_diff(diff_path)
    results = []
    summary = {"critical": 0, "core": 0, "peripheral": 0}

    for f in files_list:
        tier, reason = classify_file(f, tiers_config, modules, symbols_by_module)
        results.append({"path": f, "tier": tier, "reason": reason})
        summary[tier] = summary.get(tier, 0) + 1

    return {"files": results, "summary": summary}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", required=True, help="Path to unified diff")
    ap.add_argument("--format", choices=["json", "table"], default="json")
    args = ap.parse_args()

    diff_path = Path(args.diff)
    if not diff_path.exists():
        sys.stderr.write(f"classify_tier: diff not found: {diff_path}\n")
        return 1

    tiers_config = load_tiers_config()
    modules = load_modules()
    symbols_by_module = load_symbols_by_module()

    result = classify_diff(diff_path, tiers_config, modules, symbols_by_module)

    if args.format == "json":
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        # Table format
        print(f"{'File':<50} {'Tier':<12} {'Reason'}")
        print("-" * 80)
        for f in result["files"]:
            print(f"{f['path']:<50} {f['tier']:<12} {f['reason']}")
        print("\nSummary:")
        for tier, count in result["summary"].items():
            print(f"  {tier}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
