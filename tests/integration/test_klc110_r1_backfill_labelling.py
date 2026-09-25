"""tests/integration/test_klc110_r1_backfill_labelling.py — KLC-110 review
round 1, step-11a (MEDIUM, AC-17): `backfill_rows()` must carry
`derivation_confidence` (AC-17 requires it explicitly), on both the scored
and the unavailable row shape, and `render_backfill()` must render it as a
column."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402

_pe = _reval.load_planning_eval()


def _ticket(tickets_root, key, *, changed_files=None, trace=None):
    d = tickets_root / key
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{}", encoding="utf-8")
    if changed_files is not None:
        (d / "changed_files.txt").write_text("\n".join(changed_files) + "\n",
                                             encoding="utf-8")
    if trace is not None:
        (d / "retrieval_trace.json").write_text(json.dumps(trace), encoding="utf-8")
    return d


def test_ac17_backfill_row_carries_derivation_confidence_on_both_shapes(tmp_path):
    """AC-17: the row explicitly requires `derivation_confidence` — present
    on a scored (`status: ok`) row AND on an unavailable row, using the
    SAME authoritative/best-effort rule `build_report` already uses."""
    tickets_root = tmp_path / "tickets"
    _ticket(tickets_root, "KLC-B1", changed_files=["a.py"], trace={
        "status": "ok", "confidence": "medium",
        "files_likely_to_edit": ["a.py"], "files_to_read_first": []})
    _ticket(tickets_root, "KLC-B2")   # no stored patch, no matching commit -> unavailable

    repo = tmp_path / "not_a_repo"
    repo.mkdir()
    index_dir = tmp_path / "index"

    rows = _pe.backfill_rows(tickets_root, None, repo, index_dir, "stored")
    by_ticket = {r["ticket"]: r for r in rows}
    assert by_ticket["KLC-B1"]["derivation_confidence"] == "authoritative"
    assert by_ticket["KLC-B2"]["derivation_confidence"] == "best-effort"


def test_ac17_render_backfill_includes_a_derivation_confidence_column(tmp_path):
    rows = [{"ticket": "KLC-X", "trace_source": "stored", "status": "ok",
            "confidence": "medium", "derivation_source": "stored-patch",
            "derivation_confidence": "authoritative",
            "precision_at_5": 1.0, "recall_at_10": 1.0}]
    rendered = _pe.render_backfill({"stored": rows}, "gen-1")
    assert "derivation_confidence" in rendered
    assert "authoritative" in rendered


def test_ac17_derivation_confidence_shares_the_one_rule_build_report_uses():
    """The literal rule (`'authoritative' if kind == 'stored-patch' else
    'best-effort'`) is not duplicated — both `backfill_rows` and
    `build_report`'s per-ticket loop route through the SAME
    `derivation_confidence` helper."""
    assert _pe.derivation_confidence("stored-patch") == "authoritative"
    assert _pe.derivation_confidence("git-log-grep") == "best-effort"
    assert _pe.derivation_confidence("none") == "best-effort"
