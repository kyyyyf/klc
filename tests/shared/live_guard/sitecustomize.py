"""KLC-136 — the subprocess shim.

`klc_live_guard_plugin.py` prepends this directory (`tests/shared/live_guard`)
to a test subprocess's `PYTHONPATH`, so the interpreter imports THIS module,
under the reserved name `sitecustomize`, before running anything else. That
lets `install_from_env()` wire the guard up even in a `python -c ...`
one-liner that never imports `klc_live_guard` itself.

A plain `import sitecustomize` from inside this module would return THIS
module from `sys.modules` (Python is already mid-way through initialising
it) rather than the next `sitecustomize.py` on `sys.path` — so any system or
site-packages `sitecustomize` (virtualenv activation, coverage.py, ...)
would silently never run. Instead we locate the next one explicitly via
`importlib.machinery.PathFinder`, over `sys.path` with THIS directory
removed, load it under a private name, and execute it (impl-plan-review F-5).
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

_klc_chained = False


def _chain_system_sitecustomize() -> bool:
    search_path = [p for p in sys.path if os.path.abspath(p or ".") != _THIS_DIR]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", search_path)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    sys.modules["_klc_system_sitecustomize"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        return False
    return True


_klc_chained = _chain_system_sitecustomize()

try:
    import klc_live_guard

    klc_live_guard.install_from_env(os.environ)
except Exception:
    pass
