"""KLC-176 step-3 (AC-6): derived per-ticket files live in `.klc/scratch/<KEY>/`.

The retrieval trace and the build step files (brief, impl-report, review,
findings) are transient: they are written under the card root and never under
`tickets/<KEY>/`. Readers still accept the legacy ticket-dir location.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW))
sys.path.insert(0, str(_FW / "core" / "skills"))
sys.path.insert(0, str(_FW / "core" / "phases"))

import intake  # noqa: E402
import retrieval_eval  # noqa: E402

sys.path.insert(0, str(_FW / "tests"))
import test_intake_retrieval as _ir  # noqa: E402

KEY = "KLC-9177"

_PLAN = """---
ticket: KLC-9177
kind: impl-plan
---

# plan

## step-1 — foundation

- **Goal:** build foo
- **Interfaces:** `def foo() -> int`
- **Expected:** foo returns 42
- **VERIFY:** pytest
- **COMMIT:** KLC-9177 step-1: build foo
- **Affected:** src/foo.py
"""


def _intake(tmp_path, monkeypatch, key=KEY) -> Path:
    _ir._write_views(tmp_path)
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    assert _ir._run_intake(tmp_path, monkeypatch, key, _ir._QUERY) == 0
    return tmp_path / ".klc" / "tickets" / key


def test_new_ticket_writes_no_trace_or_step_files_in_ticket_dir(tmp_path, monkeypatch):
    tdir = _intake(tmp_path, monkeypatch)
    scratch = tmp_path / ".klc" / "scratch" / KEY
    assert (scratch / "retrieval_trace.json").exists()
    assert not (tdir / "retrieval_trace.json").exists()

    (tdir / "impl-plan.md").write_text(_PLAN, encoding="utf-8")
    (tdir / "spec.md").write_text("# s\n\n## Goals\n\n- g\n\n## Acceptance criteria\n\n- [ ] AC-1: x\n",
                                  encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "klc_phase_task_brief", _FW / "core" / "phases" / "task_brief.py")
    tb_phase = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tb_phase)
    assert tb_phase.run([KEY, "1"]) == 0
    assert (scratch / "build" / "step-1-brief.md").exists()
    assert (scratch / "build" / "step-1-impl-report.md").exists()
    assert not (tdir / "build" / "step-1-brief.md").exists()
    assert not (tdir / "build" / "step-1-impl-report.md").exists()

    import per_step_review as psr
    res = psr.RouteResult()
    psr._write_review(KEY, 1, res)
    assert (scratch / "build" / "step-1-review.md").exists()
    assert not (tdir / "build" / "step-1-review.md").exists()


def test_review_input_reads_scratch_then_legacy(tmp_path, monkeypatch):
    tdir = _intake(tmp_path, monkeypatch)
    import per_step_review as psr
    legacy = tdir / "build"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "step-1-brief.md").write_text("LEGACY BRIEF\n", encoding="utf-8")
    assert "LEGACY BRIEF" in psr.compose_review_input(KEY, 1)
    scratch = tmp_path / ".klc" / "scratch" / KEY / "build"
    scratch.mkdir(parents=True)
    (scratch / "step-1-brief.md").write_text("SCRATCH BRIEF\n", encoding="utf-8")
    text = psr.compose_review_input(KEY, 1)
    assert "SCRATCH BRIEF" in text and "LEGACY BRIEF" not in text


def test_read_trace_prefers_scratch_then_legacy_then_regenerates(tmp_path, monkeypatch):
    tdir = _intake(tmp_path, monkeypatch)
    scratch = tmp_path / ".klc" / "scratch" / KEY / "retrieval_trace.json"
    legacy = tdir / "retrieval_trace.json"
    assert retrieval_eval.read_trace(KEY)["status"] == "ok"

    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text(json.dumps({"status": "ok", "marker": "scratch"}), encoding="utf-8")
    legacy.write_text(json.dumps({"status": "ok", "marker": "legacy"}), encoding="utf-8")
    assert retrieval_eval.read_trace(KEY)["marker"] == "scratch"

    scratch.unlink()
    assert retrieval_eval.read_trace(KEY)["marker"] == "legacy"

    legacy.unlink()
    regenerated = retrieval_eval.read_trace(KEY)
    assert regenerated is not None and regenerated["status"] == "ok"
    assert "core/intake/validation.py" in regenerated["files_to_read_first"]


def test_unwritable_scratch_degrades_not_fails(tmp_path, monkeypatch):
    _ir._write_views(tmp_path)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KLC_CARD_ROOT", str(blocker))
    assert _ir._run_intake(tmp_path, monkeypatch, "KLC-9178", _ir._QUERY) == 0
    assert not (tmp_path / ".klc" / "tickets" / "KLC-9178" / "retrieval_trace.json").exists()
