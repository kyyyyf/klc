"""KLC-179 step-4 (AC-7): `scope_delta.compare` refuses to scan another
ticket's diff when HEAD is on that ticket's branch, and the gate reads the
refusal as dirty. Real temp git repos; `phase_completion._git` is wrapped as a
passthrough (never a canned return)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _count_git,
    _seed_ticket,
)


def _foreign_branch_repo(tmp_path, monkeypatch):
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _seed_ticket(clone, "KLC-179", phase="review:work", track="light",
                 affected_modules=["widgets"],
                 modules=[{"name": "widgets", "paths": ["widgets/"]}])
    _branch_with_commits(clone, "KLC-999", [
        ("gizmos/other.py", "b = 2\n", "KLC-999 step-1: add b"),
    ], branch="feature/klc-999-x")
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    return clone


def test_compare_refuses_on_foreign_branch(tmp_path, monkeypatch):
    _foreign_branch_repo(tmp_path, monkeypatch)
    import scope_delta as _sd
    calls: list = []
    real = _sd._git_changed_files
    monkeypatch.setattr(_sd, "_git_changed_files",
                        lambda root: calls.append(1) or real(root))
    delta = _sd.compare("KLC-179")
    assert "KLC-999" in delta["skipped"] and "KLC-179" in delta["skipped"]
    assert delta["actual"] == [] and delta["expansion"] == []
    assert calls == [], "the diff must never be read on a foreign branch"


def test_gate_reads_foreign_branch_as_dirty(tmp_path, monkeypatch):
    _foreign_branch_repo(tmp_path, monkeypatch)
    import scope_delta as _sd
    seen = {}
    real = _sd.compare

    def _spy(ticket, **kw):
        seen["delta"] = real(ticket, **kw)
        return seen["delta"]

    monkeypatch.setattr(_sd, "compare", _spy)
    import gate_policy as _gp
    sig = _gp.collect_signals("KLC-179", "review")
    assert "skipped" in seen["delta"]
    assert sig["scope_expansion"] is True


def test_git_failure_in_guard_is_dirty(tmp_path, monkeypatch):
    _foreign_branch_repo(tmp_path, monkeypatch)
    import phase_completion as _pc
    import scope_delta as _sd

    def _boom(args, repo=None):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(_pc, "_git", _boom)
    monkeypatch.setattr(_sd, "_git_changed_files", lambda root: [])
    delta = _sd.compare("KLC-179")
    assert delta.get("skipped")          # gate: bool(skipped) -> dirty


def test_injected_files_issue_zero_extra_git_calls(tmp_path, monkeypatch):
    _foreign_branch_repo(tmp_path, monkeypatch)
    import scope_delta as _sd
    log = _count_git(monkeypatch)
    delta = _sd.compare("KLC-179", changed_files=["widgets/a.py"])
    assert log == []
    assert not delta.get("skipped")


def test_live_path_adds_at_most_one_rev_parse(tmp_path, monkeypatch):
    _foreign_branch_repo(tmp_path, monkeypatch)
    import scope_delta as _sd
    log = _count_git(monkeypatch)
    _sd.compare("KLC-179")
    assert len(log) <= 1 and all(c[0] == "rev-parse" for c in log)
