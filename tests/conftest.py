"""Top-level pytest conftest: per-test cleanup for known order-dependence issues."""
import sys
import pytest


@pytest.fixture(autouse=True)
def _restore_real_pyyaml():
    """Remove the core/shared/yaml.py shadow from sys.modules before each test.

    core/shared/yaml.py can end up registered as sys.modules['yaml'] when a
    test inserts core/shared into sys.path and imports from yaml. Real PyYAML
    is used by jira_config and other production code; losing it causes
    'pyyaml not available' errors in subsequent tests (order-dependence).
    """
    mod = sys.modules.get("yaml")
    if mod is not None and not hasattr(mod, "safe_load"):
        del sys.modules["yaml"]
    yield
