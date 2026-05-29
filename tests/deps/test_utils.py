#!/usr/bin/env python3
"""Tests for core.deps utility functions (step-1)."""
from __future__ import annotations

import platform
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

# Add core/deps to sys.path
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core"))

from deps import platform_tag, _has, _check, _check_python_lib  # noqa: E402


class TestDepsUtils(unittest.TestCase):
    """Test suite for core.deps utility functions."""

    def test_platform_detection(self):
        """Test platform_tag returns correct OS tag."""
        result = platform_tag()
        self.assertIn(result, ("linux", "macos", "windows", "unknown"))

        # Verify it matches platform.system()
        sys_name = platform.system()
        if sys_name == "Linux":
            self.assertEqual(result, "linux")
        elif sys_name == "Darwin":
            self.assertEqual(result, "macos")
        elif sys_name == "Windows":
            self.assertEqual(result, "windows")

    def test_has_tool_present(self):
        """Test _has finds a tool that exists on PATH."""
        # Python should always be available in test environment
        result = _has("python3") or _has("python")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Path)

    def test_has_tool_missing(self):
        """Test _has returns None for nonexistent tool."""
        result = _has("nonexistent-tool-xyz123")
        self.assertIsNone(result)

    @mock.patch("deps.shutil.which")
    @mock.patch("deps.log")
    @mock.patch("deps.warn")
    def test_check_helper_found(self, mock_warn, mock_log, mock_which):
        """Test _check helper when tool is found."""
        mock_which.return_value = "/usr/bin/git"

        missing = []
        suggestions = []
        result = _check(missing, suggestions, name="git", hint="install git")

        self.assertTrue(result)
        self.assertEqual(len(missing), 0)
        self.assertEqual(len(suggestions), 0)
        mock_log.assert_called_once()
        mock_warn.assert_not_called()

    @mock.patch("deps.shutil.which")
    @mock.patch("deps.log")
    @mock.patch("deps.warn")
    def test_check_helper_missing(self, mock_warn, mock_log, mock_which):
        """Test _check helper when tool is missing."""
        mock_which.return_value = None

        missing = []
        suggestions = []
        result = _check(missing, suggestions, name="nonexistent", hint="install it")

        self.assertFalse(result)
        self.assertIn("nonexistent", missing)
        self.assertEqual(len(suggestions), 1)
        self.assertIn("install it", suggestions[0])
        mock_log.assert_not_called()
        mock_warn.assert_called_once()

    @mock.patch("deps.shutil.which")
    @mock.patch("deps.log")
    def test_check_helper_alt_names(self, mock_log, mock_which):
        """Test _check helper with alternative names."""
        # First call returns None (ast-grep not found), second returns path (sg found)
        mock_which.side_effect = [None, "/usr/local/bin/sg"]

        missing = []
        suggestions = []
        result = _check(missing, suggestions, name="ast-grep", hint="install ast-grep",
                       alt_names=("sg",))

        self.assertTrue(result)
        self.assertEqual(len(missing), 0)
        # Should check ast-grep first, then sg
        self.assertEqual(mock_which.call_count, 2)

    @mock.patch("builtins.__import__")
    @mock.patch("deps.log")
    def test_check_python_lib_found(self, mock_log, mock_import):
        """Test _check_python_lib when module is importable."""
        mock_import.return_value = None  # successful import

        missing = []
        suggestions = []
        result = _check_python_lib(missing, suggestions, module="jinja2",
                                   install_hint="pip install jinja2")

        self.assertTrue(result)
        self.assertEqual(len(missing), 0)
        mock_log.assert_called_once()

    @mock.patch("builtins.__import__")
    @mock.patch("deps.warn")
    def test_check_python_lib_missing(self, mock_warn, mock_import):
        """Test _check_python_lib when module is not importable."""
        mock_import.side_effect = ImportError("No module named 'nonexistent'")

        missing = []
        suggestions = []
        result = _check_python_lib(missing, suggestions, module="nonexistent",
                                   install_hint="pip install nonexistent")

        self.assertFalse(result)
        self.assertIn("nonexistent", missing)
        self.assertEqual(len(suggestions), 1)
        mock_warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
