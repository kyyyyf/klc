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


def _empty_state_repo(tmp_path: Path) -> Path:
    """Create a `.klc/` klc-state worktree bound to a bare upstream, seeded with
    NO tickets (just a .seed file). Returns the klc dir. The bare's HEAD is set
    to klc-state so a peer `git clone` checks the branch out cleanly."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)

    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    (klc / ".seed").write_text("seed\n", encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "origin", str(bare))
    _git(klc, "push", "-u", "origin", "klc-state")
    # Point the bare's HEAD at klc-state so `git clone` checks it out.
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    return klc


def _remote_meta(klc: Path, ticket: str) -> dict:
    """Read the ticket meta as it exists on the pushed remote tip."""
    _git(klc, "fetch", "origin")
    raw = _git(klc, "show", f"origin/klc-state:tickets/{ticket}/meta.json")
    return json.loads(raw)


def test_terminal_push_failure_leaves_clean_index_for_next_verb(tmp_path, monkeypatch):
    """HIGH-A: after a REAL terminal push failure, the `.klc` index AND working
    tree must be clean, so the NEXT feature-on verb's `pull_rebase` does not
    deadlock on a dirty index. Proven by a second ack that fully succeeds."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-910", phase="build:ack-needed", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"},
    )
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    # A pre-receive hook on the bare rejects every push (fetch/pull still work),
    # so commit_and_push_cas commits then hits a terminal (non-CAS) push failure.
    bare = tmp_path / "remote.git"
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    import ack as ack_mod
    rc1 = ack_mod.run(["KLC-910", "--pick", "1"])
    assert rc1 != 0, "the push must fail while the hook rejects it"

    status = _git(klc, "status", "--porcelain")
    assert status.strip() == "", \
        f"index/worktree not clean after rollback (HIGH-A): {status!r}"

    # The advance must have been rolled back locally too.
    local = json.loads(
        (klc / "tickets" / "KLC-910" / "meta.json").read_text(encoding="utf-8"))
    assert local["phase"] == "build:ack-needed", "advance must roll back on failure"

    # Server fixed → the second feature-on ack must fully succeed (no deadlock).
    hook.unlink()
    rc2 = ack_mod.run(["KLC-910", "--pick", "1"])
    assert rc2 == 0, "second feature-on ack must succeed after a clean rollback"
    remote = _remote_meta(klc, "KLC-910")
    assert remote["phase"] != "build:ack-needed", "the advance must reach the remote"


def test_intake_rejects_preexisting_remote_key_without_overwrite(tmp_path, monkeypatch):
    """HIGH-B: intake of a key a peer already committed to klc-state is pulled in
    by state_tx; it must be rejected as 'already taken' WITHOUT overwriting the
    peer's meta/holder, and without pushing."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _empty_state_repo(tmp_path)
    bare = tmp_path / "remote.git"

    # A peer clones the bare, creates KLC-950 (holder=bob) and pushes it.
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bare), str(peer))
    _git(peer, "config", "user.email", "bob@example.com")
    _git(peer, "config", "user.name", "Bob")
    ptd = peer / "tickets" / "KLC-950"
    ptd.mkdir(parents=True)
    (ptd / "meta.json").write_text(
        json.dumps(_meta("KLC-950", phase="intake:ack-needed", track="S",
                         holder={"id": "bob@example.com", "machine": "peerbox",
                                 "since": "2026-01-01T00:00:00Z"}),
                   indent=2) + "\n", encoding="utf-8")
    (ptd / "raw.md").write_text("peer body\n", encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer intake KLC-950")
    _git(peer, "push", "origin", "klc-state")

    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True

    import intake as intake_mod
    rc = intake_mod.run(["KLC-950", "alice tries the same key"])
    assert rc != 0, "a key already on the remote must be rejected (HIGH-B)"

    # The peer's ticket, pulled into our worktree, must be intact (not clobbered).
    meta = json.loads(
        (klc / "tickets" / "KLC-950" / "meta.json").read_text(encoding="utf-8"))
    assert meta["holder"]["id"] == "bob@example.com", \
        "the peer's holder must be preserved (no silent overwrite)"
    assert "peer body" in \
        (klc / "tickets" / "KLC-950" / "raw.md").read_text(encoding="utf-8"), \
        "the peer's raw.md must be preserved"

    # No local mutation may be left staged/unstaged.
    status = _git(klc, "status", "--porcelain")
    assert status.strip() == "", f"tree not clean after HIGH-B rejection: {status!r}"


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
