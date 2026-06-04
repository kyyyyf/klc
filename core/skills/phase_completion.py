#!/usr/bin/env python3
"""phase_completion.py — artifact-based phase completion detection.

Default behaviour: for any phase that declares `outputs` in phases.yml,
check that every listed output file exists and is non-empty.

Discovery and acceptance-test-plan additionally validate frontmatter and
section structure to catch truncated or stub artefacts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
from core.shared.paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402


def can_complete_discovery(ticket: str) -> tuple[bool, str]:
    """Check if discovery phase artifacts are complete for manual ack.

    Returns:
        (success, error_message)
        success=True: artifacts complete, can advance to ack-needed
        success=False: missing artifacts, error_message describes what's missing
    """
    ticket_dir = klc_ticket_meta_file(ticket).parent
    spec_path = ticket_dir / "spec.md"

    # Check spec.md exists
    if not spec_path.exists():
        return False, "Missing spec.md"

    # Check spec.md has valid frontmatter
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
        lines = spec_text.splitlines()

        # Must start with ---
        if not lines or lines[0].strip() != "---":
            return False, "spec.md: missing frontmatter (must start with '---')"

        # Find closing ---
        frontmatter_end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                frontmatter_end = i
                break

        if frontmatter_end is None:
            return False, "spec.md: incomplete frontmatter (no closing '---')"

        # Parse frontmatter for required fields
        frontmatter = {}
        for line in lines[1:frontmatter_end]:
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()

        # Check ticket field matches
        spec_ticket = frontmatter.get("ticket", "")
        if spec_ticket != ticket:
            return False, f"spec.md: ticket field '{spec_ticket}' doesn't match directory '{ticket}'"

        # Check required frontmatter fields
        required_fields = ["kind", "authority"]
        for field in required_fields:
            if not frontmatter.get(field):
                return False, f"spec.md: missing frontmatter field '{field}'"

        # Check required sections exist
        content = "\n".join(lines[frontmatter_end+1:])
        required_sections = ["## Goals", "## Acceptance Criteria", "## Estimate"]
        for section in required_sections:
            if section not in content:
                return False, f"spec.md: missing required section '{section}'"

    except OSError as e:
        return False, f"Cannot read spec.md: {e}"

    # Check meta.json fields
    try:
        meta = _lc.read_meta(ticket)

        # Check track
        if not meta.get("track"):
            return False, "meta.json: missing 'track' field"

        # Check estimate
        estimate = meta.get("estimate")
        if not estimate:
            return False, "meta.json: missing 'estimate' field"

        # Validate estimate structure
        required_estimate_fields = ["complexity", "uncertainty", "risk", "manual", "total"]
        if not isinstance(estimate, dict):
            return False, "meta.json: 'estimate' must be an object"

        for field in required_estimate_fields:
            if field not in estimate:
                return False, f"meta.json: estimate missing field '{field}'"

        # Check affected_modules (can be empty array, but must exist)
        if "affected_modules" not in meta:
            return False, "meta.json: missing 'affected_modules' field"

        # Check layer
        if not meta.get("layer"):
            return False, "meta.json: missing 'layer' field"

    except Exception as e:
        return False, f"Cannot read/parse meta.json: {e}"

    # All checks passed
    return True, ""


def can_complete_acceptance_test_plan(ticket: str) -> tuple[bool, str]:
    """Check if acceptance-test-plan phase artifacts are complete.

    Returns:
        (success, error_message)
    """
    ticket_dir = klc_ticket_meta_file(ticket).parent
    test_plan_path = ticket_dir / "test-plan.md"

    # Check test-plan.md exists
    if not test_plan_path.exists():
        return False, "Missing test-plan.md"

    # Check test-plan.md has valid frontmatter
    try:
        text = test_plan_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Must start with ---
        if not lines or lines[0].strip() != "---":
            return False, "test-plan.md: missing frontmatter (must start with '---')"

        # Find closing ---
        frontmatter_end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                frontmatter_end = i
                break

        if frontmatter_end is None:
            return False, "test-plan.md: incomplete frontmatter (no closing '---')"

        # Check required sections exist
        content = "\n".join(lines[frontmatter_end+1:])
        required_sections = ["## Acceptance coverage", "## Edge cases"]
        for section in required_sections:
            if section not in content:
                return False, f"test-plan.md: missing required section '{section}'"

    except OSError as e:
        return False, f"Cannot read test-plan.md: {e}"

    # All checks passed
    return True, ""


def can_complete(ticket: str, phase_id: str) -> tuple[bool, str]:
    """Check if a phase can be manually completed based on artifacts.

    Args:
        ticket: ticket key (e.g., "KLC-001")
        phase_id: phase identifier (e.g., "discovery", "build")

    Returns:
        (success, error_message)
    """
    if phase_id == "discovery":
        return can_complete_discovery(ticket)

    if phase_id == "acceptance-test-plan":
        return can_complete_acceptance_test_plan(ticket)

    # Generic check: every output declared in phases.yml must exist and
    # be non-empty.  Phases with no declared outputs pass immediately
    # (e.g. integrate, observe).
    return _can_complete_generic(ticket, phase_id)


def _can_complete_generic(ticket: str, phase_id: str) -> tuple[bool, str]:
    """Check that all phases.yml outputs exist and are non-empty."""
    try:
        ph = _ph.load_phases()
        phase = ph.by_id(phase_id)
    except (KeyError, Exception) as exc:
        return False, f"cannot load phase definition for {phase_id!r}: {exc}"

    if not phase.outputs:
        return True, ""

    ticket_dir = klc_ticket_meta_file(ticket).parent
    for rel in phase.outputs:
        path = ticket_dir / rel
        if not path.exists():
            return False, f"Missing {rel}"
        if path.stat().st_size == 0:
            return False, f"{rel} is empty"

    return True, ""


if __name__ == "__main__":
    # CLI for testing
    import argparse

    ap = argparse.ArgumentParser(description="Check if phase artifacts are complete")
    ap.add_argument("ticket", help="Ticket key")
    ap.add_argument("phase", help="Phase ID (e.g., discovery)")
    args = ap.parse_args()

    success, error = can_complete(args.ticket, args.phase)
    if success:
        print(f"✓ {args.phase} artifacts complete for {args.ticket}")
        sys.exit(0)
    else:
        print(f"✗ {error}", file=sys.stderr)
        sys.exit(1)
