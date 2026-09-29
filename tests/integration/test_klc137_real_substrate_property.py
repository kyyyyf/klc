"""KLC-137 step-4 — AC-13 (second clause): every stored ticket's rebuilt
trace satisfies AC-5/AC-6 on the same `fresh_index` mirror (D-108). No
bootstrap exemption and no git-history read — the corpus is the ticket
state directory itself (`.klc/tickets/*/raw.md`, read only).
"""
from __future__ import annotations

from pathlib import Path


def test_every_stored_ticket_query_rebuilt_trace_satisfies_ac5_and_ac6_on_the_scratch_copy(
    fresh_index, klc137_corpus_traces
):
    """AC-13, second clause: for every stored ticket's rebuilt trace, each
    `line_ranges` key is one of the two candidate lists, at most 3 unique
    entries per file, `start <= end` for every entry, and the entry's
    symbol name is present on line `start` of the mirror file — proving the
    emitted ranges are not stale against their own substrate. At least one
    trace must carry a non-empty map (non-vacuity)."""
    assert klc137_corpus_traces, "klc137_corpus_traces must not be empty"
    mirror_root = fresh_index.parent.parent
    any_non_empty = False
    file_cache: dict[str, list[str]] = {}

    for key, trace in klc137_corpus_traces.items():
        # KLC-137 step-7 review-fix (external LOW): the key must always be
        # present (AC-6/AC-7 — {} for a status != "ok" trace, never absent) —
        # a hard assertion, not a silent skip that would pass on a trace that
        # lost the key entirely.
        assert "line_ranges" in trace, (key, "trace is missing the line_ranges key")
        line_ranges = trace["line_ranges"]
        assert isinstance(line_ranges, dict), (key, "line_ranges must be a dict")
        candidates = set(trace.get("files_to_read_first") or []) | \
            set(trace.get("files_likely_to_edit") or [])
        for path, entries in line_ranges.items():
            any_non_empty = any_non_empty or bool(entries)
            assert path in candidates, (key, path, "line_ranges key outside both candidate lists")
            seen = set()
            for e in entries:
                uniq = (e["symbol"], e["kind"], e["start"], e["end"])
                assert uniq not in seen, (key, path, "duplicate entry after dedup")
                seen.add(uniq)
                assert e["start"] <= e["end"], (key, path, e)
                full_path = mirror_root / path
                if path not in file_cache:
                    # KLC-137 step-7 review-fix (external LOW): split on '\n'
                    # only — str.splitlines() also splits on U+2028/U+0085/\x0c
                    # etc., which ast/ast-grep do not treat as line breaks, so
                    # it can silently misalign `start` against the wrong text.
                    try:
                        file_cache[path] = full_path.read_text(encoding="utf-8").split("\n")
                    except OSError:
                        file_cache[path] = []
                lines = file_cache[path]
                assert 1 <= e["start"] <= len(lines), (key, path, e)
                assert e["symbol"] in lines[e["start"] - 1], (
                    key, path, e, lines[e["start"] - 1])
            assert len(entries) <= 3, (key, path, len(entries))

    assert any_non_empty, "at least one stored ticket's trace must carry a non-empty line_ranges"
