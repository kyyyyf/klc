#!/usr/bin/env python3
"""install_deps.py — check (and when possible auto-detect) framework deps.

Port of install-deps.sh. Cross-platform: works on Linux, macOS, and
Windows PowerShell. Never installs anything — it reports what's
missing, how to install it, and auto-registers tools that exist on
disk but aren't on PATH (Windows + Visual Studio clangd).

Exit 0 = every required dep present or auto-registered.
Exit 1 = at least one dep missing; manual instructions printed to stderr.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
from _paths import klc_dir, klc_config_dir, klc_logs_dir  # noqa: E402
from tools import record_tool, resolve_tool  # noqa: E402


# --- logging ------------------------------------------------------------------

_LOG_PATH: Path | None = None


def _log_init() -> None:
    global _LOG_PATH
    klc_logs_dir().mkdir(parents=True, exist_ok=True)
    _LOG_PATH = klc_logs_dir() / "install-deps.log"


def log(msg: str) -> None:
    line = f"[install-deps] {msg}"
    print(line)
    if _LOG_PATH:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def warn(msg: str) -> None:
    line = f"[install-deps][warn] {msg}"
    sys.stderr.write(line + "\n")
    if _LOG_PATH:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def err(msg: str) -> None:
    line = f"[install-deps][err]  {msg}"
    sys.stderr.write(line + "\n")
    if _LOG_PATH:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# --- platform ----------------------------------------------------------------

def platform_tag() -> str:
    s = platform.system()
    if s == "Linux":
        return "linux"
    if s == "Darwin":
        return "macos"
    if s == "Windows":
        return "windows"
    return "unknown"


# --- Windows: Visual Studio auto-detect --------------------------------------

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


# --- Tool checks --------------------------------------------------------------

def _has(name: str) -> Path | None:
    hit = shutil.which(name)
    return Path(hit) if hit else None


def _check(missing: list[str], suggestions: list[str], *,
           name: str, hint: str, alt_names: tuple[str, ...] = ()) -> bool:
    """Check for `name` (or any of alt_names) on PATH. Returns True if found."""
    for n in (name, *alt_names):
        hit = _has(n)
        if hit:
            log(f"  ok  {name} ({hit})")
            return True
    missing.append(name)
    suggestions.append(f"{name}: {hint}")
    warn(f"  missing  {name}")
    return False


def _check_python_lib(missing: list[str], suggestions: list[str], *,
                      module: str, install_hint: str) -> bool:
    try:
        __import__(module)
        log(f"  ok  python module {module}")
        return True
    except ImportError:
        missing.append(module)
        suggestions.append(f"{module}: {install_hint}")
        warn(f"  missing  python module {module}")
        return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="install-deps",
                                 description="Check framework dependencies.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat optional tools as required.")
    args = ap.parse_args(argv)

    # Ensure .klc/logs exists before first log() call.
    klc_dir().mkdir(parents=True, exist_ok=True)
    _log_init()

    log(f"Platform detected: {platform_tag()}")
    log(f"Python:            {sys.executable} ({platform.python_version()})")

    missing: list[str] = []
    suggestions: list[str] = []

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
        # Validate every profile rule.
        import tempfile
        rule_failures = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for suffix in ("cpp", "py", "ts", "rs"):
                (tmp / f"empty.{suffix}").write_text("", encoding="utf-8")
            resolve = FRAMEWORK_ROOT / "core" / "skills" / "profile-resolve.py"
            try:
                r = subprocess.run(
                    [sys.executable, str(resolve), "--field", "rules"],
                    capture_output=True, text=True, timeout=10,
                )
                rule_dirs = r.stdout.strip().split()
            except (OSError, subprocess.TimeoutExpired):
                rule_dirs = []
            for rd in rule_dirs:
                rd_path = FRAMEWORK_ROOT / rd
                if not rd_path.is_dir():
                    continue
                for rf in rd_path.glob("*.yaml"):
                    try:
                        check = subprocess.run(
                            [str(ag_path), "scan", "--rule", str(rf), str(tmp)],
                            capture_output=True, text=True, timeout=10,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        rule_failures += 1
                        warn(f"  broken rule: {rf}")
                        continue
                    if check.returncode != 0:
                        warn(f"  broken rule: {rf}")
                        rule_failures += 1
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

    # --- mutation testing tools ---------------------------------------------
    log("Checking mutation testing tools (optional per language)")
    _check(missing, suggestions, name="mutmut",
           hint="pip install mutmut  OR  pipx install mutmut")
    _check(missing, suggestions, name="stryker",
           hint="npm install -g @stryker-mutator/core")
    _check(missing, suggestions, name="cargo-mutants",
           hint="cargo install cargo-mutants")
    if not _has("mull-runner"):
        warn("  missing  mull-runner (C++ mutation testing; advisory)")
        warn("    install: https://github.com/mull-project/mull "
             "(requires LLVM; skip on Windows/UE projects)")

    # --- summary -------------------------------------------------------------
    print("")
    if not missing:
        log("All dependencies present.")
        return 0
    err(f"Missing dependencies: {' '.join(missing)}")
    err("Manual installation suggestions:")
    for s in suggestions:
        err(f"  - {s}")
    err("")
    err("After installing, re-run install_deps.py")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
