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
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("profile-resolve: PyYAML required (pip install pyyaml)\n")
    sys.exit(2)


def framework_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_manifest() -> tuple[dict, Path]:
    cfg = framework_root() / "config" / "profile.yml"
    if not cfg.exists():
        sys.stderr.write(f"profile-resolve: {cfg} missing\n"); sys.exit(1)
    profile_name = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("profile")
    if not profile_name:
        sys.stderr.write("profile-resolve: config/profile.yml must set `profile:`\n"); sys.exit(1)
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
