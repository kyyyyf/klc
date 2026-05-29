#!/usr/bin/env python3
"""Integration tests for klc init output hints (step-7)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent


class TestInitIntegration(unittest.TestCase):
    """Integration tests for klc init output with setup hints."""

    def setUp(self):
        """Create temp project directory."""
        self.tempdir = tempfile.mkdtemp(prefix="klc-test-init-")
        self.project_root = Path(self.tempdir)

        # Initialize git repo (required by klc init)
        subprocess.run(["git", "init"], cwd=str(self.project_root),
                      capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(self.project_root),
                      capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(self.project_root),
                      capture_output=True)

        # Create dummy commit (required for git rev-parse HEAD)
        (self.project_root / "dummy.txt").write_text("test", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root),
                      capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=str(self.project_root),
                      capture_output=True)

        # Set PROJECT_ROOT for subprocesses
        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.project_root)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_init_scan_only_prints_setup_hint(self):
        """Test that klc init --scan-only prints 'Next: klc setup' hint."""
        # Run klc install first
        subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "install", str(self.project_root)],
            capture_output=True,
            check=True
        )

        # Create dummy Python file for scanning
        (self.project_root / "test.py").write_text("# test", encoding="utf-8")

        # Run klc init --scan-only
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--scan-only"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Verify exit code
        self.assertEqual(result.returncode, 0, f"init --scan-only failed: {result.stderr}")

        # Verify output contains setup hint
        output = result.stdout + result.stderr
        self.assertIn("Next steps:", output)
        self.assertIn("klc setup", output)
        self.assertIn("klc doctor", output)

    def test_init_finalize_prints_setup_hint(self):
        """Test that klc init --finalize also prints setup hint."""
        # Run klc install
        subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "install", str(self.project_root)],
            capture_output=True,
            check=True
        )

        # Create .klc/index directory
        (self.project_root / ".klc" / "index").mkdir(parents=True, exist_ok=True)

        # Run klc init --finalize
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--finalize"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Verify exit code
        self.assertEqual(result.returncode, 0)

        # Verify output contains setup hint
        output = result.stdout + result.stderr
        self.assertIn("Next steps:", output)
        self.assertIn("klc setup", output)


if __name__ == "__main__":
    unittest.main()
