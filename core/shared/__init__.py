"""
Shared utilities for klc framework.

This module contains common helpers used across skills, phases, and scripts:
- yaml: YAML loading, validation, merging
- paths: Path resolution and normalization
- artefacts: Artefact writing with frontmatter, locking

Extracted from core/skills/ to eliminate duplication (KLC-007).
"""

__version__ = "0.1.0"
