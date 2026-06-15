"""KLC-024 step-3: context-loader returns neighbours when reverse edges present."""
import json
import sys
from pathlib import Path

import pytest

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))

import importlib
import importlib.util


def _load_context_loader():
    """Load context-loader.py (hyphenated filename) via importlib."""
    spec = importlib.util.spec_from_file_location(
        "context_loader_mod",
        _skills / "context-loader.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cl_mod = _load_context_loader()


def test_depth1_pulls_neighbours():
    """bfs_neighbours at depth=1 returns the neighbour module when reverse edge exists."""
    modules = [
        {"name": "modA", "path": "src/a", "depends_on": [], "depended_by": ["modB"]},
        {"name": "modB", "path": "src/b", "depends_on": ["modA"], "depended_by": []},
        {"name": "modC", "path": "src/c", "depends_on": [], "depended_by": []},
    ]
    # Seed: modA. At depth=1, should pull modB (it depends on A = depended_by edge).
    result = _cl_mod.bfs_neighbours(["modA"], modules, depth=1)
    assert "modB" in result
    assert "modC" not in result


def test_depth0_no_neighbours():
    """At depth=0, no neighbours beyond the seed itself."""
    modules = [
        {"name": "modA", "path": "src/a", "depends_on": [], "depended_by": ["modB"]},
        {"name": "modB", "path": "src/b", "depends_on": ["modA"], "depended_by": []},
    ]
    result = _cl_mod.bfs_neighbours(["modA"], modules, depth=0)
    assert result == ["modA"]


def test_empty_edges_no_crash():
    """modules with empty depends_on/depended_by don't crash bfs_neighbours."""
    modules = [
        {"name": "modA", "path": "src/a", "depends_on": [], "depended_by": []},
    ]
    result = _cl_mod.bfs_neighbours(["modA"], modules, depth=2)
    assert result == ["modA"]
