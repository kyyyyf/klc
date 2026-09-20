"""tests/integration/test_klc109_scope_delta.py — KLC-109 step-6: the
planned-versus-actual scope comparison attributes a changed test file to the
module of its production counterpart, rather than to a bare `tests` module.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_skills = Path(__file__).resolve().parents[2] / "core" / "skills"
sys.path.insert(0, str(_skills))
import scope_delta as sd  # noqa: E402


def _run_compare(monkeypatch, tmp_path, changed, planned, modules):
    idx = tmp_path / "index"
    idx.mkdir()
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")
    monkeypatch.setattr(sd, "klc_index_dir", lambda: idx)
    monkeypatch.setattr(sd, "_git_changed_files", lambda root: list(changed))
    monkeypatch.setattr(sd, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sd._lc, "read_meta",
                        lambda t: {"affected_modules": list(planned)})
    return sd.compare("KLC-XXX")


def test_changed_test_file_attributed_to_production_counterpart_module(monkeypatch, tmp_path):
    """AC-11: a branch changing only core/skills/foo.py and tests/test_foo.py
    reports NO unplanned `tests` module in `drift`."""
    modules = {"modules": [
        {"name": "core/skills", "path": "core/skills/"},
        {"name": "tests", "path": "tests/"},
    ]}
    d = _run_compare(monkeypatch, tmp_path,
                     changed=["core/skills/foo.py", "tests/test_foo.py"],
                     planned=["core/skills"], modules=modules)
    assert "tests" not in d["drift"], d
    assert d["actual"] == ["core/skills"], d


def test_orphan_test_file_falls_back_to_own_module():
    """AC-11 fallback: a test file with no resolvable production counterpart
    (among the OTHER changed files) still falls back to its own path."""
    out = sd._attribute_tests(["tests/test_orphan.py"])
    assert out == ["tests/test_orphan.py"]


def test_ambiguous_counterpart_resolves_deterministically():
    """AC-11 tie-break: two changed production files share a stem in
    different modules — the first candidate in production_candidates order
    wins, then the lexicographically smallest path, stable across runs."""
    files = ["b/foo.py", "a/foo.py", "tests/test_foo.py"]
    out1 = sd._attribute_tests(files)
    out2 = sd._attribute_tests(list(reversed(files)))
    assert out1 == out2 == ["a/foo.py", "b/foo.py"]
