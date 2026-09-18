"""Top-level pytest conftest: per-test cleanup for known order-dependence issues."""
import importlib
import os
import sys
from pathlib import Path

import pytest

_SHARED_PATH = str(Path(__file__).resolve().parent.parent / "core" / "shared")


@pytest.fixture(autouse=True)
def _restore_project_root_env():
    """Snapshot $PROJECT_ROOT before each test and restore it after, no
    matter what the test did to `os.environ` directly.

    Several test files (Jira integration tests among them, e.g.
    test_jira_managed.py / test_jira_pull.py / test_jira_core.py, plus the
    KLC-057 multiuser fuzz suite) set `os.environ["PROJECT_ROOT"] = <tmp
    dir>` directly — without a `try/finally` and without the `monkeypatch`
    fixture — and never restore it. Once such a test's tmp dir is cleaned up,
    `PROJECT_ROOT` stays pointed at a DELETED directory for the rest of the
    pytest PROCESS, silently breaking any later test that resolves paths via
    `PROJECT_ROOT` without its own override (KLC-103: discovered via
    `test_detect_languages_real_key.py` / `test_klc103_rule_executor.py`
    intermittently failing only when the full suite runs them after one of
    these leaking tests). Two individual leaks were fixed directly
    (test_klc057_fuzz.py, tests/shared/test_paths.py); this fixture is the
    safety net for the rest — it guarantees process-wide isolation
    regardless of how many more such leaks exist today or get added later,
    without requiring an edit to every offending test file. It does not
    interfere with tests that already use `monkeypatch.setenv("PROJECT_ROOT",
    ...)` correctly: monkeypatch reverts its own change at its own teardown,
    so by the time this fixture's post-yield code runs, the value is already
    back to what it was when this fixture captured it — a harmless no-op
    restore in that case.
    """
    had = "PROJECT_ROOT" in os.environ
    original = os.environ.get("PROJECT_ROOT")
    yield
    if had:
        os.environ["PROJECT_ROOT"] = original
    else:
        os.environ.pop("PROJECT_ROOT", None)


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
