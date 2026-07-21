"""KLC-075 defect-1: `klc retrack` must CAS-push the track change under
feature-ON, and stay a pure local write under feature-OFF.

Before the fix `retrack` did a bare `lifecycle.write_meta`, so a track change
made without a following `ack` was committed only to the local klc-state
worktree and never reached the bound upstream — peers saw the stale track until
some later verb's state_tx happened to sweep it.

These tests drive `retrack` through a REAL git-backed klc-state substrate (a
bare remote named ``sm`` bound as the branch upstream, plus a decoy ``origin``)
and assert the track change is committed AND CAS-pushed to the bound upstream in
one envelope: a fresh clone of ``sm`` observes the retrack with NO following
ack. No network — everything runs against local bare repos (AC-10 lesson from
KLC-057).
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


def _init_bare(path: Path) -> Path:
    subprocess.run(["git", "init", "--bare", "-b", "klc-state", str(path)],
                   check=True, capture_output=True)
    return path


def _meta(ticket: str, *, phase: str, track: str) -> dict:
    return {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }


def _build_bound_state_repo(tmp_path: Path, ticket: str, *, phase: str,
                            track: str):
    """A ``.klc/`` worktree whose ``klc-state`` upstream is bound to a bare
    remote named ``sm`` (NOT origin), with a decoy ``origin`` seeded identically.
    Returns ``(klc_dir, bound_bare, origin_bare)``."""
    bound = _init_bare(tmp_path / "sm.git")
    origin = _init_bare(tmp_path / "origin.git")

    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")

    tdir = klc / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(
        json.dumps(_meta(ticket, phase=phase, track=track), indent=2) + "\n",
        encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")

    _git(klc, "remote", "add", "origin", str(origin))
    _git(klc, "remote", "add", "sm", str(bound))
    _git(klc, "push", "origin", "klc-state")          # decoy has the branch too
    _git(klc, "push", "-u", "sm", "klc-state")        # upstream := sm
    return klc, bound, origin


def _remote_track(klc: Path, remote: str, ticket: str):
    _git(klc, "fetch", remote)
    try:
        raw = _git(klc, "show", f"{remote}/klc-state:tickets/{ticket}/meta.json")
    except RuntimeError:
        return None
    return json.loads(raw)["track"]


def _spawn_lock_holder(klc: Path, ticket: str):
    """Write a ticket .lock owned by a LIVE foreign PID so acquire_lock raises
    LockedError (a dead PID would be reclaimed). Caller must terminate it."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"])
    lock = klc / "tickets" / ticket / ".lock"
    lock.write_text(
        json.dumps({"pid": proc.pid, "at": "2026-01-01T00:00:00Z"}) + "\n",
        encoding="utf-8")
    return proc


