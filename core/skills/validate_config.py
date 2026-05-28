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
        "reports",           # report generation config
    },
    "jira.yml": {
        "url_template",  # Jira URL template
        "sync",          # sync configuration
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
