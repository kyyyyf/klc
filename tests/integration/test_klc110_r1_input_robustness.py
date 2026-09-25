"""tests/integration/test_klc110_r1_input_robustness.py — KLC-110 review
round 1, step-9b (MEDIUM, AC-11/AC-12): a `status:"ok"` trace with a
wrong-typed candidate field must degrade with a SPECIFIC, attributable
reason instead of raising TypeError deep inside `rank_metrics` (where the
only observer left is the outer surface-only exception guard in
`phase_completion.py`, which can only report a generic 'degraded —
TypeError' line with no field name). A retrieval_trace.json larger than the
512 KiB size guard must never even be parsed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402


def test_ac11_wrong_typed_candidate_field_degrades_with_specific_reason_not_typeerror():
    """AC-11/AC-12: `files_likely_to_edit` present as an int (not a list of
    strings) degrades to `status: unavailable` with a reason naming the
    field — `evaluate()` never lets a TypeError reach its own caller."""
    trace = {"status": "ok", "confidence": "low", "files_likely_to_edit": 5}
    rec = _reval.evaluate(trace, set(), {"a.py"})
    assert rec["status"] == "unavailable"
    assert "files_likely_to_edit" in rec["reason"]
    assert "not a list of strings" in rec["reason"]


def test_ac11_list_with_a_non_string_element_also_degrades_with_specific_reason():
    """The same guard catches a list whose ELEMENTS are wrong-typed (e.g. a
    trace that recorded module dicts instead of path strings), not only a
    field that is not a list at all."""
    trace = {"status": "ok", "confidence": "low",
             "files_to_read_first": ["a.py", {"not": "a string"}]}
    rec = _reval.evaluate(trace, set(), {"a.py"})
    assert rec["status"] == "unavailable"
    assert "files_to_read_first" in rec["reason"]
    assert "not a list of strings" in rec["reason"]


def test_ac11_none_and_empty_list_fields_still_score_normally():
    """Regression: a trace with an absent (None) field or a genuinely empty
    candidate list is NOT a type violation — it scores normally through the
    existing empty-candidate convention (AC-6)."""
    trace = {"status": "ok", "confidence": "low",
             "files_likely_to_edit": [], "files_to_read_first": None}
    rec = _reval.evaluate(trace, set(), {"a.py"})
    assert rec["status"] == "ok"
    assert rec["files_likely_to_edit"]["precision"] is None
    assert rec["files_likely_to_edit"]["candidates"] == 0


def test_ac12_oversized_trace_file_is_never_parsed(tmp_path, monkeypatch):
    """AC-12: a `retrieval_trace.json` over the 512 KiB size guard degrades
    read_trace() to None WITHOUT the file ever being parsed — bounding the
    read+parse cost even for a pathological/runaway trace file."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-BIG"
    tdir.mkdir(parents=True)
    huge = {"status": "ok", "confidence": "low",
            "files_likely_to_edit": ["a.py" * 1, "pad" * 200000]}
    text = json.dumps(huge)
    assert len(text.encode("utf-8")) > _reval._MAX_TRACE_BYTES
    (tdir / "retrieval_trace.json").write_text(text, encoding="utf-8")

    assert _reval.read_trace("KLC-BIG") is None


def test_ac12_trace_file_at_or_under_the_size_guard_parses_normally(tmp_path, monkeypatch):
    """A small, well-formed trace under the guard still reads normally."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-SMALL"
    tdir.mkdir(parents=True)
    small = {"status": "ok", "confidence": "low", "files_likely_to_edit": ["a.py"]}
    (tdir / "retrieval_trace.json").write_text(json.dumps(small), encoding="utf-8")

    trace = _reval.read_trace("KLC-SMALL")
    assert trace is not None
    assert trace["status"] == "ok"
