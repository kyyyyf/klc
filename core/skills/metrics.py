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
import re
import statistics
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import (  # noqa: E402
    klc_knowledge_dir,
    klc_ticket_dir,
    klc_ticket_meta_file,
    klc_tickets_dir,
)

sys.path.insert(0, str(_file_dir))
import budget_guard  # noqa: E402
import phases  # noqa: E402
import spec_review  # noqa: E402
import token_journal  # noqa: E402


# --- KLC-119 AC-11: the review-artefact crosswalk (D-204) -------------------
#
# Columns: artefact path relative to the ticket dir · the config/phases.yml
# phase ids that HOST it · the ordinal of the first ticket whose directory
# carries it (measured over .klc/tickets/ on 2026-09-18, design/options.md
# F-D6) · whether spec_review.review_mode can gate it off for a track.
_REVIEW_ARTEFACTS = (
    ("spec-review.md",        ("discovery", "discovery-lite"),  96, True),
    ("test-plan-review.md",   ("acceptance-test-plan",),        96, True),
    ("impl-plan-review.md",   ("design", "discovery-lite"),     96, True),
    ("drift-review.md",       ("integrate",),                  103, True),
    ("review/code-review.md", ("review",),                     103, False),
    ("review-report.md",      ("review",),                       1, False),
    ("review-lite-report.md", ("review-lite",),                 40, False),
)

_TICKET_ORDINAL_RE = re.compile(r"(\d+)\s*$")


def _ticket_ordinal(ticket: str) -> int:
    """The numeric suffix of a ticket key (`KLC-119` -> 119). Unparseable
    keys sort as ordinal 0 — treated as pre-dating every table entry, which
    is the conservative (smaller `expected`) direction."""
    m = _TICKET_ORDINAL_RE.search(str(ticket) or "")
    return int(m.group(1)) if m else 0


def _review_signals(meta: dict) -> dict:
    """The signals `spec_review.should_run` needs, recovered from the
    ticket's own meta.json (design/options.md A-D3) — an S ticket with none
    of these recorded reads "cascade not required", which is the
    conservative (smaller `expected`) direction for a ratio KLC-120 wants
    to move."""
    return {
        "risk_tags": meta.get("risk_tags") or [],
        "scope_expansion": bool(meta.get("scope_expansion")),
        "sentinel_hits": bool(meta.get("sentinel_hits")),
    }


def expected_review_artefacts(track: str, ticket: str, meta: dict) -> int:
    """AC-11 denominator. Never a literal: the track's own phase list
    (`phases.load_phases().track_phases(track)`) crossed with the table
    above, filtered by the era the ticket actually ran in (F-018/F-019 —
    the corpus's review-artefact set has already changed shape once)."""
    model = phases.load_phases()
    hosted = {p.id for p in model.track_phases(track)}
    ordinal = _ticket_ordinal(ticket)
    gated_on = spec_review.should_run(track, _review_signals(meta))
    total = 0
    for _path, hosts, since, gated in _REVIEW_ARTEFACTS:
        if ordinal < since or not hosted.intersection(hosts):
            continue
        if gated and not gated_on:
            continue
        total += 1
    return total


def actual_review_artefacts(track: str, ticket: str, meta: dict,
                            ticket_dir: Path) -> int:
    """Numerator: the files that are actually there. A degraded review
    lowers THIS and never the denominator (Q-004)."""
    model = phases.load_phases()
    hosted = {p.id for p in model.track_phases(track)}
    ordinal = _ticket_ordinal(ticket)
    ticket_dir = Path(ticket_dir)
    return sum(1 for path, hosts, since, _g in _REVIEW_ARTEFACTS
               if ordinal >= since and hosted.intersection(hosts)
               and (ticket_dir / path).exists())


