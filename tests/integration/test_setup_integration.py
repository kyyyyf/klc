#!/usr/bin/env python3
"""Integration tests for klc setup command (step-5).

Tests the full flow: detect_languages → klc setup → project-deps.json creation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent


class TestSetupIntegration(unittest.TestCase):
    """Integration tests for klc setup command."""

    def setUp(self):
        """Create temp project directory."""
        self.tempdir = tempfile.mkdtemp(prefix="klc-test-setup-")
        self.project_root = Path(self.tempdir)
        self.klc_dir = self.project_root / ".klc"
        self.klc_dir.mkdir()
        (self.klc_dir / "index").mkdir()
        (self.klc_dir / "config").mkdir()

        # Set PROJECT_ROOT for subprocesses
        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.project_root)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_setup_python_project(self):
        """Test klc setup on a Python project."""
        # Create inventory.json with Python files
        inventory = {
            "extensions": {
                ".py": 50,
                ".md": 5
            }
        }
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # Create minimal profile.yml
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\n", encoding="utf-8")

        # Run klc setup
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "setup"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Verify exit code
        self.assertEqual(result.returncode, 0, f"klc setup failed: {result.stderr}")

        # Verify output mentions Python
        self.assertIn("python", result.stdout.lower())
        self.assertIn("uv", result.stdout)
        self.assertIn("pylsp", result.stdout)

        # Verify project-deps.json created
        deps_file = self.klc_dir / "index" / "project-deps.json"
        self.assertTrue(deps_file.exists(), "project-deps.json not created")

        # Verify JSON structure
        deps = json.loads(deps_file.read_text(encoding="utf-8"))
        self.assertIn("python", deps["languages"])
        self.assertIn("python", deps["required"])
        self.assertIn("uv", deps["required"]["python"])
        self.assertIn("pylsp", deps["required"]["python"])
        self.assertIn("detected", deps)

    def test_setup_cpp_project(self):
        """Test klc setup on a C++ project."""
        # Create inventory.json with C++ files
        inventory = {
            "extensions": {
                ".cpp": 30,
                ".hpp": 25,
                ".h": 15
            }
        }
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # Create minimal profile.yml
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\n", encoding="utf-8")

        # Run klc setup
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "setup"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        # Verify exit code
        self.assertEqual(result.returncode, 0)

        # Verify output mentions C++
        self.assertIn("cpp", result.stdout.lower())
        self.assertIn("clangd", result.stdout)

        # Verify project-deps.json
        deps_file = self.klc_dir / "index" / "project-deps.json"
        self.assertTrue(deps_file.exists())
        deps = json.loads(deps_file.read_text(encoding="utf-8"))
        self.assertIn("cpp", deps["languages"])
        self.assertIn("clangd", deps["required"]["cpp"])

    def test_setup_mixed_language_project(self):
        """Test klc setup on a project with multiple languages."""
        # Create inventory.json with Python + TypeScript files
        inventory = {
            "extensions": {
                ".py": 40,
                ".ts": 30,
                ".tsx": 20
            }
        }
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\n", encoding="utf-8")

        # Run klc setup
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "setup"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        self.assertEqual(result.returncode, 0)

        # Verify both languages detected
        self.assertIn("python", result.stdout.lower())
        self.assertIn("typescript", result.stdout.lower())

        deps_file = self.klc_dir / "index" / "project-deps.json"
        deps = json.loads(deps_file.read_text(encoding="utf-8"))
        self.assertIn("python", deps["languages"])
        self.assertIn("typescript", deps["languages"])

    def test_setup_empty_project(self):
        """Test klc setup on empty project (no inventory.json)."""
        # No inventory.json created

        # Create minimal profile.yml
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\n", encoding="utf-8")

        # Run klc setup
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "setup"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("No languages detected", result.stdout)

        # project-deps.json should NOT be created
        deps_file = self.klc_dir / "index" / "project-deps.json"
        self.assertFalse(deps_file.exists())

    def test_setup_profile_override(self):
        """Test that profile.yml overrides inventory.json."""
        # Create inventory with many Python files
        inventory = {
            "extensions": {
                ".py": 500,  # Many Python files
                ".cpp": 2    # Few C++ files (below threshold)
            }
        }
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # But profile explicitly says C++ only
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\nlanguages:\n  - cpp\n", encoding="utf-8")

        # Run klc setup
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"), "setup"],
            cwd=str(self.project_root),
            env=self.env,
            capture_output=True,
            text=True
        )

        self.assertEqual(result.returncode, 0)

        # Should detect both python (from inventory) AND cpp (from profile)
        deps_file = self.klc_dir / "index" / "project-deps.json"
        deps = json.loads(deps_file.read_text(encoding="utf-8"))

        # Profile overrides/augments inventory
        self.assertIn("cpp", deps["languages"])


if __name__ == "__main__":
    unittest.main()