def test_retrack_cas_pushes_to_bound_remote(tmp_path, monkeypatch):
    """Feature-ON: a retrack (no following ack) is CAS-pushed to the BOUND
    upstream (sm) — a fresh clone of sm sees the new track; the decoy origin is
    untouched. RED before the fix (bare write, nothing pushed)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, origin = _build_bound_state_repo(
        tmp_path, "KLC-975", phase="discovery:work", track="L")

    assert state_feature.enabled() is True, \
        "a klc-state worktree with an upstream must read feature ON"
    assert _git(klc, "config", "--get", "branch.klc-state.remote").strip() == "sm"

    import retrack as retrack_mod
    rc = retrack_mod.run(["KLC-975", "M", "--reason", "over-routed by length"])
    assert rc == 0, "feature-on retrack must succeed against a non-origin remote"

    # The change landed on the BOUND remote WITHOUT any ack...
    assert _remote_track(klc, "sm", "KLC-975") == "M", \
        "the retrack must be CAS-pushed to the BOUND remote (sm)"
    # ...and NOT on the decoy origin.
    assert _remote_track(klc, "origin", "KLC-975") == "L", \
        "origin must be untouched — the push must not default to a remote named origin"

    # A peer cloning `sm` sees the pushed change — the real-substrate proof.
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    peer_meta = json.loads(
        (peer / "tickets" / "KLC-975" / "meta.json").read_text(encoding="utf-8"))
    assert peer_meta["track"] == "M", \
        "a peer cloning sm/klc-state must receive the retrack with no ack"
    # The audit entry rides the same commit.
    assert any(e.get("event") == "retrack" and e.get("to_track") == "M"
               for e in peer_meta.get("phase_history", [])), \
        "the retrack audit entry must ride the CAS-pushed commit"


def test_retrack_feature_off_is_pure_local_write(tmp_path, monkeypatch):
    """Feature-OFF (a plain .klc dir with no klc-state upstream): retrack still
    writes meta, performs NO push, and raises no error — byte-identical to the
    pre-KLC-075 behaviour."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / "KLC-976"
    tdir.mkdir(parents=True)
    meta_p = tdir / "meta.json"
    meta_p.write_text(
        json.dumps(_meta("KLC-976", phase="intake:ack-needed", track="L")),
        encoding="utf-8")

    assert state_feature.enabled() is False, "a plain .klc must read feature OFF"

    import retrack as retrack_mod
    rc = retrack_mod.run(["KLC-976", "S", "--reason", "verbose desc, small fix"])
    assert rc == 0, "feature-off retrack must succeed with a direct local write"

    assert json.loads(meta_p.read_text())["track"] == "S", \
        "feature-off retrack must still write the track change locally"
    # No git was created for the state dir → nothing was pushed.
    assert not (klc / ".git").exists(), \
        "feature-off retrack must touch no git"


def test_retrack_stale_guard(tmp_path, monkeypatch, capsys):
    """FIX-6: if the bound remote advanced the ticket out-of-band after seed, a
    retrack aborts with the friendly stale message + return 1 (the state_tx
    stale-guard fired), and neither the bound remote nor the decoy origin is
    changed."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-982", phase="discovery:work", track="L")
    assert state_feature.enabled() is True

    # A peer edits the ticket subtree on the bound remote; our local worktree
    # still holds the committed seed → the pull will move the subtree.
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    _git(peer, "config", "user.email", "peer@example.com")
    _git(peer, "config", "user.name", "Peer")
    _git(peer, "config", "commit.gpgsign", "false")
    pm = peer / "tickets" / "KLC-982" / "meta.json"
    d = json.loads(pm.read_text())
    d["route_confidence"] = "low"
    pm.write_text(json.dumps(d, indent=2) + "\n")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer edits ticket")
    _git(peer, "push", "origin", "klc-state")

    import retrack as retrack_mod
    rc = retrack_mod.run(["KLC-982", "M", "--reason", "over-routed"])
    assert rc == 1, "retrack must abort when the remote advanced"
    assert "advanced" in capsys.readouterr().err.lower()
    # The track was NOT pushed anywhere — the peer only touched route_confidence.
    assert _remote_track(klc, "sm", "KLC-982") == "L"
    assert _remote_track(klc, "origin", "KLC-982") == "L"


def test_retrack_lock_contention(tmp_path, monkeypatch, capsys):
    """FIX-6: a live foreign holder of the ticket .lock makes retrack fail with
    the friendly LockedError message and return 1 (no push)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-983", phase="intake:ack-needed", track="L")
    assert state_feature.enabled() is True

    holder_proc = _spawn_lock_holder(klc, "KLC-983")
    try:
        import retrack as retrack_mod
        rc = retrack_mod.run(["KLC-983", "M", "--reason", "x"])
        assert rc == 1, "retrack must fail under lock contention"
        assert "locked" in capsys.readouterr().err.lower()
        assert _remote_track(klc, "sm", "KLC-983") == "L", "no push under lock"
    finally:
        holder_proc.terminate()
        holder_proc.wait()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
