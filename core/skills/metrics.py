#!/usr/bin/env python3
"""metrics.py — per-ticket and rollup metric storage.

Per-ticket metrics live in `meta.json:metrics`. This skill offers
three operations on top:

    set       — merge key/value pairs into meta.json:metrics
    show      — print the metrics block as JSON
    rollup    — aggregate across all tickets and write
                .klc/knowledge/process-metrics.json

The skill does not compute any derived numbers on `set` — callers
pass in already-measured values (durations in ms, counts, outcomes).
Rollups compute medians / p95 / rework rate off the raw data.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import (  # noqa: E402
    klc_knowledge_dir,
    klc_ticket_meta_file,
    klc_tickets_dir,
)


def _read_meta(ticket: str) -> dict:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        raise FileNotFoundError(f"ticket {ticket!r}: no meta.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    p = klc_ticket_meta_file(ticket)
    p.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def _coerce(value: str) -> object:
    """Parse CLI-provided --kv values as int/float/bool/JSON when they
    look like one, else keep the string."""
    if value.startswith("{") or value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def cmd_set(args: argparse.Namespace) -> int:
    meta = _read_meta(args.ticket)
    metrics = meta.setdefault("metrics", {})
    for kv in args.kv:
        if "=" not in kv:
            sys.stderr.write(f"metrics: --kv expects key=value; got {kv!r}\n")
            return 2
        key, _, raw = kv.partition("=")
        metrics[key.strip()] = _coerce(raw)
    _write_meta(args.ticket, meta)
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    meta = _read_meta(args.ticket)
    print(json.dumps(meta.get("metrics", {}), indent=2, ensure_ascii=False))
    return 0


def cmd_rollup(args: argparse.Namespace) -> int:
    tickets_dir = klc_tickets_dir()
    rows: list[dict] = []
    if tickets_dir.exists():
        for meta_file in tickets_dir.glob("*/meta.json"):
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if m.get("phase") in (None, "intake"):
                continue
            rows.append(m)

    tracks = {}
    for m in rows:
        tr = m.get("track") or "unknown"
        tracks.setdefault(tr, []).append(m)

    def _ct(m: dict) -> float | None:
        hist = m.get("phase_history") or []
        if not hist:
            return None
        start = hist[0].get("started_at")
        # last finished or in-progress
        end = None
        for entry in hist:
            end = entry.get("finished_at") or entry.get("started_at")
        if not start or not end:
            return None
        try:
            s = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = _dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
            return (e - s).total_seconds()
        except ValueError:
            return None

    per_track = {}
    for track, ms in tracks.items():
        cts = [c for c in (_ct(m) for m in ms) if c is not None]
        rework_totals = [sum((m.get("rework_count") or {}).values()) for m in ms]
        per_track[track] = {
            "tickets":         len(ms),
            "cycle_time_sec_median": statistics.median(cts) if cts else None,
            "cycle_time_sec_p95":    _p95(cts),
            "rework_mean":     statistics.mean(rework_totals) if rework_totals else 0,
        }

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets_total": len(rows),
        "per_track":     per_track,
    }
    out = klc_knowledge_dir() / "process-metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = max(0, int(round(0.95 * (len(s) - 1))))
    return s[idx]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("set", help="merge key=value pairs into meta.json:metrics")
    p.add_argument("--ticket", required=True)
    p.add_argument("--kv", nargs="+", required=True,
                   help="one or more key=value pairs")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("show", help="print meta.json:metrics as JSON")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("rollup", help="aggregate across all tickets")
    p.set_defaults(func=cmd_rollup)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
