#!/usr/bin/env python3
"""Tests for scripts/install_deps.py dispatcher (step-4)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

# Add scripts to sys.path
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "scripts"))
sys.path.insert(0, str(FRAMEWORK_ROOT / "core"))


class TestInstallDepsDispatcher(unittest.TestCase):
    """Test suite for install_deps.py CLI dispatcher."""

    @mock.patch("deps.bootstrap.check_bootstrap")
    def test_bootstrap_mode(self, mock_check_bootstrap):
        """Test --bootstrap flag calls bootstrap module (AC-1)."""
        mock_check_bootstrap.return_value = 0

        from install_deps import main
        result = main(["--bootstrap"])

        self.assertEqual(result, 0)
        mock_check_bootstrap.assert_called_once()

    @mock.patch("deps.dev.check_dev")
    def test_dev_mode(self, mock_check_dev):
        """Test --dev flag calls dev module (AC-3)."""
        mock_check_dev.return_value = 0

        from install_deps import main
        result = main(["--dev"])

        self.assertEqual(result, 0)
        mock_check_dev.assert_called_once()

    @mock.patch("deps.project.check_project")
    def test_backward_compat(self, mock_check_project):
        """Test backward compatibility: no flags = project mode."""
        mock_check_project.return_value = 0

        from install_deps import main
        result = main([])

        self.assertEqual(result, 0)
        mock_check_project.assert_called_once()


if __name__ == "__main__":
    unittest.main()
