"""clarify_config.py — dialogue style for interactive clarify gates.

Global only (no per-track override, by design — see config/clarify.yml).
Fail-closed: an unrecognised STYLE VALUE raises rather than silently
falling back, so a typo in the style surfaces immediately instead of
quietly changing UX.

KLC-100: resolution now funnels through the settings loader. One edge
changes: a STRUCTURALLY malformed clarify.yml (e.g. a non-mapping top
level) now degrades to the next layer / DEFAULT_STYLE rather than raising
— the value-level fail-closed guarantee (an invalid style value still
raises) is unchanged.
"""
from __future__ import annotations

from pathlib import Path


VALID_STYLES = {"batch", "serial"}
DEFAULT_STYLE = "batch"


class ClarifyConfigError(ValueError):
    pass


def load_clarify_style() -> str:
    """Return the configured clarify dialogue style: "batch" or "serial".

    KLC-100: the style resolves through the settings loader (settings.yml
    first, then the legacy clarify.yml), so a `clarify.style` set in
    settings.yml is honored. Absent everywhere -> DEFAULT_STYLE. An explicit
    but unrecognised value (from either source) still raises
    ClarifyConfigError — fail-closed.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # ensure sibling on path
    import settings as _settings

    style = _settings.clarify_style()
    if style is None:
        return DEFAULT_STYLE
    if style not in VALID_STYLES:
        raise ClarifyConfigError(
            f"clarify style={style!r} invalid; use one of {sorted(VALID_STYLES)}"
        )
    return style
