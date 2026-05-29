#!/usr/bin/env python3
"""Unit tests for malformed JSON/YAML error handling in detect_languages (TEST-2)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))


class TestDetectLanguagesMalformed(unittest.TestCase):
    """Test malformed JSON/YAML error handling (TEST-2)."""

    def setUp(self):
        """Create temp directories for testing."""
        self.tempdir = tempfile.mkdtemp(prefix="klc-test-malformed-")
        self.project_root = Path(self.tempdir)
        self.klc_dir = self.project_root / ".klc"
        self.klc_dir.mkdir()
        (self.klc_dir / "index").mkdir()
        (self.klc_dir / "config").mkdir()

        # Mock _paths to use temp directory
        import detect_languages
        self.original_klc_index_dir = detect_languages.klc_index_dir
        self.original_klc_config_dir = detect_languages.klc_config_dir
        detect_languages.klc_index_dir = lambda: self.klc_dir / "index"
        detect_languages.klc_config_dir = lambda: self.klc_dir / "config"

    def tearDown(self):
        """Clean up temp directories and restore mocks."""
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

        # Restore original functions
        import detect_languages
        detect_languages.klc_index_dir = self.original_klc_index_dir
        detect_languages.klc_config_dir = self.original_klc_config_dir

    def test_malformed_inventory_json_graceful_degradation(self):
        """Test that malformed inventory.json is gracefully skipped."""
        from detect_languages import detect

        # Write malformed JSON (missing closing brace)
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text('{"extensions": {".py": 50}', encoding="utf-8")

        # Should not crash, should return empty set (no profile)
        languages = detect()
        self.assertEqual(languages, set(), "Malformed inventory.json should be skipped")

    def test_malformed_inventory_json_with_valid_profile(self):
        """Test that malformed inventory.json doesn't prevent profile.yml from working."""
        from detect_languages import detect

        # Write malformed JSON
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text('{"extensions": invalid json}', encoding="utf-8")

        # Write valid profile.yml
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\nlanguages:\n  - python\n", encoding="utf-8")

        # Should detect python from profile despite malformed inventory
        languages = detect()
        self.assertIn("python", languages, "Profile should work despite malformed inventory")

    def test_inventory_wrong_structure_graceful_degradation(self):
        """Test that inventory.json with wrong structure is gracefully skipped."""
        from detect_languages import detect

        # Write JSON with wrong structure (extensions is array not dict)
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory = {"extensions": [".py", ".cpp"]}  # Should be dict not list
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # Should not crash due to TypeError when iterating
        languages = detect()
        self.assertEqual(languages, set(), "Wrong structure should be skipped")

    def test_malformed_profile_yaml_graceful_degradation(self):
        """Test that malformed profile.yml is gracefully skipped."""
        from detect_languages import detect

        # Write valid inventory with 20 Python files
        inventory = {"extensions": {".py": 20}}
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # Write malformed YAML (invalid indentation)
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\nlanguages:\n- cpp\n  - rust\n", encoding="utf-8")

        # Should still detect python from inventory despite malformed profile
        languages = detect()
        self.assertIn("python", languages, "Inventory should work despite malformed profile")
        # Should NOT include cpp/rust since profile parsing failed
        self.assertNotIn("cpp", languages)
        self.assertNotIn("rust", languages)

    def test_profile_yaml_missing_import_graceful_degradation(self):
        """Test graceful degradation when PyYAML not installed."""
        from detect_languages import detect
        import sys

        # Write valid inventory
        inventory = {"extensions": {".py": 20}}
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        # Write valid profile
        profile_path = self.klc_dir / "config" / "profile.yml"
        profile_path.write_text("profile: generic\nlanguages:\n  - cpp\n", encoding="utf-8")

        # Simulate yaml import failure by temporarily hiding yaml module
        yaml_backup = sys.modules.get("yaml")
        if "yaml" in sys.modules:
            del sys.modules["yaml"]

        # Mock builtins.__import__ to raise ImportError for yaml
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("No module named 'yaml'")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = mock_import

        try:
            # Should still detect python from inventory, skip profile
            languages = detect()
            self.assertIn("python", languages)
            self.assertNotIn("cpp", languages, "Profile should be skipped if yaml unavailable")
        finally:
            # Restore original import
            builtins.__import__ = original_import
            if yaml_backup:
                sys.modules["yaml"] = yaml_backup

    def test_empty_inventory_and_profile(self):
        """Test that empty inventory.json and missing profile return empty set."""
        from detect_languages import detect

        # Write empty but valid JSON
        inventory_path = self.klc_dir / "index" / "inventory.json"
        inventory_path.write_text("{}", encoding="utf-8")

        # No profile.yml

        languages = detect()
        self.assertEqual(languages, set(), "Empty inventory and no profile should return empty set")


if __name__ == "__main__":
    unittest.main()
