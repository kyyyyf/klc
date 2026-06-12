#!/usr/bin/env python3
"""Integration tests for review_cascade.py.

Tests that:
- A peripheral-only diff with no sentinels → cheap review (use_full_review=False)
- A diff with a sentinel hit → full review
- A diff with critical-tier files → full review
- Cascade disabled in config → full review
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _make_diff(files: list[str], added_lines_per_file: int = 1) -> Path:
    """Write a minimal unified diff touching the given file paths."""
    tmp = Path(tempfile.mktemp(suffix=".patch"))
    lines = []
    for f in files:
        count = added_lines_per_file
        lines += [
            f"diff --git a/{f} b/{f}",
            f"--- a/{f}",
            f"+++ b/{f}",
            f"@@ -1,{count} +1,{count} @@",
        ]
        for i in range(count):
            lines.append(f"-old line {i}")
        for i in range(count):
            lines.append(f"+new line {i}")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp


def _make_meta(ticket: str, scratch: Path, modules: list[str] | None = None) -> None:
    """Write minimal meta.json for a ticket in scratch/.klc/tickets/."""
    tdir = scratch / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:work",
        "phase_history": [],
        "track": "S", "estimate": None, "layer": "code",
        "affected_modules": modules or [],
        "created": "2026-06-04T00:00:00Z", "owner": "test",
        "jira_url": None, "links": [], "rework_count": {}, "metrics": {}
    }
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )


def test_peripheral_diff_gets_cheap_review() -> None:
    """Peripheral diff with no sentinels → use_full_review=False."""
    import review_cascade as rc

    diff = _make_diff(["docs/readme.md", "docs/changelog.md"])
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            scratch = Path(scratch_str)
            _make_meta("T-001", scratch)

            # Patch classify_tier to return all-peripheral, scan_sentinels to 0 hits,
            # scope_delta to no expansion/drift.
            with patch.object(rc, "_get_file_tiers",
                              return_value={"docs/readme.md": "peripheral",
                                            "docs/changelog.md": "peripheral"}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=0), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": []}):

                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-001", diff)

        assert not decision.use_full_review, (
            f"expected cheap review for peripheral diff, got: {decision.reason}"
        )
        assert decision.tier == "peripheral"
        assert decision.sentinel_hits == 0
        print("PASS: peripheral diff → cheap review")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_sentinel_hit_forces_full_review() -> None:
    """Any sentinel hit → use_full_review=True."""
    import review_cascade as rc

    diff = _make_diff(["src/api/eval_endpoint.py"])
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            scratch = Path(scratch_str)
            _make_meta("T-002", scratch)

            with patch.object(rc, "_get_file_tiers",
                              return_value={"src/api/eval_endpoint.py": "peripheral"}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=1), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": []}):

                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-002", diff)

        assert decision.use_full_review, (
            f"expected full review for sentinel hit, got: {decision.reason}"
        )
        assert decision.sentinel_hits == 1
        print("PASS: sentinel hit → full review")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_critical_tier_forces_full_review() -> None:
    """Critical-tier file in diff → use_full_review=True."""
    import review_cascade as rc

    diff = _make_diff(["src/auth/jwt.py"])
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            scratch = Path(scratch_str)
            _make_meta("T-003", scratch)

            with patch.object(rc, "_get_file_tiers",
                              return_value={"src/auth/jwt.py": "critical"}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=0), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": []}):

                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-003", diff)

        assert decision.use_full_review, (
            f"expected full review for critical tier, got: {decision.reason}"
        )
        assert decision.tier == "critical"
        print("PASS: critical-tier file → full review")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_cascade_disabled_forces_full_review() -> None:
    """cascade.enabled=false → always full review."""
    import review_cascade as rc

    diff = _make_diff(["docs/readme.md"])
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            _make_meta("T-004", Path(scratch_str))
            with patch.object(rc, "_load_cascade_config",
                              return_value={"enabled": False}):
                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-004", diff)

        assert decision.use_full_review
        assert "disabled" in decision.reason
        print("PASS: cascade disabled → full review")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_empty_file_tiers_forces_full_review() -> None:
    """Empty file_tiers (classifier failed) → fail-closed = full review."""
    import review_cascade as rc

    diff = _make_diff(["docs/readme.md"])
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            _make_meta("T-005", Path(scratch_str))
            with patch.object(rc, "_get_file_tiers", return_value={}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=0), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": []}):
                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-005", diff)

        assert decision.use_full_review, (
            f"expected full review for empty tiers, got: {decision.reason}"
        )
        assert "classifier" in decision.reason.lower() or "no file" in decision.reason.lower()
        print("PASS: empty file_tiers → full review (fail-closed)")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_skipped_scope_forces_full_review() -> None:
    """Skipped scope comparison → fail-closed = full review."""
    import review_cascade as rc

    diff = _make_diff(["docs/readme.md"])
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            _make_meta("T-006", Path(scratch_str))
            with patch.object(rc, "_get_file_tiers",
                              return_value={"docs/readme.md": "peripheral"}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=0), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": [],
                                     "skipped": "modules.json not found"}):
                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-006", diff)

        assert decision.use_full_review, (
            f"expected full review for skipped scope, got: {decision.reason}"
        )
        print("PASS: skipped scope → full review (fail-closed)")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_large_line_count_forces_full_review() -> None:
    """Peripheral diff, few files but > peripheral_max_lines → full review."""
    import review_cascade as rc

    # 2 peripheral files, 300 added + 300 removed lines each = 1200 total changed lines
    diff = _make_diff(["docs/guide.md", "docs/api.md"], added_lines_per_file=300)
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            scratch = Path(scratch_str)
            _make_meta("T-007", scratch)

            with patch.object(rc, "_get_file_tiers",
                              return_value={"docs/guide.md": "peripheral",
                                            "docs/api.md": "peripheral"}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=0), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": []}), \
                 patch.object(rc, "_load_cascade_config",
                              return_value={"enabled": True,
                                            "peripheral_max_files": 20,
                                            "peripheral_max_lines": 500}):

                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-007", diff)

        assert decision.use_full_review, (
            f"expected full review for large line count, got: {decision.reason}"
        )
        assert "line" in decision.reason.lower(), (
            f"expected 'line' in reason, got: {decision.reason}"
        )
        print("PASS: large line count → full review")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


def test_cheap_reason_contains_file_and_line_counts() -> None:
    """Cheap path reason must contain file count and line count."""
    import review_cascade as rc

    diff = _make_diff(["docs/readme.md", "docs/changelog.md"], added_lines_per_file=5)
    try:
        with tempfile.TemporaryDirectory() as scratch_str:
            scratch = Path(scratch_str)
            _make_meta("T-008", scratch)

            with patch.object(rc, "_get_file_tiers",
                              return_value={"docs/readme.md": "peripheral",
                                            "docs/changelog.md": "peripheral"}), \
                 patch.object(rc, "_get_sentinel_hits", return_value=0), \
                 patch("scope_delta.compare",
                       return_value={"planned": [], "actual": [],
                                     "drift": [], "expansion": []}), \
                 patch.object(rc, "_load_cascade_config",
                              return_value={"enabled": True,
                                            "peripheral_max_files": 20,
                                            "peripheral_max_lines": 500}):

                os.environ["PROJECT_ROOT"] = scratch_str
                decision = rc.decide("T-008", diff)

        assert not decision.use_full_review, (
            f"expected cheap review, got: {decision.reason}"
        )
        # Reason must include "N files" and "M lines"
        assert "files" in decision.reason and "lines" in decision.reason, (
            f"expected file+line counts in cheap reason, got: {decision.reason}"
        )
        print(f"PASS: cheap reason = {decision.reason!r}")
    finally:
        diff.unlink(missing_ok=True)
        os.environ.pop("PROJECT_ROOT", None)


if __name__ == "__main__":
    test_peripheral_diff_gets_cheap_review()
    test_sentinel_hit_forces_full_review()
    test_critical_tier_forces_full_review()
    test_cascade_disabled_forces_full_review()
    test_empty_file_tiers_forces_full_review()
    test_skipped_scope_forces_full_review()
    test_large_line_count_forces_full_review()
    test_cheap_reason_contains_file_and_line_counts()
    print("ALL CASCADE TESTS PASSED")
