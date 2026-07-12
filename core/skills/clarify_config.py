"""clarify_config.py — dialogue style for interactive clarify gates.

Global only (no per-track override, by design — see config/clarify.yml).
Fail-closed: an unrecognised style raises rather than silently falling
back, so a typo in project config surfaces immediately instead of
quietly changing UX.
"""
from __future__ import annotations

import sys
from pathlib import Path

_skills_dir = Path(__file__).resolve().parent
_project_root = _skills_dir.parent.parent
sys.path.insert(0, str(_project_root))

from core.shared.paths import framework_root, klc_config_dir  # noqa: E402
from core.shared.yaml import parse as _yaml_parse  # noqa: E402


VALID_STYLES = {"batch", "serial"}
DEFAULT_STYLE = "batch"


class ClarifyConfigError(ValueError):
    pass


def _load_path() -> Path | None:
    """Project override wins over framework copy. None if neither exists."""
    project_override = klc_config_dir() / "clarify.yml"
    if project_override.exists():
        return project_override
    fw_copy = framework_root() / "config" / "clarify.yml"
    if fw_copy.exists():
        return fw_copy
    return None


def load_clarify_style() -> str:
    """Return the configured clarify dialogue style: "batch" or "serial".

    Absent config (no framework or project clarify.yml) -> DEFAULT_STYLE.
    An explicit but unrecognised value raises ClarifyConfigError rather
    than silently falling back.
    """
    path = _load_path()
    if path is None:
        return DEFAULT_STYLE

    raw = _yaml_parse(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ClarifyConfigError(f"clarify.yml: expected top-level mapping in {path}")

    section = raw.get("clarify") or {}
    if not isinstance(section, dict):
        raise ClarifyConfigError(f"clarify.yml: 'clarify' must be a mapping in {path}")

    style = section.get("style", DEFAULT_STYLE)
    if style not in VALID_STYLES:
        raise ClarifyConfigError(
            f"clarify.yml: style={style!r} invalid; use one of {sorted(VALID_STYLES)}"
        )
    return style
