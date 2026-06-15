#!/usr/bin/env python3
"""Integration tests for structured conditional-reviewer trigger evaluation (KLC-025 step-1).

Exercises _evaluate_conditional_trigger() in scripts/review.py:
- enabled_for_tracks gate (AC-1)
- structured triggers list (OR semantics)
- backward-compat single trigger: regex
- dependency_edge_added trigger via modules.json
- $0 pre-spawn gate (AC-5)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _import_review():
    import importlib
    import review as rv
    return rv


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _diff_with(content: str) -> str:
    return (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        f"+{content}\n"
    )


def _modules_json(modules: list[dict]) -> Path:
    tmp = Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps({"modules": modules}), encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# AC-1 / AC-5: track gate + trigger evaluation is a $0 pre-spawn decision
# ---------------------------------------------------------------------------

def test_runs_when_trigger_and_track_sml():
    """Structured trigger fires + track in {S,M,L} → reviewer selected."""
    rv = _import_review()
    entry = {
        "name": "deep-impact",
        "path": "core/agents/review/deep-impact.md",
        "filter": "",
        "enabled_for_tracks": ["S", "M", "L"],
        "triggers": ["changed_public_api"],
    }
    # diff adds a public def
    diff = _diff_with("def my_public_func(x): ...")
    for track in ("S", "M", "L"):
        assert rv._evaluate_conditional_trigger(entry, diff, track, None), \
            f"expected reviewer to be selected for track={track}"


def test_skipped_on_xs():
    """Track=XS → reviewer never selected, even when trigger pattern matches."""
    rv = _import_review()
    entry = {
        "name": "deep-impact",
        "path": "core/agents/review/deep-impact.md",
        "filter": "",
        "enabled_for_tracks": ["S", "M", "L"],
        "triggers": ["changed_public_api"],
    }
    diff = _diff_with("def public_func(): ...")
    assert not rv._evaluate_conditional_trigger(entry, diff, "XS", None)


def test_skipped_when_no_trigger():
    """Track=M but no structured trigger pattern matches → reviewer not selected."""
    rv = _import_review()
    entry = {
        "name": "deep-impact",
        "path": "core/agents/review/deep-impact.md",
        "filter": "",
        "enabled_for_tracks": ["S", "M", "L"],
        "triggers": ["security_sensitive_diff"],
    }
    # diff is a plain variable rename — no security pattern
    diff = _diff_with("x = old_value + 1")
    assert not rv._evaluate_conditional_trigger(entry, diff, "M", None)


def test_gate_is_pre_spawn():
    """_evaluate_conditional_trigger must return without calling any agent.

    This is the $0 gate (AC-5): the decision is made purely from diff text
    and meta.track, without spawning any subprocess or agent.
    """
    rv = _import_review()
    entry = {
        "name": "deep-impact",
        "path": "core/agents/review/deep-impact.md",
        "filter": "",
        "enabled_for_tracks": ["S", "M", "L"],
        "triggers": ["config_or_persistence_change"],
    }
    diff = _diff_with("DATABASE_URL = env('DB_URL')")

    # Patch subprocess.run and os.popen to verify nothing is spawned
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:
        result = rv._evaluate_conditional_trigger(entry, diff, "M", None)
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
    assert result  # the trigger should have matched config pattern


# ---------------------------------------------------------------------------
# Backward compat: plain trigger: regex still works
# ---------------------------------------------------------------------------

def test_legacy_trigger_regex_still_works():
    """A conditional reviewer with a plain trigger: string still fires correctly."""
    rv = _import_review()
    # Old-style entry: single trigger regex string, no enabled_for_tracks
    entry = {
        "name": "legacy-reviewer",
        "path": "core/agents/review/security.md",
        "filter": "",
        "trigger": r"password|secret|token",
    }
    diff_matches = _diff_with("API_KEY = 'my-secret-token'")
    diff_no_match = _diff_with("x = 1 + 2")
    # No enabled_for_tracks → runs on any track when trigger matches
    assert rv._evaluate_conditional_trigger(entry, diff_matches, "XS", None)
    assert not rv._evaluate_conditional_trigger(entry, diff_no_match, "XS", None)


# ---------------------------------------------------------------------------
# dependency_edge_added trigger
# ---------------------------------------------------------------------------

def test_dependency_edge_added_via_graph():
    """diff adds an import of a module in modules.json → trigger fires."""
    rv = _import_review()
    modules_path = _modules_json([
        {"name": "auth", "path": "core/auth", "doc_filename": "CLAUDE.md",
         "depended_by": []},
    ])
    entry = {
        "name": "deep-impact",
        "path": "core/agents/review/deep-impact.md",
        "filter": "",
        "enabled_for_tracks": ["S", "M", "L"],
        "triggers": ["dependency_edge_added"],
    }
    diff = _diff_with("import auth")
    try:
        result = rv._evaluate_conditional_trigger(entry, diff, "M", modules_path)
        assert result, "expected dependency_edge_added trigger to fire"
    finally:
        modules_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# step-2: manifest entry present + _load_reviewers passes through new fields
# ---------------------------------------------------------------------------

def test_manifest_entry_present_and_loads():
    """The deep-impact reviewer entry is in profiles/generic/manifest.yml
    and _load_reviewers returns it with enabled_for_tracks + triggers
    when the generic profile is active."""
    import json as _json
    rv = _import_review()
    # Read the generic manifest directly (no subprocess needed)
    manifest_path = FW_ROOT / "profiles" / "generic" / "manifest.yml"
    assert manifest_path.exists(), "generic manifest not found"
    manifest_text = manifest_path.read_text(encoding="utf-8")

    # Parse via _yaml (same as _load_reviewers does internally)
    sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
    from _yaml import parse as _yml_parse
    manifest = _yml_parse(manifest_text)
    reviewers = manifest.get("reviewers") or {}
    conditional = reviewers.get("conditional") or []

    names = [
        rv._import_review.__module__ if False else  # never, just for type
        (lambda r: r.get("path", "").split("/")[-1].replace(".md", ""))(r)
        for r in conditional
    ]
    # simpler: extract names directly
    names = [r.get("path", "").split("/")[-1].replace(".md", "") for r in conditional]
    assert "deep-impact" in names, \
        f"deep-impact not found in generic manifest conditional; got: {names}"
    di = next(r for r in conditional if "deep-impact" in r.get("path", ""))
    assert di.get("enabled_for_tracks"), "enabled_for_tracks missing from manifest"
    assert "S" in di["enabled_for_tracks"]
    assert "M" in di["enabled_for_tracks"]
    assert "L" in di["enabled_for_tracks"]
    assert di.get("triggers"), "triggers list missing from manifest"

    # Also verify _load_reviewers passes enabled_for_tracks + triggers through
    # by mocking _resolve_profile_field to return the generic manifest content
    with patch.object(rv, "_resolve_profile_field") as mock_resolve:
        def _side_effect(field):
            if field == "reviewers":
                return _json.dumps(reviewers)
            return ""
        mock_resolve.side_effect = _side_effect
        _, loaded = rv._load_reviewers()
    di_loaded = next((r for r in loaded if r["name"] == "deep-impact"), None)
    assert di_loaded is not None, "_load_reviewers did not return deep-impact entry"
    assert di_loaded.get("enabled_for_tracks"), \
        "_load_reviewers did not pass through enabled_for_tracks"
    assert di_loaded.get("triggers"), \
        "_load_reviewers did not pass through triggers"


def test_legacy_trigger_entry_still_resolves():
    """A single-trigger: entry in the manifest resolves without enabled_for_tracks."""
    rv = _import_review()
    # Synthesize a conditional entry in old-style format
    entry = {
        "name": "old-style",
        "path": "core/agents/review/security.md",
        "filter": "",
        "trigger": r"secret|password",
    }
    diff_match = _diff_with("secret_key = 'abc'")
    diff_no = _diff_with("x = 1")
    assert rv._evaluate_conditional_trigger(entry, diff_match, "XS", None)
    assert not rv._evaluate_conditional_trigger(entry, diff_no, "XS", None)


def test_dependency_edge_added_inert_on_stub_graph():
    """dependency_edge_added trigger is inert (no error) when modules.json is empty/unavailable (C-003)."""
    rv = _import_review()
    entry = {
        "name": "deep-impact",
        "path": "core/agents/review/deep-impact.md",
        "filter": "",
        "enabled_for_tracks": ["S", "M", "L"],
        "triggers": ["dependency_edge_added"],
    }
    diff = _diff_with("import something")
    # modules_path=None → inert, no error
    result = rv._evaluate_conditional_trigger(entry, diff, "M", None)
    assert not result  # inert on missing graph

    # also test with an empty modules list
    empty_modules = _modules_json([])
    try:
        result2 = rv._evaluate_conditional_trigger(entry, diff, "M", empty_modules)
        assert not result2
    finally:
        empty_modules.unlink(missing_ok=True)
