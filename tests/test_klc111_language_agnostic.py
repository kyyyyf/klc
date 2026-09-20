"""KLC-111 step-3 — every new rule and default derives from the deterministic
directory builder and configured path prefixes only (AC-19). A fixed grep
(design D-012) over the new settings default, the new schema entry and the
mapper source for a fixed language-marker list — extension names, language
names, and language-specific directory conventions. `README.md` is not a
violation: it is an exact repo-relative path AC-1 requires verbatim, not a
language marker.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_MARKER_WORDS = ("python", "rust", "cpp", "typescript", "javascript", "go", "java")
_MARKER_EXTS = (".py", ".rs", ".cpp", ".ts", ".tsx", ".h", ".java")
_MARKER_DIRS = ("node_modules", "site-packages", "__pycache__", "src/", "target/")


def _violations(text: str) -> list[str]:
    low = text.lower()
    hits = [w for w in _MARKER_WORDS if re.search(rf"\b{re.escape(w)}\b", low)]
    hits += [e for e in _MARKER_EXTS if re.search(re.escape(e) + r"\b", low)]
    hits += [d for d in _MARKER_DIRS if d in low]
    return hits


def _block(text: str, anchor: str, lines: int) -> str:
    idx = text.index(anchor)
    return "\n".join(text[idx:].splitlines()[:lines])


def test_no_new_rule_or_default_names_a_language_extension_or_language_specific_directory():
    """AC-19: the new settings default (`config/settings.yml`), the new
    schema entry (`validate_config.py`) and the mapper source
    (`module_vocabulary.py`) name no language, no source extension and no
    language-specific directory convention (D-012's fixed marker list)."""
    settings_text = _block(
        (REPO / "config" / "settings.yml").read_text(encoding="utf-8"),
        "# Scope-guard infra paths (KLC-111).", 6)
    schema_text = _block(
        (REPO / "core" / "skills" / "validate_config.py").read_text(encoding="utf-8"),
        "# KLC-111: the scope-guard/discovery-ack infra path list.", 4)
    mapper_text = (REPO / "core" / "skills" / "module_vocabulary.py").read_text(encoding="utf-8")

    for label, text in (("settings default", settings_text),
                        ("schema entry", schema_text),
                        ("mapper source", mapper_text)):
        assert _violations(text) == [], f"{label} names a language marker: {_violations(text)}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
