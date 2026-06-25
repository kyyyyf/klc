#!/usr/bin/env python3
"""Unit tests for language detection threshold boundary cases (TEST-1)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))


class TestLanguageDetectionThreshold(unittest.TestCase):
    """Test FILE_COUNT_THRESHOLD boundary cases."""

    def setUp(self):
        """Create temp directories for testing."""
        self.tempdir = tempfile.mkdtemp(prefix="klc-test-threshold-")
        self.project_root = Path(self.tempdir)
        self.klc_dir = self.project_root / ".klc"
        self.klc_dir.mkdir()
        (self.klc_dir / "index").mkdir()
        (self.klc_dir / "config").mkdir()

        # Mock klc_index_dir to use temp directory
        import detect_languages
        self.original_klc_index_dir = detect_languages.klc_index_dir
        detect_languages.klc_index_dir = lambda: self.klc_dir / "index"

    def tearDown(self):
        """Clean up temp directories and restore mocks."""
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

        import detect_languages
        detect_languages.klc_index_dir = self.original_klc_index_dir

    def test_threshold_below_9_files_not_detected(self):
        """Test 9 Python files (below threshold=10) - should NOT detect."""
        from detect_languages import detect

        inventory = {"extensions": {".py": 9}}
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        languages = detect()
        self.assertNotIn("python", languages, "9 files should be below threshold")

    def test_threshold_at_10_files_detected(self):
        """Test 10 Python files (at threshold=10) - SHOULD detect."""
        from detect_languages import detect

        inventory = {"extensions": {".py": 10}}
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        languages = detect()
        self.assertIn("python", languages, "10 files should be at threshold boundary")

    def test_threshold_above_11_files_detected(self):
        """Test 11 Python files (above threshold=10) - SHOULD detect."""
        from detect_languages import detect

        inventory = {"extensions": {".py": 11}}
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        languages = detect()
        self.assertIn("python", languages, "11 files should be above threshold")

    def test_threshold_multiple_languages(self):
        """Test threshold with multiple languages at boundary."""
        from detect_languages import detect

        inventory = {
            "extensions": {
                ".py": 10,   # At threshold - should detect
                ".cpp": 9,   # Below threshold - should NOT detect
                ".ts": 11    # Above threshold - should detect
            }
        }
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        languages = detect()
        self.assertIn("python", languages)
        self.assertIn("typescript", languages)
        self.assertNotIn("cpp", languages)

    @unittest.skip("detect_languages no longer reads profile.yml (profile detection removed)")
    def test_threshold_override_by_profile(self):
        """Test that profile.yml explicit language overrides threshold."""
        from detect_languages import detect

        # Only 5 C++ files (below threshold)
        inventory = {"extensions": {".cpp": 5}}
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # But profile explicitly lists cpp
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\nlanguages:\n  - cpp\n", encoding="utf-8")

        languages = detect()
        self.assertIn("cpp", languages, "Profile should override threshold")


if __name__ == "__main__":
    unittest.main()
