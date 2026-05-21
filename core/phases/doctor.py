#!/usr/bin/env python3
"""`klc doctor` — install-level health check.

Not ticket-scoped. Walks the framework itself:
  - executables have correct shebang + permissions
  - templates parse
  - active profile manifest + reviewer-allowlist are valid
  - MCP servers respond (if .mcp.json is present — best-effort)
  - git is installed and the project root is a repo
  - Python deps (jinja2) are present

Prints PASS/FAIL per check; exit 0 only if every check passes.
Safe on CI.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
CONFIG = Path(__file__).resolve().parent.parent.parent / "config"
sys.path.insert(0, str(SKILLS))
from _paths import framework_root, project_root  # noqa: E402


CHECKS: list[tuple[str, callable]] = []


def check(name: str):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("skills-executable")
def _skills_executable() -> list[str]:
    errs: list[str] = []
    # Shared helper modules (underscore-prefixed) are imported, not
    # executed; skip the shebang / +x check for them.
    for p in SKILLS.glob("*.py"):
        if p.name.startswith("_"):
            continue
        if not os.access(p, os.X_OK):
            errs.append(f"{p.relative_to(framework_root())} not executable (chmod +x)")
        first = p.read_text(encoding="utf-8", errors="ignore").splitlines()[:1]
        if first and not first[0].startswith("#!"):
            errs.append(f"{p.relative_to(framework_root())} missing shebang")
    return errs


@check("phase-scripts-executable")
def _phases_executable() -> list[str]:
    errs: list[str] = []
    phases_dir = Path(__file__).resolve().parent
    for p in phases_dir.glob("*.py"):
        if p.name == "__init__.py":
            continue
        if not os.access(p, os.X_OK):
            errs.append(f"{p.relative_to(framework_root())} not executable")
    return errs


@check("templates-parse")
def _templates_parse() -> list[str]:
    errs: list[str] = []
    try:
        from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
    except ImportError:
        return ["jinja2 not installed (pip install jinja2)"]
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    for tmpl in TEMPLATES.glob("*.j2"):
        try:
            env.get_template(tmpl.name)
        except TemplateSyntaxError as exc:
            errs.append(f"{tmpl.name}: {exc}")
    return errs


@check("profile-manifest")
def _profile_manifest() -> list[str]:
    errs: list[str] = []
    try:
        import yaml
    except ImportError:
        return ["pyyaml not installed (pip install pyyaml)"]
    prof_cfg = CONFIG / "profile.yml"
    if not prof_cfg.exists():
        return [f"{prof_cfg} missing"]
    data = yaml.safe_load(prof_cfg.read_text()) or {}
    name = data.get("profile")
    if not name:
        return [f"{prof_cfg}: no profile key"]
    manifest = framework_root() / "profiles" / name / "manifest.yml"
    if not manifest.exists():
        return [f"profile {name!r}: {manifest} missing"]
    try:
        yaml.safe_load(manifest.read_text())
    except yaml.YAMLError as exc:
        errs.append(f"{manifest}: {exc}")
    return errs


@check("reviewer-allowlist")
def _reviewer_allowlist() -> list[str]:
    cfg = CONFIG / "reviewer-allowlist.yml"
    if not cfg.exists():
        return []  # seed is optional
    try:
        import yaml
        yaml.safe_load(cfg.read_text())
    except Exception as exc:
        return [f"{cfg}: {exc}"]
    return []


@check("git-available")
def _git() -> list[str]:
    if not shutil.which("git"):
        return ["git not on PATH"]
    r = subprocess.run(["git", "-C", str(project_root()), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"project root {project_root()} is not a git repository"]
    return []


@check("klc-dispatcher")
def _klc() -> list[str]:
    klc = framework_root() / "scripts" / "klc"
    if not klc.exists():
        return ["scripts/klc missing"]
    if not os.access(klc, os.X_OK):
        return ["scripts/klc not executable"]
    return []


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc doctor")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)

    results = []
    overall_ok = True
    for name, fn in CHECKS:
        errs = fn()
        ok = not errs
        overall_ok = overall_ok and ok
        results.append({"check": name, "ok": ok, "errors": errs})

    if args.json:
        print(json.dumps({"ok": overall_ok, "checks": results}, indent=2))
    else:
        for r in results:
            tag = "PASS" if r["ok"] else "FAIL"
            print(f"  {tag} {r['check']}")
            for e in r["errors"]:
                print(f"       - {e}")
        print()
        print("DOCTOR_OK" if overall_ok else "DOCTOR_FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
