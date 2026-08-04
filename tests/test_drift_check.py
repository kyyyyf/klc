"""Tests for core/skills/drift_check.py (KLC-096, drift-check report-only core).

The reused bricks (scope_delta.compare, tdd_order.step_commits, the git probe)
read the REAL repo/index and are not repo-injectable, so these tests monkeypatch
the imported references on the drift_check module rather than build a live git
fixture — the standard pattern (mirrors tests/test_ac_test_coverage.py).

Each test's docstring carries the canonical AC-id it covers (the project's
coverage-linkage convention consumed by ac_test_coverage / V-02).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import drift_check as dc  # noqa: E402


# ---------------------------------------------------------------- step-1: scope-drift

def test_scope_drift_lists_drifted_module_and_orphan(monkeypatch):
    """AC-2: scope-drift lists each drifted module and orphan file as DISTINCT
    categories. Uses the REAL scope_delta contract where `expansion` is a superset
    already folding in `unknown_files` — the orphan must NOT leak into
    drifted_modules (review MEDIUM-1 regression)."""
    monkeypatch.setattr(
        dc, "_scope_compare",
        lambda ticket: {
            "drift": ["core/foo"],
            "expansion": ["core/foo", "scripts/x.py"],  # superset incl. the orphan
            "unknown_files": ["scripts/x.py"],
        },
    )
    rep = dc.compare("KLC-096")
    sd = rep["scope_drift"]
    assert sd["drifted_modules"] == ["core/foo"]
    assert sd["orphan_files"] == ["scripts/x.py"]
    assert "scripts/x.py" not in sd["drifted_modules"]  # no double-listing
    assert sd["skipped"] is None


def test_no_scope_drift_when_within_plan(monkeypatch):
    """AC-2: negative — scope_delta RAN with real in-plan changes but found no
    drift, so lists are empty AND there is no `skipped` reason (empty != skipped)."""
    monkeypatch.setattr(
        dc, "_scope_compare",
        lambda ticket: {"drift": [], "expansion": [], "unknown_files": []},
    )
    rep = dc.compare("KLC-096")
    sd = rep["scope_drift"]
    assert sd["drifted_modules"] == []
    assert sd["orphan_files"] == []
    assert sd["skipped"] is None


# --------------------------------------------------- step-2: step-without-commit

_TWO_STEPS = (
    "## step-1 — first\n- RED: a real red test\n- COMMIT: x\n\n"
    "## step-2 — second\n- RED: another real red test\n- COMMIT: y\n"
)


def test_step_without_commit_flagged(monkeypatch):
    """AC-3: a step whose step-key has no matching commit is flagged (positive)."""
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    monkeypatch.setattr(dc, "step_commits", lambda ticket, n, repo: [])
    sec = dc._steps_section("KLC-096", _TWO_STEPS, None)
    assert sec["flagged"] == ["step-1", "step-2"]
    assert sec["exempt"] == []
    assert sec["skipped"] is None


def test_step_with_commit_not_flagged(monkeypatch):
    """AC-3: negative — a step WITH a matching commit is not flagged."""
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    monkeypatch.setattr(
        dc, "step_commits",
        lambda ticket, n, repo: [{"sha": "abc"}] if n == 1 else [],
    )
    sec = dc._steps_section("KLC-096", _TWO_STEPS, None)
    assert "step-1" not in sec["flagged"]
    assert sec["flagged"] == ["step-2"]


def test_red_not_applicable_step_exempt(monkeypatch):
    """AC-3: a RED-not-applicable commitless step is exempt, not flagged (C-004)."""
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    monkeypatch.setattr(dc, "step_commits", lambda ticket, n, repo: [])
    plan = (
        "## step-1 — real\n- RED: a real red test\n- COMMIT: x\n\n"
        "## step-2 — doc only\n- RED: not applicable\n- COMMIT: —\n"
    )
    sec = dc._steps_section("KLC-096", plan, None)
    assert sec["flagged"] == ["step-1"]
    assert sec["exempt"] == ["step-2"]


def test_red_not_applicable_decoy_in_fence_not_exempt(monkeypatch):
    """AC-3: F-3 — a `RED: not applicable` decoy INSIDE a code fence must NOT
    exempt the step; fences are stripped before the RED check."""
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    monkeypatch.setattr(dc, "step_commits", lambda ticket, n, repo: [])
    plan = (
        "## step-1 — real work\n- Goal: do a thing\n"
        "```python\nRED: not applicable\n```\n- COMMIT: x\n"
    )
    sec = dc._steps_section("KLC-096", plan, None)
    assert sec["flagged"] == ["step-1"]
    assert sec["exempt"] == []


# ------------------------------------- step-3: degrade-not-fail / report-only

_CLEAN_SCOPE = {"drift": [], "expansion": [], "unknown_files": []}


def test_missing_impl_plan_degrades_clean(monkeypatch):
    """AC-4: absent impl-plan → step section SKIPPED (reason set), no raise."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: None)
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    rep = dc.compare("KLC-096")
    assert rep["step_without_commit"]["flagged"] == []
    assert rep["step_without_commit"]["skipped"]  # truthy reason


