#!/usr/bin/env python3
"""Tests for scripts/install_deps.py dispatcher (step-4)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add scripts to sys.path
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "scripts"))
sys.path.insert(0, str(FRAMEWORK_ROOT / "core"))


class TestInstallDepsDispatcher(unittest.TestCase):
    """Test suite for install_deps.py CLI dispatcher.

    KLC-136 step-9: every mode `install_deps.main()` dispatches to first
    does an UNCONDITIONAL `klc_dir().mkdir(exist_ok=True)` /
    `log_init(...)` (itself another `mkdir(exist_ok=True)`) before the
    mocked-out mode function ever runs. `exist_ok=True` makes this
    invisible on a checkout where that directory already exists (D-204: no
    state change) — it silently creates the LIVE or unset-fallback guarded
    root the FIRST time it does not (confirmed live: the operator's AC-9
    PROJECT_ROOT-unset full-suite run caught `test_backward_compat` doing
    exactly this against a fresh scratch clone's fallback root). `setUp`/
    `tearDown` redirect `PROJECT_ROOT` to a fresh scratch dir for every
    test in this class, same as `monkeypatch.setenv` would for a plain
    pytest function — `unittest.TestCase` methods cannot take the
    `monkeypatch` fixture as a parameter, so this uses the manual
    save/restore form instead.
    """

    def setUp(self):
        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self._scratch = tempfile.mkdtemp(prefix="klc-install-deps-test-")
        os.environ["PROJECT_ROOT"] = self._scratch

    def tearDown(self):
        if self._orig_project_root is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        shutil.rmtree(self._scratch, ignore_errors=True)

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
