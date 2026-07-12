"""Tests that intake's owner lookup delegates to identity.current().

The private `_git_user()` helper must be gone; intake must resolve the ticket
owner through the shared `identity.current()` helper instead.

Run with pytest, or standalone: `python3 tests/test_intake_identity.py`.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core" / "phases"))
import intake  # noqa: E402


def test_private_git_user_removed():
    assert not hasattr(intake, "_git_user"), \
        "_git_user() must be replaced by identity.current()"


def test_owner_delegates_to_identity_current(tmp_path, monkeypatch):
    # Isolate all writes into a throwaway PROJECT_ROOT — never touch real .klc/.
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(intake.identity, "current",
                        lambda: "sentinel-owner@example.com")

    rc = intake.run(["KLC-999", "a small tweak to the docs"])
    assert rc == 0

    meta_path = tmp_path / ".klc" / "tickets" / "KLC-999" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["owner"] == "sentinel-owner@example.com"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
