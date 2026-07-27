#!/usr/bin/env python3
"""constitution.py — read helper for config/constitution.yml.

The constitution is the anchor the spec self-check (KLC-083) and the spec
reviewer (KLC-084) check specs against. This module is the ONE place that
loads the machine-form file, so callers reference principles by id and never
re-parse the YAML themselves (single-source-of-truth).

It ships DATA plus a tiny reader, not a rule engine: it hands back the list of
principles; deciding conformance is the caller's job. The file is read through
the in-repo minimal YAML parser (`_yaml.parse`), the same one every other klc
config loader uses, so no second parser is introduced.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports (mirrors classify_tier.py).
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root  # noqa: E402


def _load_local_yaml():
    """Load the in-repo `core/skills/_yaml.py` by file path.

    A bare `import _yaml` is NOT package-safe: under a package-style import
    (`core.skills.constitution`, used by other tools) `core/skills` is not on
    sys.path, so `_yaml` resolves to PyYAML's C accelerator module `_yaml`
    (which has no `parse`) or fails outright. Loading by path under a private
    module name binds our parser unambiguously under both script and package
    invocation, and never collides with PyYAML's `_yaml` in sys.modules.
    """
    mod_name = "_klc_constitution_yaml"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached.parse
    spec = importlib.util.spec_from_file_location(mod_name, _file_dir / "_yaml.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module.parse


_parse_yaml = _load_local_yaml()

CATEGORIES = ("architecture", "boundary", "process", "product", "governance")
CHECKS = ("deterministic", "review")


def constitution_path() -> Path:
    """Path to the machine-form constitution shipped with the framework."""
    return framework_root() / "config" / "constitution.yml"


def load() -> list[dict]:
    """Return the list of principle dicts, each with keys
    id / category / check / statement. Raises FileNotFoundError if the file is
    missing and ValueError if it is malformed or empty."""
    path = constitution_path()
    if not path.exists():
        raise FileNotFoundError(f"constitution: {path} not found")
    doc = _parse_yaml(path.read_text(encoding="utf-8"))
    principles = (doc or {}).get("principles") if isinstance(doc, dict) else None
    if not principles:
        raise ValueError(f"constitution: {path} has no principles")
    return principles


def ids() -> list[str]:
    """Every principle id, in file order."""
    return [p["id"] for p in load()]


def by_id(principle_id: str) -> dict | None:
    """The principle with this id, or None."""
    for p in load():
        if p.get("id") == principle_id:
            return p
    return None


def deterministic() -> list[dict]:
    """Principles a mechanical gate (KLC-083) can verify without judgment."""
    return [p for p in load() if p.get("check") == "deterministic"]


def review() -> list[dict]:
    """Principles an agent (KLC-084) must assess as a judgment call."""
    return [p for p in load() if p.get("check") == "review"]


if __name__ == "__main__":
    for _p in load():
        print(f"{_p['check']:13} {_p['category']:13} {_p['id']}")
