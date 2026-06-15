"""KLC-024 step-1: _compute_stale accepts object form modules.json."""
import json
import sys
from pathlib import Path

import pytest

_scripts = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(_scripts))
import update as _upd  # noqa: E402


def _make_modules_obj(tmp_path, modules_list):
    """Write {"modules": [...]} form (real format)."""
    f = tmp_path / "modules.json"
    f.write_text(json.dumps({"modules": modules_list}), encoding="utf-8")
    return tmp_path


def _make_modules_list(tmp_path, modules_list):
    """Write bare-list form (legacy)."""
    f = tmp_path / "modules.json"
    f.write_text(json.dumps(modules_list), encoding="utf-8")
    return tmp_path


_MODULE_A = {"name": "modA", "path": "src/a", "files": ["src/a/foo.py"], "depended_by": []}
_MODULE_B = {"name": "modB", "path": "src/b", "files": ["src/b/bar.py"], "depended_by": ["modA"]}


def test_object_format_no_crash(tmp_path):
    """Object form {"modules":[...]} must not raise and return correct stale set."""
    idx = _make_modules_obj(tmp_path, [_MODULE_A, _MODULE_B])
    result = _upd._compute_stale(idx, ["src/b/bar.py"])
    assert result["stale_modules"] == ["modA", "modB"]
    assert result["total_modules"] == 2


def test_bare_list_back_compat(tmp_path):
    """Legacy bare-list form still works after the fix."""
    idx = _make_modules_list(tmp_path, [_MODULE_A, _MODULE_B])
    result = _upd._compute_stale(idx, ["src/b/bar.py"])
    assert result["stale_modules"] == ["modA", "modB"]
    assert result["total_modules"] == 2


def test_malformed_degrades(tmp_path):
    """Malformed JSON returns empty stale set instead of raising."""
    f = tmp_path / "modules.json"
    f.write_text("not valid json {{", encoding="utf-8")
    result = _upd._compute_stale(tmp_path, ["src/b/bar.py"])
    assert result["stale_modules"] == []
    assert result["changed_files"] == 1
