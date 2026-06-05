#!/usr/bin/env python3
"""Config validation skill for klc doctor.

Validates that config YAML files contain only known keys, helping catch
typos and deprecated config options early.

Usage:
    from core.skills import validate_config
    warnings = validate_config.validate_all()
    for w in warnings:
        print(f"Warning: {w}")
"""
from __future__ import annotations

import sys
import yaml
from pathlib import Path
from typing import Any

# Add project root to path for imports
_this_file = Path(__file__).resolve()
sys.path.insert(0, str(_this_file.parent.parent.parent))

from core.shared import paths as _p


# Known config schemas - maps config filename to set of allowed top-level keys
KNOWN_SCHEMAS = {
    "phases.yml": {
        "phases",  # array of phase definitions
    },
    "budgets.yml": {
        "version",               # schema version
        "prompt_input_limits",   # legacy: per-track token limits
        "soft_limits",           # warn only — run proceeds
        "hard_limits",           # block — dispatch refused
    },
    "models.yml": {
        "version",      # schema version
        "defaults",     # default model settings
        "roles",        # role definitions
        "phase_roles",  # phase to role mappings
        "per_track",    # track-specific overrides
    },
    "tiers.yml": {
        "tiers",           # tier definitions (critical/core/peripheral)
        "fallback_tier",   # default tier when no pattern matches
    },
    "sentinels.yml": {
        "sentinels",  # array of sentinel patterns
    },
    "reviewers.yml": {
        "external_reviewer",  # external reviewer config
        "test",              # test reviewer config
        "review",            # review orchestration config
        "cascade",           # cascade routing config
        "reports",           # report generation config
    },
    "jira.yml": {
        "enabled",          # integration on/off
        "mode",             # mirror | managed
        "site",             # Jira site connection
        "gitlab",           # GitLab source link config
        "status_mapping",   # klc_to_jira + jira_to_klc
        "artifacts",        # artefact link paths
        "url_template",     # legacy: Jira URL template
        "sync",             # legacy: push path config
    },
    "ticket-id.yml": {
        "pattern",  # ticket ID regex pattern
    },
    "profile.yml": {
        "profile",  # active profile name
    },
}

# Files to skip validation (seed files, not runtime config)
SKIP_FILES = {
    "reviewer-allowlist.seed.yml",
}


def validate_file(config_path: Path) -> list[str]:
    """Validate a single config file for unknown keys.

    Args:
        config_path: Path to config file

    Returns:
        List of warning messages (empty if valid)
    """
    warnings = []
    filename = config_path.name

    # Skip seed files
    if filename in SKIP_FILES:
        return warnings

    # Skip files without known schemas (may be project-specific)
    if filename not in KNOWN_SCHEMAS:
        return warnings

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            warnings.append(f"{filename}: root element must be a dictionary")
            return warnings

        allowed_keys = KNOWN_SCHEMAS[filename]
        actual_keys = set(data.keys())
        unknown_keys = actual_keys - allowed_keys

        if unknown_keys:
            unknown_list = ", ".join(sorted(unknown_keys))
            warnings.append(
                f"{filename}: unknown keys: {unknown_list}"
            )

    except Exception as e:
        warnings.append(f"{filename}: failed to parse: {e}")

    return warnings


