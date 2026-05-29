#!/usr/bin/env python3
"""Tests for core.deps.bootstrap module (step-2)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

# Add core to sys.path
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core"))

from deps.bootstrap import check_bootstrap  # noqa: E402


class TestBootstrap(unittest.TestCase):
    """Test suite for bootstrap dependency checks."""

    @mock.patch("deps.bootstrap._check")
    @mock.patch("deps.bootstrap._check_python_lib")
    @mock.patch("deps.bootstrap.log")
    def test_bootstrap_all_present(self, mock_log, mock_check_lib, mock_check):
        """Test check_bootstrap when all dependencies present."""
        # Mock Python version check (already 3.11+, so no mocking needed for sys.version_info)
        mock_check.return_value = True  # git present
        mock_check_lib.return_value = True  # jinja2 present

        result = check_bootstrap()

        self.assertEqual(result, 0)
        mock_check.assert_called_once()  # git
        mock_check_lib.assert_called_once()  # jinja2

    @mock.patch("deps.bootstrap._check")
    @mock.patch("deps.bootstrap._check_python_lib")
    @mock.patch("deps.bootstrap.err")
    def test_bootstrap_git_missing(self, mock_err, mock_check_lib, mock_check):
        """Test check_bootstrap when git is missing."""
        def mock_check_side_effect(missing, suggestions, **kwargs):
            missing.append("git")
            suggestions.append("git: install git")
            return False

        mock_check.side_effect = mock_check_side_effect
        mock_check_lib.return_value = True  # jinja2 present

        result = check_bootstrap()

        self.assertEqual(result, 1)
        mock_err.assert_called()  # error messages printed

    @mock.patch("deps.bootstrap._check")
    @mock.patch("deps.bootstrap._check_python_lib")
    @mock.patch("deps.bootstrap.err")
    def test_bootstrap_jinja2_missing(self, mock_err, mock_check_lib, mock_check):
        """Test check_bootstrap when jinja2 is missing."""
        def mock_check_lib_side_effect(missing, suggestions, **kwargs):
            missing.append("jinja2")
            suggestions.append("jinja2: pip install jinja2")
            return False

        mock_check.return_value = True  # git present
        mock_check_lib.side_effect = mock_check_lib_side_effect

        result = check_bootstrap()

        self.assertEqual(result, 1)
        mock_err.assert_called()

    @mock.patch("sys.version_info", new=(3, 10, 0, "final", 0))
    @mock.patch("deps.bootstrap._check")
    @mock.patch("deps.bootstrap._check_python_lib")
    @mock.patch("deps.bootstrap.warn")
    @mock.patch("deps.bootstrap.err")
    def test_python_version_too_old(self, mock_err, mock_warn, mock_check_lib, mock_check):
        """Test check_bootstrap when Python version < 3.11."""
        mock_check.return_value = True  # git present
        mock_check_lib.return_value = True  # jinja2 present

        result = check_bootstrap()

        self.assertEqual(result, 1)
        mock_warn.assert_called()  # warning about Python version
        mock_err.assert_called()  # error summary

    @mock.patch("deps.bootstrap._check")
    @mock.patch("deps.bootstrap._check_python_lib")
    @mock.patch("deps.bootstrap.err")
    def test_bootstrap_all_missing(self, mock_err, mock_check_lib, mock_check):
        """Test check_bootstrap when all dependencies missing."""
        def mock_check_side_effect(missing, suggestions, **kwargs):
            missing.append("git")
            suggestions.append("git: install git")
            return False

        def mock_check_lib_side_effect(missing, suggestions, **kwargs):
            missing.append("jinja2")
            suggestions.append("jinja2: pip install jinja2")
            return False

        mock_check.side_effect = mock_check_side_effect
        mock_check_lib.side_effect = mock_check_lib_side_effect

        result = check_bootstrap()

        self.assertEqual(result, 1)
        # Should have called err multiple times (summary + suggestions)
        self.assertGreater(mock_err.call_count, 1)


if __name__ == "__main__":
    unittest.main()
