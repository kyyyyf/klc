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


def resolve(dotted_key, *, legacy_file=None, legacy_key=None, default=None,
            project_legacy=True, project_dir=None):
    """Resolve one knob through the interleaved ladder.

    ``project_dir`` overrides the project scope root (jira forwards its
    ``config_dir=`` injection seam here so ``jira_config.load(config_dir=X)``
    keeps working — impl-review F-1). ``project_legacy=False`` drops layer 2 for
    knobs whose legacy has no project scope (the cap — spec-review F-5).

    ``legacy_file``/``legacy_key`` default to ``None`` (KLC-106 F-1/D-201): a
    knob introduced AFTER settings.yml has no legacy file at all, and omitting
    both drops the two legacy layers rather than forcing the caller to invent
    a file that was never shipped. Supplying exactly one of the pair is a
    programming error and raises — silently dropping a ladder layer would be
    the same dishonest degrade this ticket removes everywhere else.
    """
    if (legacy_file is None) != (legacy_key is None):
        raise ValueError(
            "resolve(): legacy_file and legacy_key must be given together "
            "(or both omitted for a knob with no legacy file)")
    has_legacy = legacy_file is not None
    proj = Path(project_dir) if project_dir is not None else _proj_config()
    layers = [(proj / "settings.yml", dotted_key)]
    if has_legacy and project_legacy:
        layers.append((proj / legacy_file, legacy_key))
    layers.append((_fw_config() / "settings.yml", dotted_key))
    if has_legacy:
        layers.append((_fw_config() / legacy_file, legacy_key))
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


HOOK_MODES = ("direct", "snippet", "disabled")


def advisory_threshold() -> str:
    """Severity at or above which the advisory gate signal is dirty (KLC-117
    C-004). Rides the existing project-before-framework ladder. An unknown
    value falls back to the built-in default rather than crashing resolution,
    mirroring how every other knob degrades per-knob. No legacy file predates
    this knob (mirrors `hook_mode`'s harmless probe against `profile.yml`)."""
    value = resolve("advisory.threshold", legacy_file="profile.yml",
                    legacy_key="advisory_threshold", default="medium")
    return value if value in ("high", "medium", "low", "info") else "medium"


def hook_mode():
    """Recorded pre-commit wiring mode, or None when install never recorded
    one (KLC-107 AC-17). No legacy file predates this knob."""
    return resolve("index.hook_mode", legacy_file="profile.yml",
                   legacy_key="index_hook_mode", default=None)


def hook_location():
    """Resolved hooks directory / detected manager name install recorded
    alongside `hook_mode` (KLC-107 AC-17)."""
    return resolve("index.hook_location", legacy_file="profile.yml",
                   legacy_key="index_hook_location", default=None)


def index_refresh_budget() -> float:
    """Wall-clock budget (seconds) for the verb-side lazy refresh (KLC-107
    AC-12). `index_refresh.py` resolves this key itself via `resolve()`
    directly rather than calling this accessor, so this is a convenience
    for other callers, not a hidden extra call site."""
    return float(resolve("index.refresh_budget_seconds", legacy_file="profile.yml",
                         legacy_key="index_refresh_budget_seconds", default=30.0))


def verify_entry_budget() -> int:
    """Wall-clock budget (seconds) for re-running ONE Evidence entry's command
    at build ack (KLC-115 AC-12)."""
    try:
        return int(resolve("verify.entry_budget_seconds", legacy_file="profile.yml",
                           legacy_key="verify_entry_budget_seconds", default=120))
    except (TypeError, ValueError):
        return 120


def verify_step_budget() -> int:
    """Wall-clock budget (seconds) for re-running ONE impl-plan step's `VERIFY:`
    command at build ack (KLC-115 AC-12)."""
    try:
        return int(resolve("verify.step_budget_seconds", legacy_file="profile.yml",
                           legacy_key="verify_step_budget_seconds", default=120))
    except (TypeError, ValueError):
        return 120


def verify_node_budget() -> int:
    """Wall-clock budget (seconds) for verifying ONE AC-referencing pytest node
    in `ac_test_coverage` (KLC-115 AC-12)."""
    try:
        return int(resolve("verify.node_budget_seconds", legacy_file="profile.yml",
                           legacy_key="verify_node_budget_seconds", default=120))
    except (TypeError, ValueError):
        return 120


