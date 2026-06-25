"""RED test: core/shared/yaml.py must not permanently shadow real PyYAML. (KLC-049 step-1)"""
import sys
import importlib
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parent.parent
_SHARED = str(_FW_ROOT / "core" / "shared")


def test_yaml_shadow_does_not_clobber_pyyaml():
    """After the klc yaml shadow is placed in sys.modules, the conftest fixture
    (which runs before each test) must clear it so real PyYAML is accessible."""
    # Save state
    _orig_yaml = sys.modules.get("yaml")
    _had_shared = _SHARED in sys.path

    try:
        # Force the klc shadow into sys.modules['yaml'] as a polluter would.
        if _SHARED not in sys.path:
            sys.path.insert(0, _SHARED)
        sys.modules.pop("yaml", None)
        shadow = importlib.import_module("yaml")
        assert not hasattr(shadow, "safe_load"), "pre-condition: shadow lacks safe_load"

        # Simulate the conftest _restore_real_pyyaml fixture:
        mod = sys.modules.get("yaml")
        if mod is not None and not hasattr(mod, "safe_load"):
            del sys.modules["yaml"]

        # Also remove shadow from sys.path so the re-import finds real PyYAML.
        if _SHARED in sys.path:
            sys.path.remove(_SHARED)

        real = importlib.import_module("yaml")
        assert hasattr(real, "safe_load"), (
            "After the conftest cleanup, import yaml must yield real PyYAML with safe_load. "
            "core/shared/yaml.py should NOT remain as sys.modules['yaml']."
        )
    finally:
        # Restore exactly what we found
        if not _had_shared and _SHARED in sys.path:
            sys.path.remove(_SHARED)
        if _orig_yaml is None:
            sys.modules.pop("yaml", None)
        else:
            sys.modules["yaml"] = _orig_yaml
