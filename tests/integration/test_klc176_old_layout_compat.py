"""KLC-176 step-5 (AC-11): every reader still accepts the archived layout.

Copies of the real archived tickets KLC-154 and KLC-166 (old layout: _superseded/,
design/options.md + adr.md, options-lite, retrieval_trace.json, manual-checklist.md,
integrate.md, ack-advisories.json, old meta keys) are loaded through the readers
the layout change touched.

Limitation: the golden numbers skip when the local untracked .klc/tickets corpus is absent
(fresh clone, CI), so they are verified only where the archive exists.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import advisories  # noqa: E402
import handback  # noqa: E402
import metrics  # noqa: E402
import provenance  # noqa: E402
import retrieval_eval  # noqa: E402
from core.shared import paths  # noqa: E402

TICKETS = ("KLC-154", "KLC-166")


def _copy(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    for key in TICKETS:
        src = _FW / ".klc/tickets" / key
        if not src.is_dir():
            pytest.skip(f"{key} is not present in this checkout")
        shutil.copytree(src, tmp_path / ".klc/tickets" / key)
    return tmp_path


def test_archived_klc154_and_klc166_copies_still_load(tmp_path, monkeypatch):
    _copy(tmp_path, monkeypatch)
    # rollup runs over both old metas
    assert metrics.cmd_rollup(argparse.Namespace()) in (0, None)
    out = json.loads((tmp_path / ".klc/knowledge/process-metrics.json").read_text("utf-8"))
    assert out
    for key in TICKETS:
        tdir = paths.klc_ticket_dir(key)
        # advisories: legacy per-phase file or the new one, never raising
        for phase in ("discovery", "design", "integrate"):
            env = advisories.read(key, phase)
            assert env is None or isinstance(env, dict)
            disp = advisories.for_display(key, phase)
            assert disp is None or isinstance(disp, dict)
        # findings: old per-kind files still load
        loaded = handback.load_ticket_findings(tdir)
        assert loaded is not None
        # the trace in the ticket directory is still read
        if (tdir / "retrieval_trace.json").exists():
            assert retrieval_eval.read_trace(key) is not None
        # design reader falls back to design/options.md
        assert paths.design_doc_path(key) == tdir / "design" / "options.md"
        assert paths.design_doc_path(key).exists()
        # provenance runs over the old layout
        assert isinstance(provenance.report(key), dict)


def test_superseded_snapshot_is_skipped_by_provenance(tmp_path, monkeypatch):
    _copy(tmp_path, monkeypatch)
    key = "KLC-154"
    before = sorted(it.file for it in provenance._scoped_items(key))
    snap = paths.klc_ticket_dir(key) / "_superseded" / "20260101T000000Z" / "design"
    snap.mkdir(parents=True)
    (snap / "options.md").write_text(
        "> [!FACT F-9001] src=x\n> a frozen fact\n", encoding="utf-8")
    after = sorted(it.file for it in provenance._scoped_items(key))
    assert after == before


# Values read ONCE from the real archived tickets (their data is frozen, and the
# retrieval figures come from the untouched legacy metas). They pin "the same
# result as before" without needing main's code at hand.
_GOLDEN_ADVISORY_COUNTS = {
    "KLC-154": {"discovery": 20, "design": 9, "integrate": 2},
    "KLC-166": {"discovery": 31, "design": 7, "integrate": 1},
}
_GOLDEN_PROVENANCE_ARTEFACTS = {"KLC-154": 2, "KLC-166": 1}


def test_archived_copies_give_the_recorded_results(tmp_path, monkeypatch):
    _copy(tmp_path, monkeypatch)
    for key in TICKETS:
        for phase, n in _GOLDEN_ADVISORY_COUNTS[key].items():
            assert len(advisories.read(key, phase)["records"]) == n, (key, phase)
        rep = provenance.report(key)
        assert rep["per_artefact"] and len(rep["per_artefact"]) == \
            _GOLDEN_PROVENANCE_ARTEFACTS[key], key
        assert rep["contradicted_assumed"] == 0
        assert len(handback.load_ticket_findings(paths.klc_ticket_dir(key))) == 2
    metrics.cmd_rollup(argparse.Namespace())
    out = json.loads((tmp_path / ".klc/knowledge/process-metrics.json").read_text("utf-8"))
    assert out["tickets_total"] == 2
    m = out["per_track"]["M"]
    assert m["tickets"] == 2
    assert m["cycle_time_sec_median"] == 83700.5
    assert m["review_passes_per_ticket"]["actual"] == 5.0
    assert m["tokens_by_phase"]["build"]["samples"] == 5
    r = m["retrieval"]
    assert r["tickets_scored"] == 2 and r["zero_precision_at_5_tickets"] == ["KLC-154"]
    assert abs(r["precision_at_5_mean"] - 0.2) < 1e-9
    assert out["per_confidence"]["medium"]["tickets"] == 2
    assert out["per_confidence"]["no_record"]["tickets"] == 0
