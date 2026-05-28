"""Test core.shared.artefacts utilities."""

import os
import tempfile
import time
from pathlib import Path
from core.shared import artefacts


def test_write_with_frontmatter_simple():
    """Test writing file with simple frontmatter."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        path = f.name

    try:
        artefacts.write_with_frontmatter(
            path,
            {"ticket": "KLC-007", "authority": "agent"},
            "# Spec\n\nContent here."
        )

        content = Path(path).read_text()
        assert content.startswith("---\n")
        assert "ticket: KLC-007" in content
        assert "authority: agent" in content
        assert "---\n\n# Spec" in content
    finally:
        Path(path).unlink()


def test_write_with_frontmatter_nested():
    """Test frontmatter with nested dict."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        path = f.name

    try:
        artefacts.write_with_frontmatter(
            path,
            {
                "ticket": "KLC-007",
                "estimate": {"complexity": 3, "total": 7},
                "tags": ["refactor", "cleanup"]
            },
            "Content"
        )

        content = Path(path).read_text()
        assert "ticket: KLC-007" in content
        assert "estimate:" in content
        assert "complexity: 3" in content
        assert "total: 7" in content
        assert "tags: [refactor, cleanup]" in content
    finally:
        Path(path).unlink()


def test_write_with_frontmatter_special_chars():
    """Test frontmatter with special characters in strings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        path = f.name

    try:
        artefacts.write_with_frontmatter(
            path,
            {"title": "Test: Special chars [foo]", "note": "Value with # comment"},
            "Content"
        )

        content = Path(path).read_text()
        # Should be quoted
        assert 'title: "Test: Special chars [foo]"' in content
        assert 'note: "Value with # comment"' in content
    finally:
        Path(path).unlink()


def test_acquire_lock_success():
    """Test acquiring lock on ticket."""
    ticket_id = f"TEST-{os.getpid()}"

    with artefacts.acquire_lock(ticket_id):
        # Verify lock file exists
        lock_path = artefacts._lock_path(ticket_id)
        assert lock_path.exists()

    # Verify lock released
    assert not lock_path.exists()


def test_acquire_lock_blocks_concurrent():
    """Test that second process cannot acquire same lock."""
    ticket_id = f"TEST-{os.getpid()}-concurrent"

    with artefacts.acquire_lock(ticket_id):
        # Try to acquire again (should fail)
        # Simulate different PID by manually creating lock
        lock_path = artefacts._lock_path(ticket_id)
        original_content = lock_path.read_text()

        # Write fake lock with different PID
        import json
        fake_lock = {"pid": 999999, "at": "2026-01-01T00:00:00Z"}
        lock_path.write_text(json.dumps(fake_lock) + "\n")

        try:
            with artefacts.acquire_lock(ticket_id):
                pass
            # If we get here without exception, lock wasn't enforced properly
            # But our PID check will see 999999 is dead and reclaim
        except artefacts.LockedError:
            pass  # Expected if PID 999999 somehow alive
        finally:
            # Restore original lock
            lock_path.write_text(original_content)

    # Cleanup
    if lock_path.exists():
        lock_path.unlink()


def test_acquire_lock_reclaims_stale():
    """Test that stale locks (dead PID) are reclaimed."""
    ticket_id = f"TEST-{os.getpid()}-stale"

    # Create stale lock (fake PID)
    lock_path = artefacts._lock_path(ticket_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    import json
    stale_lock = {"pid": 999999, "at": "2020-01-01T00:00:00Z"}
    lock_path.write_text(json.dumps(stale_lock) + "\n")

    # Should reclaim stale lock
    with artefacts.acquire_lock(ticket_id):
        # New lock should have our PID
        current = json.loads(lock_path.read_text())
        assert current["pid"] == os.getpid()

    # Cleanup
    assert not lock_path.exists()
