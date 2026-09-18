#!/usr/bin/env python3
"""KLC-107 step-10/step-11 — stale.json names only directly-touched modules,
impacted_modules is a separate one-hop key, and the 20% blanket rule is gone.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import update as _upd  # noqa: E402


def _modules_dir(tmp_path: Path, modules_list: list[dict]) -> Path:
    (tmp_path / "modules.json").write_text(
        json.dumps({"modules": modules_list}), encoding="utf-8")
    return tmp_path


def test_stale_modules_contains_only_directly_touched_module(tmp_path):
    """AC-25: one changed file yields the single-element list holding that
    file's own module, with no transitive closure applied."""
    mods = [
        {"name": "modA", "path": "src/a", "files": ["src/a/foo.py"], "depended_by": []},
        {"name": "modB", "path": "src/b", "files": ["src/b/bar.py"], "depended_by": ["modA"]},
    ]
    idx = _modules_dir(tmp_path, mods)
    result = _upd._compute_stale(idx, ["src/b/bar.py"])
    assert result["stale_modules"] == ["modB"]


def test_impacted_modules_is_one_hop_reverse_dependents(tmp_path):
    """AC-26: impacted_modules equals the depended_by entries of the stale
    set, excluding the stale set itself — no further hops."""
    mods = [
        {"name": "modA", "path": "src/a", "files": ["src/a/foo.py"], "depended_by": []},
        {"name": "modB", "path": "src/b", "files": ["src/b/bar.py"], "depended_by": ["modA"]},
        {"name": "modC", "path": "src/c", "files": ["src/c/baz.py"], "depended_by": ["modA"]},
    ]
    idx = _modules_dir(tmp_path, mods)
    result = _upd._compute_stale(idx, ["src/b/bar.py"])
    assert result["stale_modules"] == ["modB"]
    assert result["impacted_modules"] == ["modA"]   # NOT modC — that's two hops


def test_impacted_modules_excludes_members_of_stale_modules_itself(tmp_path):
    """A module that depends on itself, or on another already-stale module,
    is excluded from impacted_modules — the two sets never overlap."""
    mods = [
        {"name": "modA", "path": "src/a", "files": ["src/a/foo.py"], "depended_by": ["modB"]},
        {"name": "modB", "path": "src/b", "files": ["src/b/bar.py"], "depended_by": ["modA"]},
    ]
    idx = _modules_dir(tmp_path, mods)
    result = _upd._compute_stale(idx, ["src/a/foo.py", "src/b/bar.py"])
    assert set(result["stale_modules"]) == {"modA", "modB"}
    assert result["impacted_modules"] == []


def test_high_percentage_change_does_not_mark_everything_stale(tmp_path):
    """AC-27: a commit changing more than a fifth of all tracked files names
    exactly the modules containing those files — the count is strictly
    smaller than the total whenever one module is untouched — and the
    20%-blanket branch is gone from the source."""
    mods = [
        {"name": f"mod{i}", "path": f"src/m{i}", "files": [f"src/m{i}/f.py"],
         "depended_by": []}
        for i in range(10)
    ]
    idx = _modules_dir(tmp_path, mods)
    # Change files in 3 of 10 modules — 30%, well over the old 20% threshold.
    changed = ["src/m0/f.py", "src/m1/f.py", "src/m2/f.py"]
    result = _upd._compute_stale(idx, changed)
    assert result["stale_modules"] == ["mod0", "mod1", "mod2"]
    assert len(result["stale_modules"]) < result["total_modules"]

    # Source-level confirmation the blanket branch is gone entirely, not
    # merely unreachable in this fixture.
    src = inspect.getsource(_upd._compute_stale)
    body = src.split('"""', 2)[-1]   # past the function's own docstring
    assert "0.2" not in body
    assert "tracked_files" not in body


def test_no_discontinuity_at_the_twenty_percent_boundary(tmp_path):
    """The removed blanket rule leaves no discontinuity at 19/20/21% changed
    — all three take the exact same per-file logic (the absence of a
    discontinuity IS the assertion, per the test-plan edge case)."""
    mods = [
        {"name": f"mod{i}", "path": f"src/m{i}", "files": [f"src/m{i}/f.py"],
         "depended_by": []}
        for i in range(100)
    ]
    idx = _modules_dir(tmp_path, mods)
    for pct_files in (19, 20, 21):
        changed = [f"src/m{i}/f.py" for i in range(pct_files)]
        result = _upd._compute_stale(idx, changed)
        assert result["stale_modules"] == sorted(f"mod{i}" for i in range(pct_files))


# --------------------------------------------------------------------------- #
# step-11 — the intake warning reports both counts and tolerates the old schema
# --------------------------------------------------------------------------- #

import contextlib
import io
import os

_PHASES = Path(__file__).resolve().parents[2] / "core" / "phases"


def _warn_output(tmp_path: Path, stale_json: dict) -> str:
    index_dir = tmp_path / ".klc" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "stale.json").write_text(json.dumps(stale_json), encoding="utf-8")

    old_project_root = os.environ.get("PROJECT_ROOT")
    os.environ["PROJECT_ROOT"] = str(tmp_path)
    try:
        sys.path.insert(0, str(_PHASES))
        import intake as _intake
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            _intake._warn_stale_modules()
        return buf.getvalue()
    finally:
        if old_project_root is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = old_project_root


def test_intake_warning_reports_counts_and_reads_old_schema(tmp_path):
    """AC-28: a stale.json carrying both keys names the two counts
    separately; a stale.json written before this ticket (no
    impacted_modules key) is read without error."""
    out = _warn_output(tmp_path / "new", {
        "stale_modules": ["modB"], "impacted_modules": ["modA", "modC"],
        "changed_files": 1, "total_modules": 3,
    })
    assert "1 module doc(s) may be outdated" in out
    assert "2 impacted neighbour(s)" in out
    assert "modB" in out

    # Back-compat twin: no impacted_modules key at all.
    out_old = _warn_output(tmp_path / "old", {
        "stale_modules": ["modB"], "changed_files": 1, "total_modules": 3,
    })
    assert "1 module doc(s) may be outdated" in out_old
    assert "impacted neighbour" not in out_old
    assert "modB" in out_old


if __name__ == "__main__":
    import unittest
    unittest.main()
