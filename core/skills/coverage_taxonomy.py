#!/usr/bin/env python3
"""coverage_taxonomy.py — read helper for config/coverage-taxonomy.yml.

The coverage taxonomy is the anchor the elicitation skill (E-02, KLC-088) and the
coverage gate (E-05, KLC-089) will check draft specs against. This module is the
ONE place that loads the machine-form file, so callers reference categories by id
and never re-parse the YAML themselves (single-source-of-truth). It mirrors
`core/skills/constitution.py` exactly in shape.

It ships DATA plus a tiny reader, not a rule engine: it hands back the list of
coverage categories; deciding whether a draft spec covers a category is the
caller's job. The file is read through the in-repo minimal YAML parser
(`_yaml.parse`), the same one every other klc config loader uses, loaded under a
private module name so no second parser is introduced and PyYAML's C-accelerator
`_yaml` is never picked up by accident under a package-style import.

Degrade-not-fail: a missing or malformed taxonomy file must never crash a
consumer. This reader degrades MORE than constitution.py, on purpose — do not
"align" the two by deleting the try/except below, or AC-7 / C-002 break. In
constitution.py the accessors (`ids`, `by_id`, ...) do NOT catch; they propagate
FileNotFoundError / ValueError and degradation happens at the CALLER. Here the
consumer-facing accessors (`categories`, `ids`, `by_id`, `for_track`) catch
inside the accessor and return an empty / None result, so a coverage scan with no
taxonomy present is a clean no-op even for a caller that does not guard. Only
`load()` — the strict, single-source read — still raises.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports (mirrors constitution.py).
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root, klc_config_dir  # noqa: E402


def _load_local_yaml():
    """Load the in-repo `core/skills/_yaml.py` by file path under a private name.

    A bare `import _yaml` is NOT package-safe: under a package-style import
    (`core.skills.coverage_taxonomy`, used by later consumers) `core/skills` is
    not on sys.path, so `_yaml` resolves to PyYAML's C accelerator module `_yaml`
    (which has no `parse`) or fails outright. Loading by path under a private
    module name binds our parser unambiguously under both script and package
    invocation. The name is distinct from constitution.py's so the two readers
    coexist in one process without a sys.modules collision.
    """
    mod_name = "_klc_coverage_taxonomy_yaml"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached.parse
    spec = importlib.util.spec_from_file_location(mod_name, _file_dir / "_yaml.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module.parse


_parse_yaml = _load_local_yaml()

# Track ordering (XS < S < M < L). Hard-coded locally — matching the peer skills
# track_classifier.py, route_heuristic.py, and phase_completion.py, which each keep
# their own copy — rather than importing phases.TRACK_ORDER. The reader must load
# package-safely with core/skills off sys.path, so it avoids importing a sibling
# skill module; the four-way ordering is stable and this keeps the reader
# self-contained, exactly as constitution.py is.
_TRACK_ORDER = {"XS": 0, "S": 1, "M": 2, "L": 3}


def _floor_rank(min_track: object) -> int:
    """Rank of a category's min_track floor, with 99 (= above L, always excluded)
    for anything that is not a known XS/S/M/L string. A non-string floor (e.g. a
    list from a malformed override) must not reach the dict lookup, or it raises
    `TypeError: unhashable type` — so this normalises before the lookup and keeps
    for_track degrade-not-fail (codex-P2)."""
    if not isinstance(min_track, str):
        return 99
    return _TRACK_ORDER.get(min_track, 99)


def taxonomy_path() -> Path:
    """Path to the taxonomy file, project override winning over the framework copy.

    `.klc/config/coverage-taxonomy.yml` shadows `config/coverage-taxonomy.yml`
    when present, exactly like models.py resolves models.yml.
    """
    override = klc_config_dir() / "coverage-taxonomy.yml"
    if override.exists():
        return override
    return framework_root() / "config" / "coverage-taxonomy.yml"


def load() -> dict:
    """Return the parsed taxonomy document: a mapping with `schema_version` and a
    non-empty `categories` list. Raises FileNotFoundError if the file is missing
    and ValueError if it is malformed or carries no categories."""
    path = taxonomy_path()
    if not path.exists():
        raise FileNotFoundError(f"coverage-taxonomy: {path} not found")
    doc = _parse_yaml(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"coverage-taxonomy: {path} is not a mapping")
    cats = doc.get("categories")
    if not cats or not isinstance(cats, list):
        raise ValueError(f"coverage-taxonomy: {path} has no categories")
    return doc


def categories() -> list[dict]:
    """The list of category dicts, or [] when the file is absent or malformed.

    Catches OSError (covers FileNotFoundError, plus IsADirectoryError /
    PermissionError when taxonomy_path() resolves to a directory or an unreadable
    file — `.exists()` is True for both) and ValueError (malformed YAML /
    no-categories, plus UnicodeDecodeError). Nothing raised here reaches a
    consumer.
    """
    try:
        cats = load().get("categories") or []
    except (OSError, ValueError):
        return []
    return [c for c in cats if isinstance(c, dict)]


def ids() -> list[str]:
    """Every category id, in file order; [] when the file is absent or malformed."""
    return [c["id"] for c in categories() if isinstance(c.get("id"), str)]


def by_id(category_id: str) -> dict | None:
    """The category with this id, or None (also None when the file is absent)."""
    for c in categories():
        if c.get("id") == category_id:
            return c
    return None


def for_track(track: str) -> list[dict]:
    """The categories whose min_track floor is at or below `track`.

    Returns [] for an unknown track string and [] when the file is absent or
    malformed — never raises (degrade-not-fail).
    """
    floor = _TRACK_ORDER.get(track)
    if floor is None:
        return []
    return [c for c in categories() if _floor_rank(c.get("min_track")) <= floor]


if __name__ == "__main__":
    for _c in load().get("categories", []):
        print(f"{_c.get('min_track', '?'):3} {_c.get('id')}")
