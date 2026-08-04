"""Tests for the integrate drift-check advisory wiring (KLC-098).

Surface-only, degrade-not-fail: a dedicated `phase_id == "integrate"` branch in
`phase_completion._can_complete_generic`, placed BEFORE the empty-outputs early return
(integrate has outputs: []), returns advisory lines from drift_check — never blocks.
Tests monkeypatch the imported brick references on phase_completion (the standard
pattern), so no live git/drift_check run is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase_completion as pc  # noqa: E402


# ----------------------------------------------- step-1: dedicated integrate branch

def test_integrate_appends_drift_advisory(monkeypatch):
    """AC-1: the integrate branch (before the empty-outputs early return) returns the
    drift advisory lines from _drift_advisories."""
    monkeypatch.setattr(pc, "_drift_advisories", lambda ticket, persist: ["drift: core/foo"])
    ok, msg = pc._can_complete_generic("KLC-ANY", "integrate", persist=False)
    assert ok is True
    assert "drift: core/foo" in msg


def test_non_integrate_generic_phase_unaffected(monkeypatch):
    """AC-1/AC-6: a non-integrate generic phase does NOT take the drift branch."""
    monkeypatch.setattr(
        pc, "_drift_advisories",
        lambda ticket, persist: (_ for _ in ()).throw(RuntimeError("must not run")),
    )
    # observe is a generic phase; whatever it returns, the drift branch must not fire.
    ok, msg = pc._can_complete_generic("KLC-ANY", "observe", persist=False)
    assert isinstance(ok, bool)  # no RuntimeError → drift branch was not taken


# ------------------------------------------------ step-2: committed-diff scoping

def _rep(mods, orphans, skipped=None):
    return {
        "scope_drift": {"drifted_modules": mods, "orphan_files": orphans, "skipped": skipped},
        "step_without_commit": {"flagged": [], "exempt": [], "skipped": None},
    }


def test_committed_unplanned_module_surfaces(monkeypatch):
    """AC-3 positive: a committed unplanned module surfaces."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep(["core/foo"], []))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: ({"core/foo"}, set()))
    lines = pc._drift_advisories("KLC-X", False)
    assert any("core/foo" in l for l in lines)


def test_committed_wip_not_false_drift(monkeypatch):
    """AC-3 negative: an uncommitted WIP module is NOT surfaced (name∩name)."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep(["core/foo"], []))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    lines = pc._drift_advisories("KLC-X", False)
    assert not any("core/foo" in l for l in lines)


def test_committed_orphan_wip_not_surfaced(monkeypatch):
    """AC-3 (review F-1): an uncommitted orphan-file WIP is NOT surfaced (path∩path)."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep([], ["scripts/x.py"]))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    lines = pc._drift_advisories("KLC-X", False)
    assert not any("scripts/x.py" in l for l in lines)


def test_drifted_modules_are_names_not_paths(monkeypatch):
    """AC-3 (review D-2): the module arrow intersects NAME∩NAME — a committed PATH is
    resolved to its module NAME before the intersection, not compared as a path."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep(["core/foo"], []))
    # committed provides the module NAME core/foo (resolved from core/foo/bar.py)
    monkeypatch.setattr(pc, "_committed", lambda repo=None: ({"core/foo"}, {"core/foo/bar.py"}))
    lines = pc._drift_advisories("KLC-X", False)
    assert any("core/foo" in l for l in lines)


def test_merge_base_unavailable_degrades(monkeypatch):
    """AC-3 / C-001: no merge-base → empty committed set (surface nothing), never raises."""
    monkeypatch.setattr(pc, "_git", lambda args, repo=None: "")  # merge-base → ""
    mods, paths = pc._committed(None)
    assert mods == set() and paths == set()


# ---------------------------------- step-3: degrade-not-fail / never-block / persist

def test_drift_check_raises_degrades(monkeypatch):
    """AC-4: drift_check raising → exactly one degraded note, never raises."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: (_ for _ in ()).throw(RuntimeError("boom")))
    lines = pc._drift_advisories("KLC-X", False)
    assert len(lines) == 1 and "skipped" in lines[0].lower()


