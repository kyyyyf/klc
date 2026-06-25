"""Top-level pytest conftest: per-test cleanup for known order-dependence issues."""
import importlib
import sys
from pathlib import Path

import pytest

_SHARED_PATH = str(Path(__file__).resolve().parent.parent / "core" / "shared")


@pytest.fixture(autouse=True)
def _restore_real_pyyaml():
    """Ensure sys.modules['yaml'] is real PyYAML (with safe_load) before each test.

    Multiple test files insert core/shared into sys.path at module level; a
    single sys.path.remove in jira_config.py's guard only removes the first
    copy, leaving the shadow findable for a bare `import yaml`.  This fixture
    pre-warms real PyYAML into sys.modules once, before the test body runs, so
    that both jira_config.load() and other callers always see the real module.
    """
    mod = sys.modules.get("yaml")
    if mod is not None and hasattr(mod, "safe_load"):
        # Already real PyYAML — nothing to do.
        yield
        return

    # Clear the shadow (if present) and pre-import real PyYAML with all
    # core/shared entries temporarily removed from sys.path.
    sys.modules.pop("yaml", None)
    removed_indices: list[int] = [
        i for i, p in enumerate(sys.path) if p == _SHARED_PATH
    ]
    # Remove in reverse order so indices stay valid
    for i in reversed(removed_indices):
        sys.path.pop(i)
    try:
        importlib.import_module("yaml")
    finally:
        # Restore core/shared entries at their original positions
        for i in removed_indices:
            sys.path.insert(i, _SHARED_PATH)
    yield