def iter_attempts(meta: dict, ticket: str) -> list[tuple[str, dict]]:
    """Committed attempts UNION undrained journal attempts, de-duplicated
    by id (D-005/ADR-004 point 5) — this is what makes the AC-12 backfill
    (journal-only records) visible to the rollup without a CAS push.

    De-duplication tracks ids seen across BOTH sources as it goes (not just
    meta-vs-journal): a re-run of an idempotent journal-only writer (the
    backfill, D-004's deterministic id) can append more than one physical
    JSONL line carrying the SAME id, and those must collapse to one attempt
    here too (AC-12's own idempotency requirement)."""
    seen: set = set()
    out: list[tuple[str, dict]] = []
    for phase, entry in (meta.get("metrics", {}).get("tokens") or {}).items():
        for rec in budget_guard.normalize_attempts(entry)["attempts"]:
            seen.add(rec.get("id"))
            out.append((phase, rec))
    for rec in token_journal.read(ticket):
        rid = rec.get("id")
        if rid not in seen:
            seen.add(rid)
            out.append((rec.get("phase", "unknown"), rec))
    return out


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
    ticket_ids: list[str] = []
    cancelled_total = 0
    if tickets_dir.exists():
        for meta_file in tickets_dir.glob("*/meta.json"):
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if m.get("phase") in (None, "intake"):
                continue
            # KLC-076: `cancelled` is terminated-early work, NOT completed —
            # unlike `archived` (done), it must never inflate throughput /
            # lead-time / completion. Count it separately and exclude from rows.
            if m.get("phase") == "cancelled":
                cancelled_total += 1
                continue
            rows.append(m)
            ticket_ids.append(meta_file.parent.name)

    tracks: dict[str, list[tuple[dict, str]]] = {}
    for m, tid in zip(rows, ticket_ids):
        tr = m.get("track") or "unknown"
        tracks.setdefault(tr, []).append((m, tid))

    def _ct(m: dict) -> float | None:
        hist = m.get("phase_history") or []
        if not hist:
            return None
        start = hist[0].get("started_at")
        # last finished or in-progress. review-fix (HIGH, AC-15/KLC-117): only
        # an entry that actually CARRIES a timestamp updates `end` — an
        # audit-only entry (retrack.py/scope_fix.py/migrate_notes.py's bare
        # `ts` field, no started_at/finished_at) is transparently skipped
        # instead of nulling out an already-known real end when it happens to
        # be the LAST entry (e.g. an audit note appended to an already-
        # archived ticket). Without this, the note-migration audit entry
        # would silently drop every already-archived ticket out of the
        # cycle-time sample the moment its over-cap note is migrated.
        end = None
        for entry in hist:
            ts = entry.get("finished_at") or entry.get("started_at")
            if ts:
                end = ts
        if not start or not end:
            return None
        try:
            s = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = _dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
            return (e - s).total_seconds()
        except ValueError:
            return None

    per_track = {}
    for track, pairs in tracks.items():
        ms = [m for m, _tid in pairs]
        cts = [c for c in (_ct(m) for m in ms) if c is not None]
        rework_totals = [sum((m.get("rework_count") or {}).values()) for m in ms]

        # KLC-119: attempts list UNION undrained journal, per phase, across
        # every ticket in this track (D-005). `source_counts` now has a
        # `signal` bucket alongside `provider`/`estimated` (AC-10).
        token_by_phase: dict[str, dict[str, list]] = {}
        card_bytes_total = 0
        for m, tid in pairs:
            for phase, rec in iter_attempts(m, tid):
                bucket = token_by_phase.setdefault(
                    phase, {"in": [], "out": [], "cache_hit": [], "source": [],
                           "attempts": []}
                )
                bucket["in"].append(rec.get("in", 0))
                bucket["out"].append(rec.get("out", 0))
                bucket["cache_hit"].append(rec.get("cache_hit", 0))
                bucket["source"].append(rec.get("source", "estimated"))
                bucket["attempts"].append(rec)
                if rec.get("card_bytes"):
                    card_bytes_total += rec["card_bytes"]
        tokens_summary = {
            phase: {
                "avg_in":        round(statistics.mean(v["in"])) if v["in"] else 0,
                "avg_out":       round(statistics.mean(v["out"])) if v["out"] else 0,
                "avg_cache_hit": round(statistics.mean(v["cache_hit"])) if v["cache_hit"] else 0,
                "samples":       len(v["in"]),
                "source_counts": {
                    "provider":  v["source"].count("provider"),
                    "signal":    v["source"].count("signal"),
                    "estimated": v["source"].count("estimated"),
                },
            }
            for phase, v in token_by_phase.items()
        }

        # cheap_escape_rate: fraction of cheap/lite reviews that later
        # had regression or rework.
        cheap_total = sum(
            1 for m in ms
            if m.get("metrics", {}).get("review_depth") in ("cheap", "lite")
        )
        cheap_escaped = sum(
            1 for m in ms
            if m.get("metrics", {}).get("review_depth") in ("cheap", "lite")
            and (
                sum((m.get("rework_count") or {}).values()) > 0
                or m.get("regression_observed", 0) == 1
            )
        )
        cheap_escape_rate = (cheap_escaped / cheap_total) if cheap_total > 0 else None

        # KLC-119 AC-11: the two numbers KLC-120 is scoped to reduce. Both
        # per-ticket averages (F-018's own wording: "average 1.8 reviewer
        # artefacts ... exactly 4.00 for every ticket"); `prompt_bytes_per_ticket`
        # is None (not 0) when the track has no measured attempts at all, so
        # "not measured" never reads as "costs nothing".
        prompt_bytes_per_ticket = (
            (card_bytes_total / len(ms)) if ms and token_by_phase else None
        )
        actual_sum = sum(
            actual_review_artefacts(track, tid, m, klc_ticket_dir(tid))
            for m, tid in pairs
        )
        expected_sum = sum(
            expected_review_artefacts(track, tid, m) for m, tid in pairs
        )
        review_passes_per_ticket = {
            "actual":   (actual_sum / len(ms)) if ms else None,
            "expected": (expected_sum / len(ms)) if ms else None,
            "ratio":    (actual_sum / expected_sum) if expected_sum else None,
        }

        estimator_calibration = budget_guard.calibration_statement(
            {phase: v["attempts"] for phase, v in token_by_phase.items()}
        )

        per_track[track] = {
            "tickets":               len(ms),
            "cycle_time_sec_median": statistics.median(cts) if cts else None,
            "cycle_time_sec_p95":    _p95(cts),
            "rework_mean":           statistics.mean(rework_totals) if rework_totals else 0,
            "tokens_by_phase":       tokens_summary,
            "cheap_escape_rate":     cheap_escape_rate,
            "prompt_bytes_per_ticket":    prompt_bytes_per_ticket,
            "review_passes_per_ticket":   review_passes_per_ticket,
            "estimator_calibration":      estimator_calibration,
        }

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets_total": len(rows),
        "cancelled_total": cancelled_total,   # KLC-076: excluded from tickets_total
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
