"""KLC-111 step-2 — `module_vocabulary`: the one module that answers "is this
path infra" and "what module name does this path have" (AC-4).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import module_vocabulary as _mv  # noqa: E402


def test_two_segment_module_name_tests_integration_is_valid_and_not_normalised():
    """AC-4: the module-name vocabulary is exactly the `name` set of
    modules.json plus infra entries, so a two-segment name such as
    `tests/integration` remains a first-class member and a file under it
    resolves to that name, never collapsed to its parent `tests`."""
    modules_data = {"modules": [
        {"name": "tests", "path": "tests/"},
        {"name": "tests/integration", "path": "tests/integration/"},
    ]}
    assert "tests/integration" in _mv.module_names(modules_data)
    resolved = _mv.resolve_name("tests/integration/test_foo.py", modules_data)
    assert resolved == "tests/integration"
    assert resolved != "tests"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
