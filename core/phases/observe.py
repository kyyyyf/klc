#!/usr/bin/env python3
"""Phase 8 — Observe (optional).

No-op today for projects without deploy automation. Records a
`observation_started_at` timestamp on first call and advances to
`learn` after `--hours N` elapsed (or immediately with `--now`).

Wire this to CI alerts later via a webhook → `klc observe <key>
--alert '<json>'`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle  # noqa: E402


def _meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


def _write(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc observe")
    ap.add_argument("ticket")
    ap.add_argument("--now", action="store_true", help="skip observation window, go to learn")
    ap.add_argument("--alert", default=None,
                    help="record an alert (JSON blob) in meta.json:alerts")
    args = ap.parse_args(argv)

    meta = _meta(args.ticket)
    if meta["phase"] not in ("observe",):
        sys.stderr.write(
            f"klc observe: expected phase 'observe', got {meta['phase']!r}\n"
        )
        return 1

    if args.alert:
        try:
            alert_obj = json.loads(args.alert)
        except json.JSONDecodeError:
            alert_obj = {"raw": args.alert}
        meta.setdefault("alerts", []).append({
            "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": alert_obj,
        })
        _write(args.ticket, meta)
        print(f"OBSERVE_ALERT_RECORDED {args.ticket}")
        return 0

    if "observation_started_at" not in meta:
        meta["observation_started_at"] = _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _write(args.ticket, meta)

    if args.now:
        meta.setdefault("metrics", {})["alerts_seen"] = len(meta.get("alerts", []))
        _write(args.ticket, meta)
        lifecycle.advance(args.ticket, "learn", note="observation ended (--now)")
        print(f"OBSERVE_DONE {args.ticket}")
        return 0

    print(f"OBSERVE_STARTED {args.ticket}")
    print(f"  started_at: {meta['observation_started_at']}")
    print(f"  To finish:  klc observe {args.ticket} --now")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