def verify_arm_budget() -> int:
    """Wall-clock budget (seconds) for the WHOLE verification arm at one build
    ack — once spent, remaining entries/nodes surface as
    `unverified: arm-budget-exhausted` rather than running (KLC-115 AC-12).

    review-fix (HIGH): this is ONE ceiling for the ack as a whole, not one
    per checker. `phase_completion.can_complete_build` computes a single
    `time.monotonic()` deadline from this value and threads it through
    `ac_test_coverage.check`, `evidence_gate.check_evidence` and
    `step_verify.check_steps` — so a slow ac-coverage arm eats into the
    budget the Evidence/step-verify arms get, and the total ack ceiling is
    this ONE value, not three independent ones. Each checker still computes
    its own fresh deadline when called standalone with no shared deadline
    (e.g. a unit test)."""
    try:
        return int(resolve("verify.arm_budget_seconds", legacy_file="profile.yml",
                           legacy_key="verify_arm_budget_seconds", default=600))
    except (TypeError, ValueError):
        return 600


def scope_infra_paths():
    """Framework/delivery paths outside the module graph (KLC-111 AC-1).

    Settings-only ladder: this knob is new, so there is no legacy file to
    consult. Returns the raw ladder value, including None when unset; the
    built-in default and the degrade live in module_vocabulary, so this
    layer stays pure resolution (D-003)."""
    return resolve("scope.infra_paths")


def index_coverage_threshold(builder=None):
    """Index-coverage floor (KLC-106 AC-2). Settings-only ladder: this knob is
    new, so there is no legacy file to consult. The per-builder override wins
    when set; the built-in default lives in index_coverage, not here, so the
    data layer stays pure data."""
    if builder:
        override = resolve(f"index.coverage.per_builder.{builder}")
        if override is not None:
            return override
    return resolve("index.coverage.min_ratio")


def index_coverage_language_share_threshold():
    """Dominant-language floor for the retriever's language-scoped inventory
    cap (KLC-123 AC-9). Settings-only ladder, same shape as
    `index_coverage_threshold`: this knob is new, so there is no legacy file
    to consult. The built-in default lives in index_coverage, not here."""
    return resolve("index.coverage.language_share_threshold")


def build_verify_steps() -> bool:
    """KLC-114 AC-11: on/off knob for the post-build step ledger pass.
    Settings-only ladder (no legacy file — this knob is new, KLC-106
    precedent). Defaults to true: the pass is report-producing, not
    ack-blocking, so a default-on pass cannot break an existing flow."""
    return bool(resolve("build.verify_steps", default=True))


def build_per_step_review_on_verify() -> bool:
    """KLC-114 AC-11: dispatches the per-step reviewer when the ledger pass
    records a step non-green. Settings-only ladder, defaults to false — it
    costs a model call, so it opts in rather than opts out."""
    return bool(resolve("build.per_step_review_on_verify", default=False))


def autorun_cap():
    """Autonomous-runner consecutive-auto-transition cap, or None if unset.

    The legacy layer is framework-only (``config/budgets.yml``); a project
    budgets.yml is deliberately not consulted for the cap (spec-review F-5).
    """
    return resolve("autorun.consecutive_auto_transitions", legacy_file="budgets.yml",
                   legacy_key="consecutive_auto_transitions", project_legacy=False)


def _posint(value, default: int) -> int:
    """A positive int, else *default* (KLC-139 AC-10: 0, -1, 'abc', None)."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def skeleton_max_fields() -> int:
    """Data members shown per Python class before `[N more truncated]`
    (KLC-139, Q-001). Settings-only ladder: no legacy file."""
    return _posint(resolve("skeleton.max_fields"), 8)


def skeleton_max_line() -> int:
    """Max characters per rendered outline line, range included (KLC-139)."""
    return _posint(resolve("skeleton.max_line"), 120)


def skeleton_max_bytes() -> int:
    """Files above this size are refused (KLC-139; 2 MiB)."""
    return _posint(resolve("skeleton.max_bytes"), 2_097_152)
