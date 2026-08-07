"""settings.py — consolidated operational knobs behind a backward-compatible loader.

Single front door for the frequently-flipped SYSTEM settings, fronted by
``config/settings.yml`` (framework) and ``.klc/config/settings.yml`` (project),
with every accessor falling back to the pre-settings.yml legacy file
(``profile.yml`` / ``clarify.yml`` / ``jira.yml`` / ``budgets.yml``) so an install
that has not migrated behaves byte-for-byte as before (KLC-100 AC-3 / C-001).

Resolution ladder (INTERLEAVED — project layers BEFORE framework layers, so a
project's explicit legacy choice is never overridden by a framework-level
settings default; spec-review F-2 / C-002):

    1. <project>/settings.yml   [dotted key]      project, new
    2. <project>/<legacy>.yml    [legacy key]      project, legacy   (skipped for the cap)
    3. <framework>/settings.yml  [dotted key]      framework, new
    4. <framework>/<legacy>.yml  [legacy key]      framework, legacy
    5. hard default

The framework-shipped ``config/settings.yml`` and the ``klc install``-seeded
``.klc/config/settings.yml`` ship every knob COMMENTED, so they contribute no
active value and resolution falls through to the legacy files by construction.
"""
from __future__ import annotations

import sys
from pathlib import Path

# F-4: two of this module's callers run with only the skills dir on sys.path —
# profile-resolve.py (invoked as a subprocess by many skills) and doctor.py — so
# ``from core.shared...`` would fail there. Put the repo root on the path first.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.shared.paths import framework_root, klc_config_dir  # noqa: E402
from core.shared.yaml import parse as _parse  # noqa: E402

_MISSING = object()


def _proj_config() -> Path:
    """Per-project config dir (.klc/config). Monkeypatched in tests."""
    return klc_config_dir()


def _fw_config() -> Path:
    """Framework config dir (config/). Monkeypatched in tests."""
    return framework_root() / "config"


def _read_key(path: Path, dotted: str):
    """Return the value at ``dotted`` in the YAML file at ``path``.

    ``_MISSING`` when the file is absent, malformed, not a mapping, or the key
    (or any parent) is absent. A malformed scope degrades — it never raises
    (impl-review F-2): the caller simply continues to the next layer.
    """
    if not path.exists():
        return _MISSING
    try:
        data = _parse(path.read_text(encoding="utf-8")) or {}
    except ValueError:
        return _MISSING
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return _MISSING
        data = data[part]
    return data


def resolve(dotted_key, *, legacy_file, legacy_key, default=None,
            project_legacy=True, project_dir=None):
    """Resolve one knob through the interleaved four-layer ladder.

    ``project_dir`` overrides the project scope root (jira forwards its
    ``config_dir=`` injection seam here so ``jira_config.load(config_dir=X)``
    keeps working — impl-review F-1). ``project_legacy=False`` drops layer 2 for
    knobs whose legacy has no project scope (the cap — spec-review F-5).
    """
    proj = Path(project_dir) if project_dir is not None else _proj_config()
    layers = [(proj / "settings.yml", dotted_key)]
    if project_legacy:
        layers.append((proj / legacy_file, legacy_key))
    layers += [
        (_fw_config() / "settings.yml", dotted_key),
        (_fw_config() / legacy_file, legacy_key),
    ]
    for path, key in layers:
        value = _read_key(path, key)
        if value is not _MISSING:
            return value
    return default


# ------------------------------------------------------------ typed accessors

def profile():
    """Active profile name, or None if unset at every layer (caller decides)."""
    return resolve("profile", legacy_file="profile.yml", legacy_key="profile")


def clarify_style():
    """Clarify dialogue style raw value, or None if unset (caller validates)."""
    return resolve("clarify.style", legacy_file="clarify.yml", legacy_key="clarify.style")


def jira_enabled(config_dir=None) -> bool:
    """Jira integration on/off. ``config_dir`` = the caller's project scope."""
    return bool(resolve("jira.enabled", legacy_file="jira.yml", legacy_key="enabled",
                        default=False, project_dir=config_dir))


def jira_mode(config_dir=None) -> str:
    """Jira mode (mirror|managed). ``config_dir`` = the caller's project scope."""
    return resolve("jira.mode", legacy_file="jira.yml", legacy_key="mode",
                   default="mirror", project_dir=config_dir)


def autorun_cap():
    """Autonomous-runner consecutive-auto-transition cap, or None if unset.

    The legacy layer is framework-only (``config/budgets.yml``); a project
    budgets.yml is deliberately not consulted for the cap (spec-review F-5).
    """
    return resolve("autorun.consecutive_auto_transitions", legacy_file="budgets.yml",
                   legacy_key="consecutive_auto_transitions", project_legacy=False)
