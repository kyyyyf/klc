#!/usr/bin/env python3
"""Integration tests for klc doctor with project-tools check (step-6)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent


class TestDoctorIntegration(unittest.TestCase):
    """Integration tests for klc doctor project-tools validation."""

    def setUp(self):
        """Create temp project directory."""
        self.tempdir = tempfile.mkdtemp(prefix="klc-test-doctor-")
        self.project_root = Path(self.tempdir)
        self.klc_dir = self.project_root / ".klc"
        self.klc_dir.mkdir()
        (self.klc_dir / "index").mkdir()
        (self.klc_dir / "config").mkdir()
        (self.klc_dir / "logs").mkdir()

        # Copy essential config files
        import shutil
        shutil.copy(FRAMEWORK_ROOT / "config" / "phases.yml",
                   self.klc_dir / "config" / "phases.yml")
        shutil.copy(FRAMEWORK_ROOT / "config" / "models.yml",
                   self.klc_dir / "config" / "models.yml")

        # Create minimal profile
        profile_yml = self.klc_dir / "config" / "profile.yml"
        profile_yml.write_text("profile: generic\n", encoding="utf-8")

        # Initialize git repo (required by git-available check)
        subprocess.run(["git", "init"], cwd=str(self.project_root),
                      capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(self.project_root),
                      capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(self.project_root),
                      capture_output=True)

        # Set PROJECT_ROOT for subprocesses
        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.project_root)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_doctor_without_project_deps(self):
        """Test klc doctor when project-deps.json doesn't exist (graceful skip)."""
        # No project-deps.json created
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "doctor"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Should exit 0 (project-tools check skipped gracefully)
        self.assertEqual(result.returncode, 0)
        self.assertIn("DOCTOR_OK", result.stdout)

    def test_doctor_default_mode_missing_tools(self):
        """Test klc doctor default mode (WARN) with missing tools."""
        # Create project-deps.json with missing tools
        project_deps = {
            "languages": ["python"],
            "required": {
                "python": ["uv", "pylsp"]
            },
            "optional": {},
            "detected": {
                "uv": None,  # missing
                "pylsp": None  # missing
            }
        }
        deps_file = self.klc_dir / "index" / "project-deps.json"
        deps_file.write_text(json.dumps(project_deps), encoding="utf-8")

        # Run klc doctor (default mode, no --strict)
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "doctor"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Should exit 0 (warnings don't fail doctor)
        self.assertEqual(result.returncode, 0)
        self.assertIn("WARN", result.stdout)
        self.assertIn("project-tools", result.stdout)
        self.assertIn("uv", result.stdout)
        self.assertIn("pylsp", result.stdout)
        self.assertIn("DOCTOR_OK", result.stdout)

    def test_doctor_strict_mode_missing_tools(self):
        """Test klc doctor --strict mode (FAIL) with missing tools."""
        # Create project-deps.json with missing tools
        project_deps = {
            "languages": ["python"],
            "required": {
                "python": ["uv", "pylsp"]
            },
            "optional": {},
            "detected": {
                "uv": None,
                "pylsp": None
            }
        }
        deps_file = self.klc_dir / "index" / "project-deps.json"
        deps_file.write_text(json.dumps(project_deps), encoding="utf-8")

        # Run klc doctor --strict
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "doctor", "--strict"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Should exit 1 (strict mode fails on missing tools)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("project-tools", result.stdout)
        self.assertIn("DOCTOR_FAIL", result.stdout)

    def test_doctor_all_tools_present(self):
        """Test klc doctor when all required tools are present."""
        # Create project-deps.json with all tools present
        project_deps = {
            "languages": ["python"],
            "required": {
                "python": ["python3"]  # Use python3 which should be available in test env
            },
            "optional": {},
            "detected": {
                "python3": "/usr/bin/python3"  # present
            }
        }
        deps_file = self.klc_dir / "index" / "project-deps.json"
        deps_file.write_text(json.dumps(project_deps), encoding="utf-8")

        # Run klc doctor
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "doctor"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Should exit 0
        self.assertEqual(result.returncode, 0)
        self.assertIn("PASS", result.stdout)
        self.assertIn("project-tools", result.stdout)
        self.assertIn("DOCTOR_OK", result.stdout)

    def test_doctor_existing_checks_still_pass(self):
        """Test that all 9 existing checks still work (regression test)."""
        # Run klc doctor
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "doctor"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Verify existing checks present
        expected_checks = [
            "skills-executable",
            "phase-scripts-executable",
            "templates-parse",
            "profile-manifest",
            "git-available",
            "klc-dispatcher",
            "config-validation",
            "project-tools"  # new check
        ]

        for check in expected_checks:
            self.assertIn(check, result.stdout, f"Check {check} not found in doctor output")


if __name__ == "__main__":
    unittest.main()
