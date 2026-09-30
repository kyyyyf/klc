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
import math
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


# --------------------------------------------------------------------------- #
# KLC-110 step-6: the retrieval rollup (AC-13, AC-14, AC-20)
# --------------------------------------------------------------------------- #
_RETRIEVAL_MEANS = (
    ("precision_at_5",          ("files_likely_to_edit", "precision")),
    ("recall_at_5",             ("files_likely_to_edit", "recall")),
    ("precision_at_10",         ("files_to_read_first", "precision")),
    ("recall_at_10",            ("files_to_read_first", "recall")),
    ("files_before_first_edit", ("files_to_read_first", "items_before_first_hit")),
    ("tests_recall",            ("tests_to_read_or_run", "recall")),
    ("modules_precision",       ("affected_modules_hint", "precision")),
    ("modules_recall",          ("affected_modules_hint", "recall")),
)

# AC-14's four, plus one additive fifth. `no_record` is NOT a confidence value:
# it is the count of tickets carrying no `metrics.retrieval` key at all — most
# of the archived corpus today, and every XS/unsignalled-S ticket after the
# KLC-110 track gate. Putting those in `unknown` would inflate the one raw
# count AC-14 asks for by name with tickets that were never measured (D-303).
_CONFIDENCE_BUCKETS = ("high", "medium", "low", "unknown")
_NO_RECORD = "no_record"


def _retrieval_rollup(metas: list[dict]) -> dict:
    """AC-13 / AC-14. Aggregates ONLY status-ok records; an unavailable
    record is counted, never averaged. A null metric (an empty candidate
    list, AC-6) is excluded from its mean — counting it as a zero would
    re-introduce the fake zero KLC-110 exists to remove — and a mean with no
    samples reports null. `degraded_count` slices the honest question a
    reader asks next: was this a weak retriever, or a degraded index
    (D-217)?"""
    recs = [(m, (m.get("metrics") or {}).get("retrieval") or {}) for m in metas]
    ok = [(m, r) for m, r in recs if r.get("status") == "ok"]
    out = {
        "tickets_scored": len(ok),
        "tickets_unavailable": sum(1 for _, r in recs if r.get("status") == "unavailable"),
        "degraded_count": sum(1 for _, r in ok if r.get("degraded_inputs")),
        "zero_precision_at_5_tickets": sorted(
            m.get("ticket") for m, r in ok
            if not (r.get("files_likely_to_edit") or {}).get("precision")),
    }
    for name, (arrow, key) in _RETRIEVAL_MEANS:
        vals = [v for _, r in ok
                if (v := (r.get(arrow) or {}).get(key)) is not None]
        out[f"{name}_mean"] = statistics.mean(vals) if vals else None
    return out


def _per_confidence(rows: list[dict]) -> dict:
    """Top-level AC-14 block, keyed by the confidence the trace CLAIMED. On
    this repository today every live trace caps to `low`, so an empty `high`
    bucket is the expected production reading until KLC-123 scopes that cap
    (Q-211)."""
    buckets: dict[str, list[dict]] = {b: [] for b in (*_CONFIDENCE_BUCKETS, _NO_RECORD)}
    for m in rows:
        metrics_block = m.get("metrics") or {}
        if "retrieval" not in metrics_block or not isinstance(metrics_block["retrieval"], dict):
            # Never measured: no trace was ever scored for this ticket.
            # Membership is decided by the KEY's presence, not by a confidence
            # lookup, because a missing key and a `confidence: unknown` record
            # both read as None.
            buckets[_NO_RECORD].append(m)
            continue
        claimed = metrics_block["retrieval"].get("confidence")
        buckets[claimed if claimed in _CONFIDENCE_BUCKETS else "unknown"].append(m)
    return {b: {"tickets": len(ms), "retrieval": _retrieval_rollup(ms)}
            for b, ms in buckets.items()}


# --- KLC-133 AC-10/AC-11: per-source buckets, no mixed average -------------

_SOURCES = ("provider", "signal", "estimated")


def _num(v):
    """A genuine int/float, never a bool (bool is technically an int
    subclass but is never a token/turn/cost value) and never NaN/Infinity.
    Anything else (a stray string from a hand-edited corpus, etc.) reads as
    "not reported" rather than raising or silently becoming 0."""
    return v if type(v) in (int, float) and math.isfinite(v) else None


