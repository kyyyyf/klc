#!/usr/bin/env python3
"""Resolve one field from the active profile manifest.

Usage:
    profile-resolve.py --field <name>          Print the field value.
    profile-resolve.py --field rules           Print newline-separated paths.
    profile-resolve.py --field excludes-regex  Print a POSIX-ERE alternation
                                               built from excludes[] for use
                                               in shell `grep -Ev`.

The active profile is whatever config/profile.yml:profile points at. The
script exits non-zero with a message on stderr if the field is missing.
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("profile-resolve: PyYAML required (pip install pyyaml)\n")
    sys.exit(2)


def framework_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def project_root() -> Path:
    # Honour explicit env (used when the framework is shared across projects);
    # default to the repo one level above .../, which matches the layout
    # used by init.sh when PROJECT_ROOT is not set.
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return framework_root().parent


def _profile_selector() -> tuple[str, Path]:
    """Locate the active profile name via the settings loader (KLC-100).

    The loader's interleaved ladder resolves the profile from
    settings.yml / profile.yml across the project and framework scopes, so a
    profile set in settings.yml is honored here (and by every runtime reader
    that funnels through this resolver). The returned path is best-effort, for
    diagnostics only."""
    import settings as _settings  # sibling in core/skills (on sys.path)

    name = _settings.profile()
    if name:
        for cfg in (
            project_root() / ".klc" / "config" / "settings.yml",
            project_root() / ".klc" / "config" / "profile.yml",
            framework_root() / "config" / "settings.yml",
            framework_root() / "config" / "profile.yml",
        ):
            if cfg.exists():
                return name, cfg
        return name, framework_root() / "config" / "settings.yml"

    per_project = project_root() / ".klc" / "config" / "profile.yml"
    framework_default = framework_root() / "config" / "profile.yml"
    sys.stderr.write(
        f"profile-resolve: no profile with a `profile:` key found "
        f"(checked settings.yml and {per_project}, {framework_default})\n"
    )
    sys.exit(1)


def load_manifest() -> tuple[dict, Path]:
    profile_name, _ = _profile_selector()
    man = framework_root() / "profiles" / profile_name / "manifest.yml"
    if not man.exists():
        sys.stderr.write(f"profile-resolve: {man} missing\n"); sys.exit(1)
    return yaml.safe_load(man.read_text(encoding="utf-8")) or {}, man.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--field", required=True)
    args = ap.parse_args()
    data, _ = load_manifest()

    if args.field == "excludes-regex":
        ex = data.get("excludes", []) or []
        if not ex:
            print("")
        else:
            print("(^|/)(" + "|".join(ex) + ")(/|$)")
        return 0

    if args.field not in data:
        sys.stderr.write(f"profile-resolve: field `{args.field}` not in manifest\n")
        return 1
    v = data[args.field]
    if isinstance(v, list):
        for x in v:
            print(x)
    elif isinstance(v, dict):
        import json
        print(json.dumps(v, ensure_ascii=False))
    else:
        print(v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
