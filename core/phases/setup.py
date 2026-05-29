#!/usr/bin/env python3
"""`klc setup` — detect project languages and show required tool install commands.

Runs after `klc init` to:
1. Detect languages via detect_languages.py
2. Compute required/optional tools per language
3. Print manual install commands
4. Write .klc/index/project-deps.json

Does NOT auto-install tools (manual only, per user decision).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))

try:
    from _paths import klc_index_dir
    from detect_languages import detect
except ImportError:
    sys.stderr.write("Error: could not import klc framework modules\n")
    sys.exit(2)


# Tool registry: language → required/optional tools
TOOLS_BY_LANG = {
    "python": {
        "required": ["uv", "pylsp"],
        "optional": ["mutmut", "pipdeptree"],
        "install_hints": {
            "uv": "curl -LsSf https://astral.sh/uv/install.sh | sh  OR  winget install astral-sh.uv",
            "pylsp": "pipx install 'python-lsp-server[all]'  OR  uv tool install python-lsp-server",
            "mutmut": "pipx install mutmut  OR  pip install mutmut",
            "pipdeptree": "pipx install pipdeptree  OR  uv tool install pipdeptree",
        }
    },
    "cpp": {
        "required": ["clangd"],
        "optional": ["scip-clang", "mull-runner", "cmake"],
        "install_hints": {
            "clangd": "apt install clangd  |  brew install llvm  |  winget install LLVM.LLVM",
            "scip-clang": "(see KLC-004 for scip-clang installation)",
            "mull-runner": "https://github.com/mull-project/mull (requires LLVM)",
            "cmake": "apt install cmake  |  brew install cmake  |  winget install Kitware.CMake",
        }
    },
    "typescript": {
        "required": ["typescript-language-server", "tsc"],
        "optional": ["stryker", "madge"],
        "install_hints": {
            "typescript-language-server": "npm install -g typescript-language-server typescript",
            "tsc": "(installed with typescript)",
            "stryker": "npm install -g @stryker-mutator/core",
            "madge": "npm install -g madge",
        }
    },
    "javascript": {
        "required": ["node", "npm"],
        "optional": ["madge", "stryker"],
        "install_hints": {
            "node": "install Node.js LTS from https://nodejs.org",
            "npm": "(ships with Node.js)",
            "madge": "npm install -g madge",
            "stryker": "npm install -g @stryker-mutator/core",
        }
    },
    "rust": {
        "required": ["rust-analyzer", "cargo"],
        "optional": ["cargo-mutants"],
        "install_hints": {
            "rust-analyzer": "rustup component add rust-analyzer",
            "cargo": "install Rust toolchain (rustup) from https://rustup.rs",
            "cargo-mutants": "cargo install cargo-mutants",
        }
    },
}


def run(argv: list[str]) -> int:
    """klc setup command entry point."""
    ap = argparse.ArgumentParser(prog="klc setup")
    ap.add_argument("--json", action="store_true",
                    help="Output project-deps.json to stdout (for CI)")
    args = ap.parse_args(argv)

    # Detect languages
    languages = detect()

    if not languages:
        print("[setup] No languages detected, skipping tool setup.")
        print("[setup] Hint: run `klc init` first to generate inventory.json")
        return 0

    print(f"[setup] Detected languages: {', '.join(sorted(languages))}")

    # Compute required/optional tools
    required: dict[str, list[str]] = {}
    optional: dict[str, list[str]] = {}
    all_tools: set[str] = set()

    for lang in languages:
        if lang in TOOLS_BY_LANG:
            required[lang] = TOOLS_BY_LANG[lang]["required"]
            optional[lang] = TOOLS_BY_LANG[lang]["optional"]
            all_tools.update(required[lang])
            all_tools.update(optional[lang])

    # Detect which tools are already present
    detected: dict[str, str | None] = {}
    for tool in all_tools:
        path = shutil.which(tool)
        detected[tool] = str(path) if path else None

    # Print install commands for missing required tools
    print("\n[setup] Required tools:")
    has_missing = False
    for lang in sorted(languages):
        if lang not in TOOLS_BY_LANG:
            continue
        print(f"  {lang}:")
        for tool in TOOLS_BY_LANG[lang]["required"]:
            if detected.get(tool):
                print(f"    - {tool:<30} (found: {detected[tool]})")
            else:
                has_missing = True
                hint = TOOLS_BY_LANG[lang]["install_hints"].get(tool, "")
                print(f"    - {tool:<30} (missing) — install: {hint}")

    # Print optional tools (informational)
    print("\n[setup] Optional tools (not required for basic functionality):")
    for lang in sorted(languages):
        if lang not in TOOLS_BY_LANG:
            continue
        print(f"  {lang}:")
        for tool in TOOLS_BY_LANG[lang]["optional"]:
            if detected.get(tool):
                print(f"    - {tool:<30} (found: {detected[tool]})")
            else:
                hint = TOOLS_BY_LANG[lang]["install_hints"].get(tool, "")
                print(f"    - {tool:<30} (missing) — install: {hint}")

    # Write project-deps.json
    project_deps = {
        "languages": sorted(languages),
        "required": required,
        "optional": optional,
        "detected": detected,
    }

    deps_file = klc_index_dir() / "project-deps.json"
    deps_file.parent.mkdir(parents=True, exist_ok=True)
    deps_file.write_text(json.dumps(project_deps, indent=2) + "\n", encoding="utf-8")

    print(f"\n[setup] Wrote {deps_file}")

    if args.json:
        print(json.dumps(project_deps, indent=2))

    if has_missing:
        print("\nNext: install missing tools, then run `klc doctor` to verify.")
    else:
        print("\nAll required tools present! Run `klc doctor` to verify installation health.")

    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
