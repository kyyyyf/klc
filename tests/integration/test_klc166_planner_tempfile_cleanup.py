"""KLC-166 step-2 — AC-6: `handback._run_planner`'s temporary diff file
lives under the system temporary directory (never the project tree or
`.klc/tickets`) and is removed in a `finally` on EVERY return path,
including a raised `subprocess.TimeoutExpired` or `OSError`.

The two failure tests raise only for the `review.py` argv and pass every
`git` call through to the real subprocess (D-008): a fake that raised for
`git` too would be swallowed by `phase_completion._git`'s own
never-raises contract, no temp file would ever exist, and the test would
pass vacuously.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import handback  # noqa: E402

from _klc128_fixtures import _bare_and_clone, _branch_with_commits, _seed_ticket  # noqa: E402

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def _seed_real_project(clone: Path, ticket: str, **kw) -> Path:
    tdir = _seed_ticket(clone, ticket, **kw)
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return tdir


def _seed_with_live_range(tmp_path: Path, ticket: str) -> Path:
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch=f"feature/{ticket.lower()}-add-a-widget")
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    return clone


def _track_mkstemp(monkeypatch) -> list:
    """Record every path `_run_planner`'s `tempfile.mkstemp` creates, via a
    passthrough to the real `mkstemp` (never a canned path)."""
    paths: list = []
    real_mkstemp = tempfile.mkstemp

    def _wrapped(*a, **kw):
        fd, name = real_mkstemp(*a, **kw)
        paths.append(name)
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", _wrapped)
    return paths


def test_temporary_diff_file_is_gone_after_a_successful_plan_and_never_lived_under_the_project_tree(
    tmp_path, monkeypatch
):
    """AC-6: a successful real `_run_planner` run removes its temp file, and
    that file was never under `project_root()` or `.klc/tickets` in the
    first place."""
    ticket = "KLC-971"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    paths = _track_mkstemp(monkeypatch)

    result = handback._run_planner(ticket)
    assert result, getattr(result, "reason", "")
    assert len(paths) == 1
    temp_path = Path(paths[0])
    assert not temp_path.exists()
    assert not str(temp_path).startswith(str(clone))


def test_temporary_diff_file_is_gone_after_a_forced_timeout(tmp_path, monkeypatch):
    """AC-6: `review.py` raising `subprocess.TimeoutExpired` still removes
    the temp file — the `finally` cleanup must not depend on a normal
    return."""
    ticket = "KLC-972"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    paths = _track_mkstemp(monkeypatch)

    real_run = subprocess.run
    existed_during_call = []

    def _raise_for_review_py(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            diff_file = Path(argv[argv.index("--diff") + 1])
            existed_during_call.append(diff_file.exists())
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 0))
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _raise_for_review_py)

    with pytest.raises(subprocess.TimeoutExpired):
        handback._run_planner(ticket)

    assert existed_during_call == [True]
    assert len(paths) == 1
    assert not Path(paths[0]).exists()


def test_temporary_diff_file_is_gone_after_an_oserror(tmp_path, monkeypatch):
    """AC-6: `review.py` raising `OSError` still removes the temp file —
    operator ruling on test-plan-review D-1 (OSError gets its own cleanup
    test, not just AC-5's note-text coverage)."""
    ticket = "KLC-973"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    paths = _track_mkstemp(monkeypatch)

    real_run = subprocess.run
    existed_during_call = []

    def _raise_for_review_py(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            diff_file = Path(argv[argv.index("--diff") + 1])
            existed_during_call.append(diff_file.exists())
            raise OSError("boom")
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _raise_for_review_py)

    with pytest.raises(OSError):
        handback._run_planner(ticket)

    assert existed_during_call == [True]
    assert len(paths) == 1
    assert not Path(paths[0]).exists()
