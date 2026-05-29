#!/usr/bin/env python3
"""Tests for core.deps.dev module (step-3)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

# Add core to sys.path
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core"))

from deps.dev import check_dev  # noqa: E402


class TestDev(unittest.TestCase):
    """Test suite for dev dependency checks."""

    @mock.patch("deps.dev._has")
    @mock.patch("deps.dev._check")
    @mock.patch("deps.dev.log")
    def test_check_dev_all_present(self, mock_log, mock_check, mock_has):
        """Test check_dev when all tools present."""
        mock_check.return_value = True  # mutmut, stryker, cargo-mutants
        mock_has.return_value = Path("/usr/bin/mull-runner")  # mull-runner present

        result = check_dev()

        self.assertEqual(result, 0)
        # Should check 3 tools (mutmut, stryker, cargo-mutants)
        self.assertEqual(mock_check.call_count, 3)

    @mock.patch("deps.dev._has")
    @mock.patch("deps.dev._check")
    @mock.patch("deps.dev.err")
    def test_check_dev_mutmut_missing(self, mock_err, mock_check, mock_has):
        """Test check_dev when mutmut is missing."""
        def mock_check_side_effect(missing, suggestions, **kwargs):
            name = kwargs.get("name")
            if name == "mutmut":
                missing.append("mutmut")
                suggestions.append("mutmut: pip install mutmut")
                return False
            return True

        mock_check.side_effect = mock_check_side_effect
        mock_has.return_value = None  # mull-runner advisory, not required

        result = check_dev()

        self.assertEqual(result, 1)
        mock_err.assert_called()

    @mock.patch("deps.dev._has")
    @mock.patch("deps.dev._check")
    @mock.patch("deps.dev.err")
    def test_check_dev_all_missing(self, mock_err, mock_check, mock_has):
        """Test check_dev when all required tools missing."""
        def mock_check_side_effect(missing, suggestions, **kwargs):
            name = kwargs.get("name")
            missing.append(name)
            suggestions.append(f"{name}: install {name}")
            return False

        mock_check.side_effect = mock_check_side_effect
        mock_has.return_value = None  # mull-runner advisory

        result = check_dev()

        self.assertEqual(result, 1)
        # Should have 3 missing tools (mutmut, stryker, cargo-mutants)
        self.assertGreater(mock_err.call_count, 1)

    @mock.patch("deps.dev._has")
    @mock.patch("deps.dev._check")
    @mock.patch("deps.dev.warn")
    @mock.patch("deps.dev.log")
    def test_check_dev_mull_runner_advisory(self, mock_log, mock_warn, mock_check, mock_has):
        """Test that mull-runner is advisory (warning, not error)."""
        mock_check.return_value = True  # all required tools present
        mock_has.return_value = None  # mull-runner missing (advisory)

        result = check_dev()

        # Should still exit 0 (mull-runner is advisory)
        self.assertEqual(result, 0)
        # Should log warning about mull-runner
        mock_warn.assert_called()

    @mock.patch("deps.dev._has")
    @mock.patch("deps.dev._check")
    def test_check_dev_does_not_check_project_tools(self, mock_check, mock_has):
        """Test that check_dev does NOT check project-runtime tools."""
        mock_check.return_value = True
        mock_has.return_value = None

        check_dev()

        # Verify _check was called exactly 3 times (mutmut, stryker, cargo-mutants)
        self.assertEqual(mock_check.call_count, 3)

        # Extract the 'name' arguments from all _check calls
        check_names = [call[1]["name"] for call in mock_check.call_args_list]

        # Verify dev tools are checked
        self.assertIn("mutmut", check_names)
        self.assertIn("stryker", check_names)
        self.assertIn("cargo-mutants", check_names)

        # Verify project-runtime tools are NOT checked
        self.assertNotIn("pylsp", check_names)
        self.assertNotIn("clangd", check_names)
        self.assertNotIn("typescript-language-server", check_names)
        self.assertNotIn("rust-analyzer", check_names)


if __name__ == "__main__":
    unittest.main()
