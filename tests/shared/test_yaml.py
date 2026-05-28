"""Test core.shared.yaml utilities."""

from pathlib import Path
import tempfile
from core.shared import yaml


def test_parse_simple_dict():
    """Test parsing simple dictionary."""
    text = """
key1: value1
key2: 123
key3: true
"""
    result = yaml.parse(text)
    assert result == {"key1": "value1", "key2": 123, "key3": True}


def test_parse_list():
    """Test parsing list."""
    text = """
- item1
- item2
- 42
"""
    result = yaml.parse(text)
    assert result == ["item1", "item2", 42]


def test_load_from_file():
    """Test loading YAML from file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write("name: test\nversion: 1.0\n")
        f.flush()
        path = f.name

    try:
        result = yaml.load(path)
        assert result == {"name": "test", "version": "1.0"}
    finally:
        Path(path).unlink()


def test_load_with_defaults():
    """Test loading with default values merged."""
    defaults = {"timeout": 30, "retries": 3, "verbose": False}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write("timeout: 60\nverbose: true\n")
        f.flush()
        path = f.name

    try:
        result = yaml.load_with_defaults(path, defaults)
        assert result == {"timeout": 60, "retries": 3, "verbose": True}
    finally:
        Path(path).unlink()


def test_load_with_defaults_non_dict_fails():
    """Test that load_with_defaults fails if file contains non-dict."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write("- item1\n- item2\n")
        f.flush()
        path = f.name

    try:
        try:
            yaml.load_with_defaults(path, {"key": "value"})
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "requires dict" in str(e)
    finally:
        Path(path).unlink()


def test_validate_schema_success():
    """Test schema validation with all required keys present."""
    data = {"name": "test", "version": "1.0", "author": "me"}
    yaml.validate_schema(data, ["name", "version"])  # Should not raise


def test_validate_schema_missing_keys():
    """Test schema validation fails when keys missing."""
    data = {"name": "test"}
    try:
        yaml.validate_schema(data, ["name", "version", "author"])
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "Missing required keys" in str(e)
        assert "version" in str(e)
        assert "author" in str(e)


def test_validate_schema_non_dict_fails():
    """Test schema validation fails on non-dict."""
    try:
        yaml.validate_schema(["item1", "item2"], ["key"])
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "requires dict" in str(e)
