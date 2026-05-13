#!/usr/bin/env python3
"""Phase 7 — Integrate (pre + post).

The framework does NOT perform the merge. `klc integrate pre` runs
before the human does `git merge`; `klc integrate post --merge-sha`
runs after. See process-framework-alignment.md change #9 for the
rationale.

    klc integrate pre  <key>                       # snapshot + consistency check
    (human performs `git merge` / opens a PR)
    klc integrate post <key> --merge-sha <sha>     # record SHA, archive, bump phase
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_ticket_dir,
    klc_ticket_meta_file,
    project_root,
)
import lifecycle  # noqa: E402


def _read_meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _snapshot(ticket: str) -> dict:
    """Hash every artefact + .index.json so `post` can detect any
    last-second edit that skipped consistency."""
    out: dict[str, str] = {}
    tdir = klc_ticket_dir(ticket)
    for p in sorted(tdir.rglob("*")):
        if p.is_dir():
            continue
        if any(part.startswith("discovery-context") or part.startswith("design-context")
               or part.startswith("build-context") or part.startswith("scratch")
               or part == "serena-cache" for part in p.parts):
            continue
        rel = str(p.relative_to(tdir))
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def _run_consistency(ticket: str) -> int:
    items_script = Path(__file__).resolve().parent.parent / "skills" / "items.py"
    r = subprocess.run(
        [sys.executable, str(items_script), "validate", "--ticket", ticket],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.stderr.write(r.stderr or r.stdout)
    return r.returncode


def _pre(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "integrate-pre":
        sys.stderr.write(
            f"klc integrate pre: expected phase 'integrate-pre', got {meta['phase']!r}\n"
        )
        return 1

    t0 = _dt.datetime.now(_dt.timezone.utc)
    rc = _run_consistency(ticket)
    if rc != 0:
        sys.stderr.write("klc integrate pre: consistency violations; not advancing.\n")
        return 1

    snap = _snapshot(ticket)
    meta["pre_merge_snapshot"] = snap
    meta["metrics"].setdefault("integrate_pre_ms", 0)
    meta["metrics"]["integrate_pre_ms"] = int(
        (_dt.datetime.now(_dt.timezone.utc) - t0).total_seconds() * 1000
    )
    _write_meta(ticket, meta)

    print(f"INTEGRATE_PRE_OK {ticket}")
    print(f"  snapshot files: {len(snap)}")
    print()
    print(f"Now perform the merge with your team's flow (PR / push / ...).")
    print(f"When the merge lands, run:")
    print(f"  klc integrate post {ticket} --merge-sha <sha>")
    return 0


def _post(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "integrate-pre":
        sys.stderr.write(
            f"klc integrate post: expected phase 'integrate-pre', got {meta['phase']!r}. "
            "Run `klc integrate pre` first.\n"
        )
        return 1

    # Snapshot parity
    old = meta.get("pre_merge_snapshot") or {}
    new = _snapshot(ticket)
    mismatches = [k for k in set(old) | set(new) if old.get(k) != new.get(k)]
    meta.setdefault("metrics", {})["pre_post_snapshot_match"] = not mismatches
    if mismatches and not args.allow_drift:
        sys.stderr.write(
            f"klc integrate post: {len(mismatches)} artefact(s) changed between "
            f"pre and post:\n  " + "\n  ".join(mismatches[:10]) + "\n"
            "Re-run `klc integrate pre` or pass --allow-drift.\n"
        )
        return 1

    meta["merge_sha"] = args.merge_sha
    meta["merged_at"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_meta(ticket, meta)

    # Archive scratch via scratch.py
    scratch_script = Path(__file__).resolve().parent.parent / "skills" / "scratch.py"
    if scratch_script.exists():
        subprocess.run([sys.executable, str(scratch_script), "archive",
                        "--ticket", ticket], check=False)

    lifecycle.advance(ticket, "integrate-post", note=f"merge_sha={args.merge_sha}")

    next_phase = "observe" if args.observe else "learn"
    lifecycle.advance(ticket, next_phase, note="post-merge")
    print(f"INTEGRATE_POST_OK {ticket}")
    print(f"  merge_sha: {args.merge_sha}")
    print(f"  next:      klc {next_phase} {ticket}")
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc integrate")
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("pre")
    p.add_argument("ticket")
    p.set_defaults(func=_pre)

    p = sub.add_parser("post")
    p.add_argument("ticket")
    p.add_argument("--merge-sha", required=True)
    p.add_argument("--allow-drift", action="store_true",
                   help="continue even if the pre/post snapshot disagrees")
    p.add_argument("--observe", action="store_true",
                   help="advance to observe (default: skip to learn)")
    p.set_defaults(func=_post)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
