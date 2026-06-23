#!/usr/bin/env python3
"""`klc install <project-root>` — bootstrap a project to use this
klc checkout as its framework (layout B).

Creates inside <project-root>/.klc/:

    bin/klc              — shim that forwards every call to this klc
                           repo, with PROJECT_ROOT pinned to <project-root>
    config/profile.yml   — seed, `profile: generic`
    config/ticket-id.yml — seed regex for Jira-style keys
    index/               — empty, ready for init
    logs/
    reports/
    tickets/
    knowledge/           — with seed copy of reviewer-allowlist

Plus, in <project-root>:
    .mcp.json            — copied from the active profile if none exists
    .gitignore           — appended with recommended rules (only if not
                           already listed)

When done, prints the next steps — which amount to running
`.klc/bin/klc init` from the project root.

Implementation notes:
  - The shim is a tiny POSIX shell script; no symlinks (Windows
    compatibility, WSL quirks on /mnt filesystems).
  - Seeds are copied from the klc repo's config/ and never modified
    afterwards — the shipped versions stay as templates. The project
    copies are the live ones.
  - Running install twice is idempotent. Pre-existing config files are
    NOT overwritten; the script warns and continues.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc install")
    ap.add_argument("project_root",
                    help="path to the project to bootstrap")
    ap.add_argument("--profile", default="generic",
                    help="profile to seed into .klc/config/profile.yml "
                         "(default: generic)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing .klc/ files")
    args = ap.parse_args(argv)

    project = Path(args.project_root).resolve()
    if not project.exists() or not project.is_dir():
        sys.stderr.write(f"klc install: {project} is not a directory\n")
        return 2

    fw = Path(__file__).resolve().parent.parent.parent   # repo root
    profile_dir = fw / "profiles" / args.profile
    if not profile_dir.exists():
        sys.stderr.write(
            f"klc install: profile {args.profile!r} not found at {profile_dir}\n"
        )
        return 2

    klc = project / ".klc"
    bin_dir = klc / "bin"
    config_dir = klc / "config"
    knowledge_dir = klc / "knowledge"
    for d in (klc, bin_dir, config_dir, knowledge_dir,
              klc / "index", klc / "logs", klc / "reports",
              klc / "tickets"):
        d.mkdir(parents=True, exist_ok=True)

    # --- shims -------------------------------------------------------------
    # Triple-write unconditionally: bash (klc) for Unix, cmd (klc.cmd) for
    # cmd.exe, PowerShell (klc.ps1) for pwsh. Cost is ~400 bytes; each
    # runs regardless of which shell is active.
    shim_variants = (
        ("klc",     _shim_source(fw, project),     True),
        ("klc.cmd", _shim_source_cmd(fw, project), False),
        ("klc.ps1", _shim_source_ps1(fw, project), False),
    )
    for filename, body, make_executable in shim_variants:
        path = bin_dir / filename
        if path.exists() and not args.force:
            sys.stderr.write(
                f"klc install: {path} already exists (use --force to "
                "overwrite)\n"
            )
            continue
        path.write_text(body, encoding="utf-8")
        if make_executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # --- config seeds ------------------------------------------------------
    _seed(config_dir / "profile.yml", f"profile: {args.profile}\n",
          force=args.force)
    _copy_if_missing(fw / "config" / "ticket-id.yml",
                     config_dir / "ticket-id.yml",
                     force=args.force)

    # Ship reviewer allowlist seed so the runtime picks up the project
    # copy even before the first retrospective.
    _copy_if_missing(fw / "config" / "reviewer-allowlist.seed.yml",
                     knowledge_dir / "reviewer-allowlist.yml",
                     force=args.force)

    # --- .mcp.json ---------------------------------------------------------
    mcp_src = profile_dir / "mcp.json"
    mcp_dst = project / ".mcp.json"
    if mcp_src.exists():
        if mcp_dst.exists() and not args.force:
            sys.stderr.write(
                f"klc install: {mcp_dst} already exists; not overwriting\n"
            )
        else:
            shutil.copy2(mcp_src, mcp_dst)

    # --- .gitignore --------------------------------------------------------
    _ensure_gitignore(project)

    # --- summary -----------------------------------------------------------
    print(f"INSTALL_OK {project}")
    print(f"  shims:      .klc/bin/{{klc, klc.cmd, klc.ps1}}")
    print(f"  profile:    {args.profile}")
    print(f"  mcp.json:   {'copied' if mcp_src.exists() else '(profile has no mcp.json)'}")
    print()
    print("Next steps (run from the project root):")
    print(f"  cd {project}")
    print( "  # Unix / macOS:    .klc/bin/klc doctor")
    print( "  # PowerShell:      .\\.klc\\bin\\klc.ps1 doctor")
    print( "  # cmd.exe:         .klc\\bin\\klc.cmd doctor")
    print("")
    print(f"  python {fw}/scripts/install_deps.py   # verify dep tools")
    print( "  <shim> init            # bootstrap indices + per-module CLAUDE.md")
    return 0


# ---- helpers --------------------------------------------------------------

def _shim_source(fw: Path, project: Path) -> str:  # noqa: ARG001 project unused after self-locate
    return (
        "#!/usr/bin/env bash\n"
        "# klc shim — generated by `klc install`.\n"
        "# Forwards every call to the klc repo at:\n"
        f"#   {fw}\n"
        "# PROJECT_ROOT is derived from the shim's own location at runtime,\n"
        "# so the shim stays correct after the project is moved or renamed.\n"
        "#\n"
        "# Regenerate with: <klc-repo>/scripts/klc install <project> --force\n"
        "\n"
        "set -eu\n"
        f'KLC_FW="{fw}"\n'
        'SHIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'export PROJECT_ROOT="$(cd "$SHIM_DIR/../.." && pwd)"\n'
        'exec "$KLC_FW/scripts/klc" "$@"\n'
    )


def _shim_source_cmd(fw: Path, project: Path) -> str:  # noqa: ARG001 project unused after self-locate
    """Windows cmd.exe shim. Uses backslashes and %*.

    PROJECT_ROOT is derived from the shim's own directory (%~dp0) at runtime
    so the shim works correctly after the project is moved or renamed.
    """
    fw_win = str(fw).replace("/", "\\")
    return (
        "@echo off\r\n"
        "REM klc shim — generated by `klc install`.\r\n"
        "REM Regenerate with: <klc-repo>\\scripts\\klc install <project> --force\r\n"
        "setlocal\r\n"
        f'set "KLC_FW={fw_win}"\r\n'
        'for %%I in ("%~dp0..\\..") do set "PROJECT_ROOT=%%~fI"\r\n'
        'python "%KLC_FW%\\scripts\\klc" %*\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )


def _shim_source_ps1(fw: Path, project: Path) -> str:  # noqa: ARG001 project unused after self-locate
    """PowerShell shim. Forwards $args verbatim and preserves the exit
    code via $LASTEXITCODE.

    PROJECT_ROOT is derived from $PSScriptRoot at runtime so the shim
    works correctly after the project is moved or renamed.
    """
    fw_win = str(fw).replace("/", "\\").replace("'", "''")
    return (
        "# klc shim — generated by `klc install`.\n"
        "# Regenerate with: <klc-repo>\\scripts\\klc install <project> --force\n"
        f"$env:KLC_FW = '{fw_win}'\n"
        '$env:PROJECT_ROOT = (Resolve-Path "$PSScriptRoot\\..\\..").Path\n'
        "& python \"$env:KLC_FW\\scripts\\klc\" @args\n"
        "exit $LASTEXITCODE\n"
    )


def _seed(dst: Path, body: str, *, force: bool) -> None:
    if dst.exists() and not force:
        sys.stderr.write(f"klc install: {dst} already exists; keeping as-is\n")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body, encoding="utf-8")


def _copy_if_missing(src: Path, dst: Path, *, force: bool) -> None:
    if not src.exists():
        return
    if dst.exists() and not force:
        sys.stderr.write(f"klc install: {dst} already exists; keeping as-is\n")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


GITIGNORE_RULES = """
# klc per-project state
.klc/index/
.klc/logs/
.klc/reports/partials-*
.klc/reports/pending-*
!.klc/reports/review-*.md
!.klc/tickets/
!.klc/knowledge/
!.klc/bin/
!.klc/config/
""".lstrip()


def _ensure_gitignore(project: Path) -> None:
    gi = project / ".gitignore"
    if gi.exists():
        existing = gi.read_text(encoding="utf-8")
        # Only append if the klc section isn't already there
        if ".klc/index/" in existing:
            return
        with gi.open("a", encoding="utf-8") as f:
            if not existing.endswith("\n"):
                f.write("\n")
            f.write("\n")
            f.write(GITIGNORE_RULES)
    else:
        gi.write_text(GITIGNORE_RULES, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
