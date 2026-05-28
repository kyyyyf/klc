#!/usr/bin/env python3
"""budget.py — cycle-limit counter per ticket.

Defaults loaded from `.klc/config/budgets.yml`, falling back to the
values shipped in this module. Counters live under
`meta.json:budgets` so `klc status` and metrics see them.

Subcommands:

    bump      --ticket K --counter name [--by N]   default +1
    check     --ticket K --counter name             exit 0 if below limit,
                                                    1 if at/over
    status    --ticket K                            print current counters
    limits                                          print effective limits
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import klc_config_dir, klc_ticket_meta_file  # noqa: E402


DEFAULT_LIMITS: dict[str, int] = {
    "regenerate_spec":        3,
    "regenerate_test_plan":   3,
    "regenerate_impl_plan":   3,
    "red_test_fix_attempts":  3,
    "mutation_fix_attempts":  3,
    "rework_review_cycles":   3,
    "xs_fix_attempts":        3,
}


def _load_limits() -> dict[str, int]:
    override = klc_config_dir() / "budgets.yml"
    if not override.exists():
        return dict(DEFAULT_LIMITS)
    merged = dict(DEFAULT_LIMITS)
    for raw in override.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(\w[\w_]*)\s*:\s*(\d+)", line)
        if m:
            merged[m.group(1)] = int(m.group(2))
    return merged


def _meta(ticket: str) -> dict:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        raise FileNotFoundError(f"ticket {ticket!r}: no meta.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _write(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def cmd_bump(args: argparse.Namespace) -> int:
    meta = _meta(args.ticket)
    budgets = meta.setdefault("budgets", {})
    budgets[args.counter] = int(budgets.get(args.counter, 0)) + args.by
    _write(args.ticket, meta)
    print(json.dumps({args.counter: budgets[args.counter]}))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    meta = _meta(args.ticket)
    current = int((meta.get("budgets") or {}).get(args.counter, 0))
    limits = _load_limits()
    limit = limits.get(args.counter)
    if limit is None:
        sys.stderr.write(f"budget check: unknown counter {args.counter!r}\n")
        return 2
    status = "ok" if current < limit else "exceeded"
    print(json.dumps({"counter": args.counter, "current": current,
                       "limit": limit, "status": status}))
    return 0 if status == "ok" else 1


def cmd_status(args: argparse.Namespace) -> int:
    meta = _meta(args.ticket)
    limits = _load_limits()
    budgets = meta.get("budgets") or {}
    rows = {}
    for name in limits:
        rows[name] = {"current": int(budgets.get(name, 0)), "limit": limits[name]}
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def cmd_limits(_: argparse.Namespace) -> int:
    print(json.dumps(_load_limits(), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("bump")
    p.add_argument("--ticket", required=True)
    p.add_argument("--counter", required=True)
    p.add_argument("--by", type=int, default=1)
    p.set_defaults(func=cmd_bump)

    p = sub.add_parser("check")
    p.add_argument("--ticket", required=True)
    p.add_argument("--counter", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("status")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("limits")
    p.set_defaults(func=cmd_limits)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