def validate_phase_roles(config_dir: Path) -> list[str]:
    """Check models.yml against phases.yml.

    Rules:
    - Every phase with a non-empty work.prompt must have an entry in
      phase_roles (or a per_track override for every track it appears in).
    - Every per_track.<track>.<phase> must reference a phase that exists in
      phases.yml.
    - Every work.prompt file must exist on disk.
    """
    warnings: list[str] = []
    try:
        import yaml
        models_path = config_dir / "models.yml"
        phases_path = config_dir / "phases.yml"
        if not models_path.exists() or not phases_path.exists():
            return warnings

        models = yaml.safe_load(models_path.read_text()) or {}
        phase_roles: dict = models.get("phase_roles") or {}
        per_track: dict = models.get("per_track") or {}

        fw = _p.framework_root()

        # Load phases via our own parser to stay consistent
        sys.path.insert(0, str(fw / "core" / "skills"))
        import phases as _ph
        ph = _ph.load_phases()
    except Exception as exc:
        warnings.append(f"phase-roles validation failed: {exc}")
        return warnings

    # 1. Every phase with work.prompt must have a role entry
    for phase in ph.ordered:
        if not phase.prompt:
            continue
        # Check prompt file exists
        prompt_path = fw / phase.prompt
        if not prompt_path.exists():
            warnings.append(
                f"models.yml: work.prompt file missing: {phase.prompt} "
                f"(phase {phase.id!r})"
            )
        # Check phase_roles coverage (or per_track coverage for all tracks)
        if phase.id in phase_roles:
            continue
        # Check if every track for this phase has a per_track override
        covered_tracks = set(per_track.get(t, {}).keys() for t in phase.tracks
                              if phase.id in per_track.get(t, {}))
        uncovered = [t for t in phase.tracks
                     if phase.id not in per_track.get(t, {})]
        if uncovered:
            warnings.append(
                f"models.yml: phase {phase.id!r} has work.prompt but no "
                f"phase_roles entry (uncovered tracks: {uncovered})"
            )

    # 2. Every per_track phase reference must exist in phases.yml.
    # Pseudo-phases (indexing, review-external) are intentional and not in
    # phases.yml — skip them.
    _PSEUDO_PHASES = {"indexing", "review-external", "review-internal", "review-cheap"}
    phase_ids = {p.id for p in ph.ordered}
    for track, overrides in per_track.items():
        if not isinstance(overrides, dict):
            continue
        for phase_id in overrides:
            if phase_id in _PSEUDO_PHASES:
                continue
            if phase_id not in phase_ids:
                warnings.append(
                    f"models.yml: per_track.{track}.{phase_id!r} references "
                    f"unknown phase"
                )

    return warnings


def validate_condition_syntax(config_dir: Path) -> list[str]:
    """Check that all condition: expressions in phases.yml are recognised syntax."""
    warnings: list[str] = []
    try:
        fw = _p.framework_root()
        sys.path.insert(0, str(fw / "core" / "skills"))
        import phases as _ph
        ph = _ph.load_phases()
    except Exception as exc:
        warnings.append(f"condition syntax validation failed: {exc}")
        return warnings

    for phase in ph.ordered:
        if phase.condition is None:
            continue
        try:
            import phases as _ph2
            if not _ph2._is_known_condition(phase.condition):
                warnings.append(
                    f"phases.yml: phase {phase.id!r} has unrecognised "
                    f"condition syntax: {phase.condition!r}"
                )
        except Exception as exc:
            warnings.append(
                f"phases.yml: phase {phase.id!r} condition check failed: {exc}"
            )
    return warnings


def validate_all(config_dir: Path | None = None) -> list[str]:
    """Validate all config files in the config directory.

    Args:
        config_dir: Config directory to validate (defaults to framework config/)

    Returns:
        List of warning messages (empty if all valid)
    """
    if config_dir is None:
        config_dir = _p.framework_root() / "config"

    warnings = []

    # Find all YAML files
    for config_file in sorted(config_dir.glob("*.yml")):
        file_warnings = validate_file(config_file)
        warnings.extend(file_warnings)

    for config_file in sorted(config_dir.glob("*.yaml")):
        file_warnings = validate_file(config_file)
        warnings.extend(file_warnings)

    warnings.extend(validate_phase_roles(config_dir))
    warnings.extend(validate_condition_syntax(config_dir))

    return warnings


def main() -> int:
    """CLI entry point for testing."""
    warnings = validate_all()

    if warnings:
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)
        return 1
    else:
        print("All config files valid.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
