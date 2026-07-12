"""Tests for core/skills/identity.py — the public `current()` identity helper.

Run with pytest, or standalone: `python3 tests/test_identity.py`.
"""
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core" / "skills"))
import identity  # noqa: E402


def _fake_run(mapping, raise_exc=None):
    """Build a fake subprocess.run.

    `mapping` maps a git config key ("user.email"/"user.name") to the stdout
    the fake `git config --get` should return. `raise_exc`, if given, is raised
    on every call (simulating git-not-on-PATH via OSError or a TimeoutExpired).
    """
    def _run(cmd, capture_output=True, text=True, timeout=5):
        if raise_exc is not None:
            raise raise_exc
        key = cmd[-1]
        return types.SimpleNamespace(stdout=mapping.get(key, ""), returncode=0)
    return _run


def test_returns_email(monkeypatch):
    monkeypatch.setattr(identity.subprocess, "run",
                        _fake_run({"user.email": "dev@example.com",
                                   "user.name": "Dev Name"}))
    monkeypatch.setenv("USER", "shelluser")
    assert identity.current() == "dev@example.com"


def test_falls_back_to_name(monkeypatch):
    # Whitespace-only email must be treated as unset, so name wins.
    monkeypatch.setattr(identity.subprocess, "run",
                        _fake_run({"user.email": "   ", "user.name": "Dev Name"}))
    monkeypatch.setenv("USER", "shelluser")
    assert identity.current() == "Dev Name"


def test_falls_back_to_user_env(monkeypatch):
    monkeypatch.setenv("USER", "shelluser")
    # (a) both git keys empty -> $USER
    monkeypatch.setattr(identity.subprocess, "run",
                        _fake_run({"user.email": "", "user.name": ""}))
    assert identity.current() == "shelluser"
    # (b) git not on PATH (OSError) -> fall through to $USER
    monkeypatch.setattr(identity.subprocess, "run",
                        _fake_run({}, raise_exc=OSError("no git")))
    assert identity.current() == "shelluser"
    # (c) git times out -> fall through to $USER
    monkeypatch.setattr(
        identity.subprocess, "run",
        _fake_run({}, raise_exc=subprocess.TimeoutExpired(cmd="git", timeout=5)))
    assert identity.current() == "shelluser"


def test_systemexit_when_all_unset(monkeypatch):
    # Empty $USER must be treated as unset, so nothing remains -> SystemExit.
    monkeypatch.setattr(identity.subprocess, "run",
                        _fake_run({"user.email": "", "user.name": ""}))
    monkeypatch.setenv("USER", "")
    with pytest.raises(SystemExit):
        identity.current()


def test_systemexit_message(monkeypatch):
    monkeypatch.setattr(identity.subprocess, "run",
                        _fake_run({"user.email": "", "user.name": ""}))
    monkeypatch.delenv("USER", raising=False)
    with pytest.raises(SystemExit) as exc:
        identity.current()
    msg = str(exc.value)
    assert msg  # non-empty
    assert "git config --global user.email" in msg


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
