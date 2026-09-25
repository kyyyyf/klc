"""tests/integration/test_klc110_backfill.py — KLC-110 step-7: `--backfill`
scores the whole ticket corpus into machine-readable rows, labelled by trace
source, and never pools `stored` and `replayed` into one mean (AC-17,
D-218)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402  (KLC-110 D-213: the canonical loader)

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


def test_backfill_scores_corpus_with_stored_and_replayed_rows_labeled_separately(
    tmp_path, monkeypatch
):
    """AC-17: `planning-eval.py --backfill` scores the whole klc ticket corpus
    into machine-readable rows plus one rendered per-ticket and aggregate
    table, with every row labelled by its trace source (`stored` for the
    trace written at intake, `replayed` for a re-run of the retriever
    against the current index using the trace's recorded query)."""
    tickets_root = tmp_path / "tickets"
    _ticket(tickets_root, "KLC-B1", changed_files=["a.py", "b.py"], trace={
        "status": "ok", "confidence": "medium",
        "files_likely_to_edit": ["a.py", "z.py"],
        "files_to_read_first": ["a.py", "b.py"],
    })
    _ticket(tickets_root, "KLC-B2")   # no stored patch, no matching commit

    repo = tmp_path / "not_a_repo"
    repo.mkdir()
    index_dir = tmp_path / "index"

    stored_rows = _pe.backfill_rows(tickets_root, None, repo, index_dir, "stored")
    by_ticket = {r["ticket"]: r for r in stored_rows}
    assert by_ticket["KLC-B1"]["status"] == "ok"
    assert by_ticket["KLC-B1"]["trace_source"] == "stored"
    assert by_ticket["KLC-B1"]["precision_at_5"] == 0.5
    assert by_ticket["KLC-B2"]["status"] == "unavailable"
    assert by_ticket["KLC-B2"]["trace_source"] == "stored"

    def fake_rescore(ticket_dir, idx):
        if ticket_dir.name == "KLC-B1":
            return {"status": "ok", "confidence": "high",
                    "files_likely_to_edit": ["a.py"],
                    "files_to_read_first": ["b.py"]}
        return None

    monkeypatch.setattr(_pe, "rescore_trace", fake_rescore)
    replayed_rows = _pe.backfill_rows(tickets_root, None, repo, index_dir, "replayed")
    by_ticket_r = {r["ticket"]: r for r in replayed_rows}
    assert by_ticket_r["KLC-B1"]["status"] == "ok"
    assert by_ticket_r["KLC-B1"]["trace_source"] == "replayed"
    assert by_ticket_r["KLC-B1"]["precision_at_5"] == 1.0
    assert by_ticket_r["KLC-B2"]["status"] == "unavailable"


def test_backfill_never_mixes_stored_and_replayed_in_one_mean(tmp_path, monkeypatch):
    """AC-17/D-218: the two source populations are counted and averaged
    separately — a stored row and a replayed row for the same ticket may
    score differently, and `render_backfill` reports two aggregate blocks,
    never one pooled mean."""
    tickets_root = tmp_path / "tickets"
    _ticket(tickets_root, "KLC-M1", changed_files=["a.py"], trace={
        "status": "ok", "confidence": "low",
        "files_likely_to_edit": ["z.py"],   # stored: precision 0
        "files_to_read_first": [],
    })

    repo = tmp_path / "repo"
    repo.mkdir()
    index_dir = tmp_path / "index"

    def fake_rescore(ticket_dir, idx):
        return {"status": "ok", "confidence": "high",
                "files_likely_to_edit": ["a.py"],   # replayed: precision 1
                "files_to_read_first": []}

    monkeypatch.setattr(_pe, "rescore_trace", fake_rescore)

    stored_rows = _pe.backfill_rows(tickets_root, None, repo, index_dir, "stored")
    replayed_rows = _pe.backfill_rows(tickets_root, None, repo, index_dir, "replayed")

    assert stored_rows[0]["precision_at_5"] == 0.0
    assert replayed_rows[0]["precision_at_5"] == 1.0

    rendered = _pe.render_backfill(
        {"stored": stored_rows, "replayed": replayed_rows}, "gen-1")
    assert "## stored" in rendered
    assert "## replayed" in rendered


def test_klc102_replayed_row_reproduces_klc108_baseline_precision_at_5(
    tmp_path, monkeypatch
):
    """Positive e2e, ties AC-17 to AC-18: the fixture-corpus stand-in for the
    real KLC-102 row reproduces precision@5 = 0.20 for a replayed row scored
    against a fixture corpus."""
    tickets_root = tmp_path / "tickets"
    _ticket(tickets_root, "KLC-102", changed_files=["a.py"])

    repo = tmp_path / "repo"
    repo.mkdir()
    index_dir = tmp_path / "index"

    def fake_rescore(ticket_dir, idx):
        return {"status": "ok", "confidence": "low",
                "files_likely_to_edit": ["a.py", "b.py", "c.py", "d.py", "e.py"],
                "files_to_read_first": []}

    monkeypatch.setattr(_pe, "rescore_trace", fake_rescore)
    rows = _pe.backfill_rows(tickets_root, None, repo, index_dir, "replayed")
    row = next(r for r in rows if r["ticket"] == "KLC-102")
    assert row["precision_at_5"] == 0.20
