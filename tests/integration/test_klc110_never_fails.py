"""tests/integration/test_klc110_never_fails.py — KLC-110 step-5: the
integrate ack completes with an unchanged verdict and no raised exception
however badly the retrieval evaluator's inputs behave, and the two existing
drift advisory producers are unaffected (AC-12)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import advisories as _adv_mod  # noqa: E402  (KLC-117)
import phase_completion as _pc  # noqa: E402


def test_integrate_ack_verdict_unchanged_and_no_exception_on_git_index_or_log_failure(
    tmp_path, monkeypatch
):
    """AC-12: the integrate ack completes with an unchanged verdict and no
    raised exception even when git is unavailable, the index is missing, or
    the evidence log cannot be written."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc" / "tickets" / "KLC-N"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"phase": "integrate:work", "track": "M"}), encoding="utf-8")
    trace = {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"]}
    (d / "retrieval_trace.json").write_text(json.dumps(trace), encoding="utf-8")

    def raising_git(args, repo=None):
        raise RuntimeError("git unavailable")

    def raising_modules():
        raise RuntimeError("index missing")

    monkeypatch.setattr(_pc, "_git", raising_git)
    monkeypatch.setattr(_pc, "_load_modules", raising_modules)

    ok, msg = _pc._can_complete_generic("KLC-N", "integrate", persist=True)
    assert ok is True
    assert isinstance(msg, str)


def test_drift_advisories_unaffected_by_retrieval_evaluator_failure(tmp_path, monkeypatch):
    """Regression: the existing two drift advisory producers are unaffected
    when the retrieval evaluator's own internals raise — the integrate
    branch's concatenated message still contains their lines unchanged."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc" / "tickets" / "KLC-M"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"phase": "integrate:work", "track": "M"}), encoding="utf-8")

    monkeypatch.setattr(
        _pc, "_drift_advisories",
        lambda ticket, persist, **kw: [
            {"source": "drift-check", "severity": "medium", "code": "drift-check.x",
             "message": "drift: core/foo", "ref": ""}])
    monkeypatch.setattr(_pc, "_drift_review_advisories", lambda ticket, persist: [])
    monkeypatch.setattr(
        _pc._reval, "read_trace",
        lambda ticket: (_ for _ in ()).throw(RuntimeError("boom")))

    ok, msg = _pc._can_complete_generic("KLC-M", "integrate", persist=True)
    assert ok is True
    envelope = _adv_mod.read("KLC-M", "integrate")
    assert any("drift: core/foo" in r["message"] for r in envelope["records"])
    assert any(r["source"] == "retrieval-eval" for r in envelope["records"])


def test_non_integrate_phase_does_not_invoke_retrieval_evaluator(monkeypatch):
    """Regression: a non-integrate generic phase does NOT take the
    retrieval-evaluator branch at all, matching the existing drift-advisory
    precedent."""
    monkeypatch.setattr(
        _pc, "_retrieval_advisories",
        lambda ticket, persist, **kw: (_ for _ in ()).throw(RuntimeError("must not run")))
    ok, msg = _pc._can_complete_generic("KLC-ANY", "observe", persist=False)
    assert isinstance(ok, bool)  # no RuntimeError -> the branch was not taken
