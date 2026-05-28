#!/usr/bin/env python3
"""per-module-hash.py — per-module signature for differential update.

The project-wide `inventory-hash.json` answers "has anything drifted?"
with a single digest. That is enough for CI gates but too coarse for
periodic updates: when a single module's public API moves, we should
regenerate its CLAUDE.md only, not every module's.

This skill emits `.klc/index/per-module-hash.json`:

    {
      "generated_at": "...",
      "git_sha":      "...",
      "modules": {
        "<name>": {
          "public_api_hash":  "<sha1>",
          "depends_on_hash":  "<sha1>",
          "path":             "<module.path>",
          "symbol_count":     N
        }
      }
    }

Subcommands:

    write   — compute current hashes, overwrite the file (or --out path).
    diff    — compare current hashes to the file's previous contents,
              print JSON with three arrays: changed, added, removed.
              A module is "changed" when public_api_hash OR
              depends_on_hash differs.

The diff command deliberately stays dumb about transitive closure — the
periodic agent walks `depended_by` explicitly when it decides docs to
regenerate. Keeping this skill narrow lets tests exercise each layer
independently.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import klc_index_dir  # noqa: E402


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha1(blob: str) -> str:
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def compute_hashes(modules: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in modules:
        # public_api — canonical list (sorted, names only). We hash names,
        # not signatures: signatures live in symbols_by_module.json.
        # Names + count = "what this module exposes".
        public_api = sorted(m.get("public_api") or [])
        depends_on = sorted(m.get("depends_on") or [])
        out[m["name"]] = {
            "path":             m.get("path") or "",
            "symbol_count":     int(m.get("symbol_count") or 0),
            "public_api_hash":  _sha1("\n".join(public_api)),
            "depends_on_hash":  _sha1("\n".join(depends_on)),
        }
    return out


def cmd_write(args: argparse.Namespace) -> int:
    modules_path = Path(args.modules) if args.modules else klc_index_dir() / "modules.json"
    if not modules_path.exists():
        sys.stderr.write(f"per-module-hash: {modules_path} missing\n")
        return 1
    doc = json.loads(modules_path.read_text(encoding="utf-8"))
    hashes = compute_hashes(doc.get("modules", []))
    payload = {
        "generated_at": _now_iso(),
        "git_sha":      doc.get("git_sha"),
        "modules":      hashes,
    }
    out = Path(args.out) if args.out else klc_index_dir() / "per-module-hash.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE {out} ({len(hashes)} module(s))")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    hash_path = Path(args.hash_file) if args.hash_file else klc_index_dir() / "per-module-hash.json"
    modules_path = Path(args.modules) if args.modules else klc_index_dir() / "modules.json"
    if not modules_path.exists():
        sys.stderr.write(f"per-module-hash: {modules_path} missing\n")
        return 1
    if not hash_path.exists():
        # First run: treat every module as added. The caller decides
        # whether to regenerate everything or to initialise and exit.
        doc = json.loads(modules_path.read_text(encoding="utf-8"))
        current = compute_hashes(doc.get("modules", []))
        json.dump(
            {"changed": [], "added": sorted(current.keys()), "removed": []},
            sys.stdout, indent=2, ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0

    stored = json.loads(hash_path.read_text(encoding="utf-8")).get("modules", {})
    doc = json.loads(modules_path.read_text(encoding="utf-8"))
    current = compute_hashes(doc.get("modules", []))

    stored_names = set(stored.keys())
    current_names = set(current.keys())
    added = sorted(current_names - stored_names)
    removed = sorted(stored_names - current_names)
    changed = []
    for name in sorted(stored_names & current_names):
        before = stored[name]
        after = current[name]
        if before.get("public_api_hash") != after["public_api_hash"] \
           or before.get("depends_on_hash") != after["depends_on_hash"]:
            changed.append(name)

    json.dump(
        {"changed": changed, "added": added, "removed": removed},
        sys.stdout, indent=2, ensure_ascii=False,
    )
    sys.stdout.write("\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_w = sub.add_parser("write", help="compute + persist per-module hashes")
    p_w.add_argument("--modules", default=None,
                     help="override path to modules.json (default .klc/index/modules.json)")
    p_w.add_argument("--out", default=None,
                     help="override output path (default .klc/index/per-module-hash.json)")
    p_w.set_defaults(func=cmd_write)

    p_d = sub.add_parser("diff", help="print changed/added/removed vs. the stored snapshot")
    p_d.add_argument("--hash-file", default=None,
                     help="override path to the stored hash file")
    p_d.add_argument("--modules", default=None,
                     help="override path to modules.json")
    p_d.set_defaults(func=cmd_diff)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