def _avg(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _source_bucket(recs: list[dict], source: str) -> dict:
    """AC-10: one source's own samples/avg_in/avg_out/avg_cache_hit, plus
    (provider only) avg_cache_write/avg_num_turns/cost_usd_total/
    failed_samples. A failed attempt counts in `samples`/`failed_samples`/
    `cost_usd_total` but never in an average (Q-004)."""
    ok = [r for r in recs if r.get("failed") is not True]
    bucket = {
        "samples":       len(recs),
        "avg_in":        _avg(_num(r.get("in")) for r in ok),
        "avg_out":       _avg(_num(r.get("out")) for r in ok),
        "avg_cache_hit": _avg(_num(r.get("cache_hit")) for r in ok),
    }
    if source == "provider":
        costs = [c for c in (_num(r.get("cost_usd")) for r in recs) if c is not None]
        bucket.update(
            avg_cache_write=_avg(_num(r.get("cache_write")) for r in ok),
            avg_num_turns=_avg(_num(r.get("num_turns")) for r in ok),
            cost_usd_total=sum(costs) if costs else None,
            failed_samples=sum(1 for r in recs if r.get("failed") is True),
        )
    return bucket


def _measured_per_ticket(pairs: list[tuple[dict, str]], phase: str,
                         tag_key: str) -> dict:
    """AC-11: per-ticket averages over FULLY measured tickets only — every
    tagged run attempt of *phase* for that ticket is a `provider` attempt.
    A ticket with both provider and tagged non-provider attempts counts
    only in `partial_tickets`; a ticket with no provider attempt at all
    (estimated-only), or whose tagged provider attempts ALL failed
    (impl-plan-review F-8), counts in NEITHER — its cost still lands in
    `by_source.provider.cost_usd_total` via `_source_bucket` above, just not
    here. Each figure is `null`, never 0, when no ticket qualifies."""
    fully_measured: list[tuple[float, float, float, float]] = []
    partial = 0
    for m, tid in pairs:
        tagged = [rec for p, rec in iter_attempts(m, tid)
                 if p == phase and rec.get(tag_key)]
        if not tagged:
            continue
        sources = {r.get("source") for r in tagged}
        if sources == {"provider"}:
            ok = [r for r in tagged if r.get("failed") is not True]
            if not ok:
                continue  # F-8: all tagged provider attempts failed
            fully_measured.append((
                sum(budget_guard._total_input(r) for r in ok),
                sum(_num(r.get("out")) or 0 for r in ok),
                sum(_num(r.get("cost_usd")) or 0 for r in ok),
                sum(_num(r.get("num_turns")) or 0 for r in ok),
            ))
        elif "provider" in sources:
            partial += 1
        # else: estimated-only — counts in neither.

    tickets = len(fully_measured)

    def _mean(idx: int) -> float | None:
        return (sum(t[idx] for t in fully_measured) / tickets) if tickets else None

    return {
        "tickets":         tickets,
        "partial_tickets": partial,
        "avg_total_input": _mean(0),
        "avg_out":         _mean(1),
        "avg_cost_usd":    _mean(2),
        "avg_num_turns":   _mean(3),
    }


def _pool_duplicate_rate(ticket_dir: Path) -> tuple[float, int] | None:
    """KLC-127 AC-18/step-12 F-3: one ticket's `review/findings-pool.json`
    `duplicate_rate` PLUS its `raw_count` (used to WEIGHT the per-track mean
    so a 2-finding ticket no longer counts as much as a 20-finding one), or
    `None` when the file is absent, unreadable, or its rate is JSON null —
    never coerced to 0 (a null rate, including build_pool's own single-
    reviewer-contributed null, must never enter the mean)."""
    path = ticket_dir / "review" / "findings-pool.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    rate = data.get("duplicate_rate")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return None
    raw = data.get("raw_count")
    weight = raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 1
    return float(rate), weight


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
        tagged_per_ticket: dict[str, int] = {}
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
                # KLC-133 F-016: only an ESTIMATED attempt's card_bytes feeds
                # prompt_bytes_per_ticket — a provider attempt is never
                # double-counted into the prompt-size figure.
                if rec.get("card_bytes") and rec.get("source") == "estimated":
                    card_bytes_total += rec["card_bytes"]
                # KLC-133 AC-11: only a non-failed reviewer-tagged attempt of
                # phase "review" counts an executed LLM review pass — a
                # build-phase attempt is never reviewer-tagged (AC-6), and a
                # failed reviewer dispatch never counted as executed.
                if (phase == "review" and rec.get("reviewer")
                        and rec.get("failed") is not True):
                    tagged_per_ticket[tid] = tagged_per_ticket.get(tid, 0) + 1
        # KLC-133 AC-10: every averaged figure lives under exactly ONE
        # `by_source` bucket — no more mixed avg_in/avg_out/avg_cache_hit at
        # the phase level (F-011 removed). `samples`/`source_counts` stay.
        tokens_summary = {
            phase: {
                "samples":       len(v["in"]),
                "source_counts": {
                    "provider":  v["source"].count("provider"),
                    "signal":    v["source"].count("signal"),
                    "estimated": v["source"].count("estimated"),
                },
                "by_source": {
                    s: _source_bucket(
                        [r for r in v["attempts"] if r.get("source") == s], s)
                    for s in _SOURCES
                },
            }
            for phase, v in token_by_phase.items()
        }
        measured_per_ticket = {
            "review": _measured_per_ticket(pairs, "review", "reviewer"),
            "build":  _measured_per_ticket(pairs, "build", "run_pass"),
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

        # KLC-120 AC-4/D-013: a REAL count of executed LLM review passes,
        # counted from reviewer-tagged attempt records — distinct from
        # review_passes_per_ticket above, which counts artefact FILES, not
        # model calls (F-010). Averaged only over tickets that carry at
        # least one tagged attempt, never over the whole track — "not
        # measured" must never read as "costs nothing" (the same trap
        # prompt_bytes_per_ticket already avoids).
        measured_counts = list(tagged_per_ticket.values())
        review_llm_passes_per_ticket = (
            sum(measured_counts) / len(measured_counts)
        ) if measured_counts else None
        review_llm_passes_measured_tickets = len(measured_counts)

        estimator_calibration = budget_guard.calibration_statement(
            {phase: v["attempts"] for phase, v in token_by_phase.items()}
        )

        # KLC-127 AC-18/D-116/step-12 F-3: the `duplicate_rate` over tickets
        # whose review/findings-pool.json carries a NUMERIC rate — a pool
        # with a null rate (no review-kind findings, or fewer than two
        # contributing reviewers, AC-17/F-3) is not averaged in, and a track
        # with no pooled ticket at all reads None, never 0 (the same "not
        # measured never reads as costs nothing" rule as the figures above).
        # Weighted by each ticket's raw_count (D-1xx: re-check this weight
        # choice after ~10 more tickets carry a pool) so a 2-finding ticket
        # does not count as much as a 20-finding one.
        dup_stats = [r for r in (_pool_duplicate_rate(klc_ticket_dir(tid)) for _m, tid in pairs)
                    if r is not None]
        total_weight = sum(w for _r, w in dup_stats)
        review_duplicate_rate = (
            sum(r * w for r, w in dup_stats) / total_weight
        ) if total_weight else None

        per_track[track] = {
            "tickets":               len(ms),
            "cycle_time_sec_median": statistics.median(cts) if cts else None,
            "cycle_time_sec_p95":    _p95(cts),
            "rework_mean":           statistics.mean(rework_totals) if rework_totals else 0,
            "tokens_by_phase":       tokens_summary,
            "measured_per_ticket":   measured_per_ticket,
            "cheap_escape_rate":     cheap_escape_rate,
            "prompt_bytes_per_ticket":    prompt_bytes_per_ticket,
            "review_passes_per_ticket":   review_passes_per_ticket,
            "review_llm_passes_per_ticket":          review_llm_passes_per_ticket,
            "review_llm_passes_measured_tickets":    review_llm_passes_measured_tickets,
            "review_duplicate_rate":      review_duplicate_rate,
            "estimator_calibration":      estimator_calibration,
            "retrieval":                  _retrieval_rollup(ms),   # KLC-110 AC-13
        }

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets_total": len(rows),
        "cancelled_total": cancelled_total,   # KLC-076: excluded from tickets_total
        "per_track":     per_track,
        "per_confidence": _per_confidence(rows),   # KLC-110 AC-14
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