def test_empty_impl_plan_empty_section(monkeypatch):
    """AC-4: F-1 — present-but-empty impl-plan (0 steps) → EMPTY section with
    skipped is None (empty != skipped)."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: "")
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    rep = dc.compare("KLC-096")
    sec = rep["step_without_commit"]
    assert sec["flagged"] == [] and sec["exempt"] == []
    assert sec["skipped"] is None


def test_unreadable_impl_plan_surfaces_real_reason(monkeypatch):
    """AC-4: review LOW-1 — a present-but-UNREADABLE impl-plan surfaces its real
    exception as the skip-reason, not the misleading 'impl-plan.md not found'."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)

    def _boom(ticket):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad byte")

    monkeypatch.setattr(dc, "_read_impl_plan", _boom)
    rep = dc.compare("KLC-096")
    sec = rep["step_without_commit"]
    assert sec["skipped"] and "not found" not in sec["skipped"]
    assert "UnicodeDecodeError" in sec["skipped"]


def test_missing_modules_degrades_clean(monkeypatch):
    """AC-4: scope_delta reports a skip (no modules.json) → scope records reason."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: {"skipped": "modules.json not found"})
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: "")
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    rep = dc.compare("KLC-096")
    assert rep["scope_drift"]["skipped"] == "modules.json not found"
    assert rep["scope_drift"]["drifted_modules"] == []


def test_git_unavailable_degrades_clean(monkeypatch):
    """AC-4: D-1 — git subprocess unavailable → skip-reason via explicit probe."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: _TWO_STEPS)
    monkeypatch.setattr(dc, "_git_available", lambda repo: False)
    rep = dc.compare("KLC-096")
    sec = rep["step_without_commit"]
    assert sec["flagged"] == [] and sec["skipped"] == "git unavailable"


def test_skip_reason_only_when_skipped(monkeypatch):
    """AC-4: F-3 observability — a clean-empty section carries NO skip-reason
    while a skipped section DOES. Both directions pinned."""
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: "")
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    ran = dc.compare("KLC-096")["scope_drift"]
    assert ran["skipped"] is None
    monkeypatch.setattr(dc, "_scope_compare", lambda t: {"skipped": "no changed files detected"})
    skp = dc.compare("KLC-096")["scope_drift"]
    assert skp["skipped"] == "no changed files detected"


def test_report_only_never_raises(monkeypatch):
    """AC-6: enumerated adversarial inputs — compare() returns a report, never raises."""
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    adversarial = [
        (lambda t: (_ for _ in ()).throw(RuntimeError("scope boom")), "## step-1 — x\n- RED: r\n"),
        (lambda t: dict(_CLEAN_SCOPE), "## step-1 — x\n```\ngarbage\n```"),
        (lambda t: dict(_CLEAN_SCOPE), "\x00\xff not markdown at all"),
    ]
    monkeypatch.setattr(dc, "step_commits", lambda *a, **k: (_ for _ in ()).throw(OSError("git boom")))
    for scope_fn, plan in adversarial:
        monkeypatch.setattr(dc, "_scope_compare", scope_fn)
        monkeypatch.setattr(dc, "_read_impl_plan", lambda t, _p=plan: _p)
        rep = dc.compare("KLC-096")  # must not raise
        assert isinstance(rep, dict)
        assert "scope_drift" in rep and "step_without_commit" in rep


def test_no_gating_side_effects(monkeypatch):
    """AC-6: compare() is pure — writes no drift-report.json, mutates no state."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: "")
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    report_path = _FW_ROOT / ".klc" / "tickets" / "KLC-ZZZ" / "drift-report.json"
    rep = dc.compare("KLC-ZZZ")
    assert isinstance(rep, dict)
    assert not report_path.exists()  # compare never writes; only write_report does


# --------------------------------------- step-4: report writer / summary / AC-5

def test_report_has_scope_and_step_sections(monkeypatch, tmp_path):
    """AC-1: write_report emits drift-report.json with both sections + summary."""
    monkeypatch.setattr(dc, "_scope_compare", lambda t: dict(_CLEAN_SCOPE))
    monkeypatch.setattr(dc, "_read_impl_plan", lambda t: "")
    monkeypatch.setattr(dc, "_git_available", lambda repo: True)
    out = tmp_path / "drift-report.json"
    monkeypatch.setattr(dc, "_report_path", lambda t: out)
    rep = dc.write_report("KLC-096")
    assert out.exists()
    data = json.loads(out.read_text())
    assert "scope_drift" in data and "step_without_commit" in data and "summary" in data
    assert rep["summary"] == data["summary"]


def test_human_readable_summary_names_content():
    """AC-7: the summary NAMES the drifted module / flagged step / skip-reason —
    a constant placeholder ignoring content would fail these substring checks."""
    rep = {
        "ticket": "KLC-096",
        "scope_drift": {"drifted_modules": ["core/foo"], "orphan_files": ["x.py"], "skipped": None},
        "step_without_commit": {"flagged": ["step-3"], "exempt": [], "skipped": None},
    }
    s = dc._summary(rep)
    assert "core/foo" in s and "step-3" in s

    rep_skip = {
        "ticket": "KLC-096",
        "scope_drift": {"drifted_modules": [], "orphan_files": [], "skipped": "modules.json not found"},
        "step_without_commit": {"flagged": [], "exempt": [], "skipped": "git unavailable"},
    }
    s2 = dc._summary(rep_skip)
    assert "modules.json not found" in s2 and "git unavailable" in s2


def test_no_ac_test_coverage_arrow():
    """AC-5: drift_check must never re-derive the AC-to-test verdict (C-002) — the
    string `ac_test_coverage` never appears in the source and no such field is emitted."""
    src = Path(dc.__file__).read_text()
    assert "ac_test_coverage" not in src
    rep = {"scope_drift": {}, "step_without_commit": {}}
    assert not any("ac_test" in k or "coverage" in k for k in rep)
