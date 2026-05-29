#!/usr/bin/env python3
"""Project dependency checks — runtime tools for klc against target repos.

Checks project-runtime tools (LSP servers, language runtimes, analysis tools):
- Core: git, jq, node, npm
- Analysis: ast-grep, uv
- LSP servers: pylsp, typescript-language-server, clangd, rust-analyzer
- Dep-graph: madge, pipdeptree, cargo, cmake
- Python libs: jinja2

Does NOT check bootstrap-only (already checked) or dev-only tools.

Exit 0 if all present, exit 1 with install instructions otherwise.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Import shared utilities
from . import log, warn, err, _check, _check_python_lib, _has


def _vswhere_path() -> Path | None:
    """Locate Microsoft's vswhere.exe. It ships with any modern VS /
    Build Tools installer at a stable path under ProgramFiles(x86)."""
    pf_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cand = Path(pf_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    return cand if cand.exists() else None


def detect_vs_clangd() -> Path | None:
    """On Windows, ask vswhere for every VS installation and look for
    clangd.exe at `{install}\\VC\\Tools\\Llvm\\bin\\clangd.exe`.
    Returns the first existing path, or None."""
    if platform.system() != "Windows":
        return None
    vswhere = _vswhere_path()
    if vswhere is None:
        return None
    try:
        r = subprocess.run(
            [str(vswhere), "-products", "*", "-requires",
             "Microsoft.VisualStudio.Component.VC.Llvm.Clang",
             "-property", "installationPath", "-utf8"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    for install in r.stdout.strip().splitlines():
        install = install.strip()
        if not install:
            continue
        clangd = Path(install) / "VC" / "Tools" / "Llvm" / "bin" / "clangd.exe"
        if clangd.exists():
            return clangd
    # Fallback: even if the LLVM component wasn't formally installed,
    # newer VS images ship clangd.exe anyway. Enumerate all
    # installations and probe the conventional path.
    try:
        r = subprocess.run(
            [str(vswhere), "-products", "*", "-property", "installationPath",
             "-utf8"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for install in r.stdout.strip().splitlines():
        install = install.strip()
        if not install:
            continue
        clangd = Path(install) / "VC" / "Tools" / "Llvm" / "bin" / "clangd.exe"
        if clangd.exists():
            return clangd
    return None


def check_project(strict: bool = False, framework_root: Path | None = None) -> int:
    """Check project-runtime dependencies.

    Args:
        strict: If True, treat optional tools as required
        framework_root: Path to klc framework root (for tools.py imports)

    Returns:
        0 if all dependencies present
        1 if any dependency missing
    """
    log("Checking project-runtime dependencies")

    missing: list[str] = []
    suggestions: list[str] = []

    # Import tools.py for clangd resolution (needs framework_root in sys.path)
    if framework_root:
        skills_dir = framework_root / "core" / "skills"
        if str(skills_dir) not in sys.path:
            sys.path.insert(0, str(skills_dir))
        try:
            from tools import record_tool, resolve_tool  # noqa: F401
        except ImportError:
            resolve_tool = lambda x: None  # noqa: E731
            record_tool = lambda x, y: None  # noqa: E731
    else:
        resolve_tool = lambda x: None  # noqa: E731
        record_tool = lambda x, y: None  # noqa: E731

    # --- core ----------------------------------------------------------------
    log("Checking core tools")
    _check(missing, suggestions, name="git",
           hint="install git from https://git-scm.com")
    _check(missing, suggestions, name="jq",
           hint="optional on Windows (framework ports no longer require it). "
                "winget install jqlang.jq | brew install jq | apt install jq")
    _check(missing, suggestions, name="node",
           hint="install Node.js LTS from https://nodejs.org")
    _check(missing, suggestions, name="npm",
           hint="npm ships with Node.js")

    # --- ast-grep ------------------------------------------------------------
    log("Checking ast-grep")
    ag_path = _has("ast-grep") or _has("sg")
    if ag_path:
        log(f"  ok  ast-grep ({ag_path})")
        # Validate profile rules if framework_root provided
        if framework_root:
            rule_failures = 0
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                for suffix in ("cpp", "py", "ts", "rs"):
                    (tmp / f"empty.{suffix}").write_text("", encoding="utf-8")
                resolve_script = framework_root / "core" / "skills" / "profile-resolve.py"
                if resolve_script.exists():
                    try:
                        r = subprocess.run(
                            [sys.executable, str(resolve_script), "--field", "rules"],
                            capture_output=True, text=True, timeout=10,
                        )
                        rule_dirs = r.stdout.strip().split()
                    except (OSError, subprocess.TimeoutExpired):
                        rule_dirs = []
                    # Collect all rule files first
                    rule_files = []
                    for rd in rule_dirs:
                        rd_path = framework_root / rd
                        if not rd_path.is_dir():
                            continue
                        rule_files.extend(rd_path.glob("*.yaml"))

                    # Batch validate: invoke ast-grep once with multiple --rule flags
                    if rule_files:
                        cmd = [str(ag_path), "scan"]
                        for rf in rule_files:
                            cmd.extend(["--rule", str(rf)])
                        cmd.append(str(tmp))

                        try:
                            check = subprocess.run(
                                cmd,
                                capture_output=True, text=True, timeout=30,
                            )
                            # ast-grep exits non-zero if any rule fails
                            if check.returncode != 0:
                                # Parse stderr to identify which rules failed
                                for rf in rule_files:
                                    if str(rf) in check.stderr:
                                        rule_failures += 1
                                        warn(f"  broken rule: {rf}")
                        except (OSError, subprocess.TimeoutExpired):
                            # If batch fails, report all as failures
                            rule_failures = len(rule_files)
                            for rf in rule_files:
                                warn(f"  broken rule: {rf}")
            if rule_failures:
                missing.append("ast-grep-rules")
                suggestions.append(
                    f"ast-grep: {rule_failures} rule file(s) fail to parse. "
                    "Quote inline patterns containing ':' or rewrite them."
                )
    else:
        missing.append("ast-grep")
        suggestions.append(
            "ast-grep: npm i -g @ast-grep/cli  OR  cargo install ast-grep "
            "--locked  OR  brew install ast-grep  OR  winget install ast-grep"
        )
        warn("  missing  ast-grep")

    # --- uv ------------------------------------------------------------------
    log("Checking uv")
    _check(missing, suggestions, name="uv",
           hint="install uv: https://docs.astral.sh/uv/  "
                "(curl -LsSf https://astral.sh/uv/install.sh | sh  OR  "
                "winget install astral-sh.uv)")

    # --- LSP servers (optional per language) ---------------------------------
    log("Checking LSP servers (optional per language)")
    _check(missing, suggestions, name="pylsp",
           hint="pipx install 'python-lsp-server[all]'  OR  "
                "uv tool install python-lsp-server")
    _check(missing, suggestions, name="typescript-language-server",
           hint="npm i -g typescript-language-server typescript")

    # clangd — special handling on Windows (auto-detect via vswhere).
    clangd_path = resolve_tool("clangd")
    if clangd_path is None and platform.system() == "Windows":
        vs_clangd = detect_vs_clangd()
        if vs_clangd:
            record_tool("clangd", vs_clangd)
            log(f"  ok  clangd (Visual Studio: {vs_clangd})")
            clangd_path = vs_clangd
    if clangd_path:
        if clangd_path and not shutil.which("clangd"):
            log(f"  ok  clangd ({clangd_path})  (via .klc/config/tools.json)")
        else:
            log(f"  ok  clangd ({clangd_path})")
    else:
        missing.append("clangd")
        if platform.system() == "Windows":
            suggestions.append(
                "clangd: winget install LLVM.LLVM  OR  "
                "winget install Microsoft.VisualStudio.2022.BuildTools "
                "(Build Tools ships a bundled LLVM; rerun install_deps.py "
                "to auto-detect)"
            )
        else:
            suggestions.append(
                "clangd: apt install clangd  |  brew install llvm"
            )
        warn("  missing  clangd")

    _check(missing, suggestions, name="rust-analyzer",
           hint="rustup component add rust-analyzer")

    # --- dep-graph tools -----------------------------------------------------
    log("Checking dep-graph tools")
    _check(missing, suggestions, name="madge",
           hint="npm i -g madge")
    _check(missing, suggestions, name="pipdeptree",
           hint="pipx install pipdeptree  OR  uv tool install pipdeptree")
    _check(missing, suggestions, name="cargo",
           hint="install Rust toolchain (rustup) for 'cargo metadata'")
    _check(missing, suggestions, name="cmake",
           hint="optional; only required if the project uses CMake")

    # --- Python libraries ----------------------------------------------------
    log("Checking Python libraries (jinja2)")
    _check_python_lib(missing, suggestions, module="jinja2",
                      install_hint=f"{sys.executable} -m pip install jinja2  "
                                   "OR  uv pip install jinja2")

    # --- summary -------------------------------------------------------------
    print("")
    if not missing:
        log("All project-runtime dependencies present.")
        return 0
    err(f"Missing project dependencies: {' '.join(missing)}")
    err("Manual installation suggestions:")
    for s in suggestions:
        err(f"  - {s}")
    err("")
    err("After installing, re-run install_deps.py")
    return 1


if __name__ == "__main__":
    # For standalone testing
    FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.exit(check_project(framework_root=FRAMEWORK_ROOT))
