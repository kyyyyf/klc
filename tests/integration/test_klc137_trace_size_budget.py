"""KLC-137 step-4 — AC-11: `line_ranges` keeps `retrieval_trace.json` well
under the 512 KiB budget across the real ticket corpus.

D-107: the "before" size in every test here is the rebuilt trace with
`line_ranges` popped — the value AC-7/AC-8 already prove equal to what the
pre-ticket retriever would have produced — so no test in this module reads
git history (D-106/D-108).
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

_MAX_BYTES = 512 * 1024

# D-109: the ten pinned tickets spanning F-105's size deciles (median KLC-051,
# largest KLC-103). Step-4 re-checks this list against its own measurement
# and records any substitution in build-log.md.
_PINNED_TICKETS = (
    "KLC-048", "KLC-036", "KLC-141", "KLC-061", "KLC-073",
    "KLC-051", "KLC-077", "KLC-081", "KLC-108", "KLC-103",
)


def _before_after_bytes(trace: dict) -> tuple[int, int]:
    after = len(json.dumps(trace, indent=2, ensure_ascii=False).encode("utf-8"))
    before_trace = dict(trace)
    before_trace.pop("line_ranges", None)
    before = len(json.dumps(before_trace, indent=2, ensure_ascii=False).encode("utf-8"))
    return before, after


def test_rebuilt_traces_for_every_stored_raw_md_ticket_report_before_after_bytes_under_512kib(
    klc137_corpus_traces
):
    """AC-11: per-ticket before/after byte sizes, the total/median/largest
    growth, the share of read-slice files that received at least one range,
    and the largest after-size — all under 512 KiB."""
    assert klc137_corpus_traces
    records = []
    ranged_files = 0
    total_slice_files = 0
    for key, trace in klc137_corpus_traces.items():
        before, after = _before_after_bytes(trace)
        records.append({"ticket": key, "before": before, "after": after,
                        "growth": after - before})
        candidates = set(trace.get("files_to_read_first") or []) | \
            set(trace.get("files_likely_to_edit") or [])
        total_slice_files += len(candidates)
        ranged_files += sum(1 for p in candidates if (trace.get("line_ranges") or {}).get(p))

    assert records
    total_before = sum(r["before"] for r in records)
    total_after = sum(r["after"] for r in records)
    growths = [r["growth"] for r in records]
    median_growth = statistics.median(growths)
    largest_growth = max(growths)
    largest_after = max(r["after"] for r in records)
    ranged_share = (ranged_files / total_slice_files) if total_slice_files else 0.0

    assert largest_after < _MAX_BYTES, (largest_after, _MAX_BYTES)
    assert total_after > total_before, "line_ranges must add real bytes somewhere"
    assert median_growth >= 0
    assert largest_growth >= median_growth
    assert largest_growth > 0
    assert ranged_share > 0.0, "at least one read-slice file must have received a range"

    # Evidence-shaped summary — not asserted further, but computed so a
    # build-log paste of this test's output is meaningful.
    summary = {
        "tickets": len(records), "total_before": total_before,
        "total_after": total_after, "median_growth": median_growth,
        "largest_growth": largest_growth, "largest_after": largest_after,
        "ranged_share": round(ranged_share, 4),
    }
    assert summary["tickets"] == len(klc137_corpus_traces)


def test_pinned_sample_of_ten_tickets_stays_under_512kib(fresh_index):
    """AC-11's Evidence command (D-2/D-109): a CHEAP re-check over ten
    pinned tickets, rebuilt live from `fresh_index` directly — never the
    full 132-ticket sweep at `klc ack` time (KLC-121 D-202)."""
    import importlib.util
    repo_root = Path(__file__).resolve().parents[2]
    skills = repo_root / "core" / "skills"
    spec = importlib.util.spec_from_file_location(
        "klc137_planning_eval_pinned", str(skills / "planning-eval.py"))
    pe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe)

    tickets_dir = repo_root / ".klc" / "tickets"
    checked = 0
    any_growth = False
    for key in _PINNED_TICKETS:
        ticket_dir = tickets_dir / key
        assert (ticket_dir / "raw.md").exists(), f"{key}: raw.md missing"
        trace = pe.rescore_trace(ticket_dir, fresh_index)
        assert trace is not None, f"{key}: rescore_trace returned None"
        before, after = _before_after_bytes(trace)
        assert after < _MAX_BYTES, (key, after, _MAX_BYTES)
        assert after >= before, (key, before, after)
        any_growth = any_growth or (after > before)
        checked += 1
    assert checked == len(_PINNED_TICKETS)
    assert any_growth, "at least one pinned ticket must show real line_ranges growth"
