"""KLC-057 LOW-1: feature-ON verbs against a REAL local klc-state worktree.

Unlike test_klc057_sync_holder.py (which stubs state_sync), these tests bind a
real `.klc/` git worktree to a `klc-state` branch with a LOCAL bare-repo upstream
(no network, AC-10) and drive the verbs with NOTHING stubbed except identity.

This exercises the actual `pull → mutate → CAS-push` sequence end-to-end. It is
the test that would have caught HIGH-1: before the fix the verbs mutated meta
BEFORE `state_tx` pulled, so `git pull --rebase` ran on a dirty tree and crashed
with an uncaught RuntimeError — feature-ON ack/next never worked against a real
repo.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import identity  # noqa: E402
import state_feature  # noqa: E402

ALICE = "alice@example.com"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _meta(ticket: str, *, phase: str, track: str, holder=None) -> dict:
    meta = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if holder is not None:
        meta["holder"] = holder
    return meta


def _build_state_repo(tmp_path: Path, ticket: str, *, phase: str, track: str,
                      holder=None) -> Path:
    """Create a `.klc/` klc-state worktree with a bare-repo upstream, seeded with
    one ticket, and return the klc dir. Feature detection reads ON afterwards."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)

    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")

    tdir = klc / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(
        json.dumps(_meta(ticket, phase=phase, track=track, holder=holder),
                   indent=2) + "\n", encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "origin", str(bare))
    _git(klc, "push", "-u", "origin", "klc-state")
    return klc


def _remote_meta(klc: Path, ticket: str) -> dict:
    """Read the ticket meta as it exists on the pushed remote tip."""
    _git(klc, "fetch", "origin")
    raw = _git(klc, "show", f"origin/klc-state:tickets/{ticket}/meta.json")
    return json.loads(raw)


def test_feature_on_ack_pulls_mutates_pushes_for_real(tmp_path, monkeypatch):
    """Feature ON against a real bare upstream: `ack` exits 0 AND the advance +
    holder release are actually committed and pushed to the remote."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-901", phase="build:ack-needed", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"},
    )
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    assert state_feature.enabled() is True, \
        "the real klc-state worktree with an upstream must read feature ON"

    import ack as ack_mod
    rc = ack_mod.run(["KLC-901", "--pick", "1"])
    assert rc == 0, "feature-on ack must succeed against a real repo"

    remote = _remote_meta(klc, "KLC-901")
    assert remote["phase"] != "build:ack-needed", \
        "the advance must be committed AND pushed to the bare remote"
    assert remote.get("holder") is None, \
        "the holder release must ride the same pushed commit"


def test_feature_on_next_pulls_mutates_pushes_for_real(tmp_path, monkeypatch):
    """Feature ON against a real bare upstream: `next` exits 0 AND the advance +
    first-grabbed holder are actually pushed to the remote."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-902", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    assert state_feature.enabled() is True

    import next as next_mod
    rc = next_mod.run(["KLC-902"])
    assert rc == 0, "feature-on next must succeed against a real repo"

    remote = _remote_meta(klc, "KLC-902")
    assert remote["phase"].endswith(":work"), \
        "the advance to :work must be pushed to the bare remote"
    assert remote["holder"]["id"] == ALICE, \
        "the first-grabbed holder must ride the same pushed commit"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
