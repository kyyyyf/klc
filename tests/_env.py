"""Shared skip helpers for environment-dependent tests."""
import os
import shutil
from pathlib import Path

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent


def require_tool(name: str):
    """Return a pytest.mark.skipif that skips when `name` is not on PATH."""
    return pytest.mark.skipif(
        shutil.which(name) is None,
        reason=f"{name!r} not installed",
    )


def require_skills_executable() -> "pytest.MarkDecorator":
    """Skip when framework skill files lack execute permission.

    doctor's skills-executable check will fail independently of the
    project-deps scenario being tested, making the test result misleading.
    """
    sentinel = FRAMEWORK_ROOT / "core" / "skills" / "artefacts.py"
    return pytest.mark.skipif(
        not os.access(sentinel, os.X_OK),
        reason=(
            "Framework skill files are not executable (+x) in this environment; "
            "klc doctor will fail on the skills-executable check before reaching "
            "the project-tools check under test."
        ),
    )