def test_drift_check_absent_degrades(monkeypatch):
    """AC-4: an unavailable drift_check (AttributeError) degrades to one note."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: (_ for _ in ()).throw(AttributeError("gone")))
    lines = pc._drift_advisories("KLC-X", False)
    assert lines and "skipped" in lines[0].lower()


def test_never_blocks(monkeypatch):
    """AC-6: across drift present / error, the integrate completion is always True."""
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    for fn in (lambda t: _rep(["x"], []), lambda t: (_ for _ in ()).throw(RuntimeError())):
        monkeypatch.setattr(pc._drift, "compare", fn)
        ok, _ = pc._can_complete_generic("KLC-X", "integrate", persist=False)
        assert ok is True


def test_probe_is_read_only(monkeypatch):
    """AC-2: a persist=False probe never calls write_report (writes nothing)."""
    calls = []
    monkeypatch.setattr(pc._drift, "write_report", lambda t, **k: calls.append(t) or _rep([], []))
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep([], []))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    pc._drift_advisories("KLC-X", False)
    assert calls == []


def test_persist_writes_only_report(monkeypatch):
    """AC-2/AC-7: persist=True writes the report via write_report (the only writer)."""
    calls = []
    monkeypatch.setattr(pc._drift, "write_report", lambda t, **k: calls.append(t) or _rep([], []))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    pc._drift_advisories("KLC-X", True)
    assert calls == ["KLC-X"]


def test_persists_drift_report_json(monkeypatch):
    """AC-7: on a persist run, the drift report is persisted (write_report invoked)."""
    calls = []
    monkeypatch.setattr(pc._drift, "write_report", lambda t, **k: calls.append(t) or _rep([], []))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    pc._drift_advisories("KLC-X", True)
    assert "KLC-X" in calls


def test_scope_skipped_names_reason(monkeypatch):
    """AC-4: a scope `skipped` section is NAMED, not shown as an empty 'no drift'."""
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep([], [], skipped="modules.json not found"))
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    lines = pc._drift_advisories("KLC-X", False)
    assert any("modules.json not found" in l for l in lines)


# ------------------------------------------------------ step-4: track-scaling

def test_track_scaling_xs_skips(monkeypatch):
    """AC-5: XS → the advisory is skipped entirely (drift not even computed)."""
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "XS", "risk_tags": []})
    monkeypatch.setattr(pc._drift, "compare",
                        lambda t: (_ for _ in ()).throw(AssertionError("must not run on XS")))
    assert pc._drift_advisories("KLC-X", False) == []


def test_track_scaling_s_cascade_on_signal(monkeypatch):
    """AC-5: S cascades — runs with a coordination signal, skipped without one."""
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    ran = []
    monkeypatch.setattr(pc._drift, "compare", lambda t: ran.append(1) or _rep([], []))
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "S", "risk_tags": ["coordination"]})
    pc._drift_advisories("KLC-X", False)
    assert ran == [1]  # ran on S WITH signal
    ran.clear()
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "S", "risk_tags": []})
    assert pc._drift_advisories("KLC-X", False) == []  # skipped on S WITHOUT signal
    assert ran == []


def test_track_scaling_ml_full(monkeypatch):
    """AC-5: M/L → the advisory runs full."""
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    ran = []
    monkeypatch.setattr(pc._drift, "compare", lambda t: ran.append(1) or _rep([], []))
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "M", "risk_tags": []})
    pc._drift_advisories("KLC-X", False)
    assert ran == [1]


def test_probe_restores_meta_if_brick_migrates(monkeypatch, tmp_path):
    """AC-2: a persist=False probe leaves meta byte-identical even if a downstream brick
    (drift_check.compare → scope_delta.compare → read_meta) migrates it as a side effect —
    so `klc remind` / gate-policy stay read-only. Regression from the full suite."""
    meta = tmp_path / "meta.json"
    meta.write_bytes(b'{"ticket": "KLC-X", "phase": "integrate"}')
    monkeypatch.setattr(pc, "klc_ticket_meta_file", lambda t: meta)
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "M", "risk_tags": []})

    def _compare_migrates(t):
        meta.write_bytes(b'{\n  "ticket": "KLC-X",\n  "phase": "integrate"\n}')  # side-effect
        return _rep([], [])

    monkeypatch.setattr(pc._drift, "compare", _compare_migrates)
    pc._drift_advisories("KLC-X", False)  # read-only probe
    assert meta.read_bytes() == b'{"ticket": "KLC-X", "phase": "integrate"}'  # restored


def test_malformed_track_does_not_raise(monkeypatch):
    """AC-4/C-002 (review MEDIUM): a malformed meta track (non-string) must NOT raise
    past the never-raise guarantee — the track-scale decision fails open (runs)."""
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": 3, "risk_tags": []})
    monkeypatch.setattr(pc, "_committed", lambda repo=None: (set(), set()))
    monkeypatch.setattr(pc._drift, "compare", lambda t: _rep([], []))
    # must not raise (AttributeError from 3.strip() would violate C-002)
    result = pc._drift_advisories("KLC-X", False)
    assert isinstance(result, list)


def test_committed_includes_shared_memberships(monkeypatch):
    """Codex P2: a committed SHARED file (primary_module=None) contributes its member
    modules to the committed set, so shared-file drift is not suppressed."""
    monkeypatch.setattr(pc, "_git",
                        lambda args, repo=None: "base" if args[0] == "merge-base" else "core/util.py")
    monkeypatch.setattr(pc, "_load_modules", lambda: {"modules": []})
    monkeypatch.setattr(pc._mm, "file_to_module",
                        lambda p, md: {"primary_module": None, "member_of": ["core/a", "core/b"], "is_shared": True})
    mods, paths = pc._committed()
    assert mods == {"core/a", "core/b"} and "core/util.py" in paths


def test_committed_runs_git_from_project_root(monkeypatch):
    """Codex P2: the git probes run from PROJECT_ROOT, not the caller's cwd."""
    seen = []
    monkeypatch.setattr(pc, "_git", lambda args, repo=None: (seen.append(repo), "")[1])
    pc._committed()
    assert seen and all(r is not None for r in seen)
