"""KLC-111 step-2 — validation and `scope_delta.compare` must never disagree
on a file's module name (AC-5): both resolve through the ONE
`module_membership.file_to_module`, and `module_vocabulary.resolve_name` is a
thin wrapper over it, never a second implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import module_membership as _mm  # noqa: E402
import module_vocabulary as _mv  # noqa: E402


def test_validation_and_compare_agree_on_hooks_pre_commit():
    """AC-5: both call sites resolve `hooks/pre-commit` to `hooks` via the
    one `file_to_module` (longest-prefix over the directory module
    `hooks/`)."""
    modules_data = {"modules": [{"name": "hooks", "path": "hooks/"}]}
    via_validation = _mv.resolve_name("hooks/pre-commit", modules_data)
    via_scope_guard = _mm.file_to_module("hooks/pre-commit", modules_data)["primary_module"]
    assert via_validation == via_scope_guard == "hooks"


def test_validation_and_compare_agree_on_root_readme_md():
    """AC-5: both resolve the root `README.md` to `.` (`files_override`),
    a byte-identical name on both sides."""
    modules_data = {
        "modules": [{"name": ".", "path": "."}],
        "files": {"README.md": {"primary_module": "."}},
    }
    via_validation = _mv.resolve_name("README.md", modules_data)
    via_scope_guard = _mm.file_to_module("README.md", modules_data)["primary_module"]
    assert via_validation == via_scope_guard == "."


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
