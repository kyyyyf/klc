"""KLC-069: a feature-ON transaction CAS-pushes to the remote the ``klc-state``
branch is actually BOUND to — not a hardcoded ``origin``.

Dogfooding the multi-user state machine surfaced the bug: ``state_tx`` called
``commit_and_push_cas_subtree`` with no ``remote`` arg, so it defaulted to a
remote literally named ``origin`` regardless of where ``klc state init <remote>``
had bound the branch. On a clone whose state remote was ``sm`` the transaction
committed locally but pushed to the clone's ``origin`` (a different repo), so a
peer cloning ``sm/klc-state`` saw nothing.

These tests bind a REAL ``.klc/`` worktree to a bare remote named ``sm`` (NOT
``origin``), run a real feature-ON verb, and assert the push landed on
``sm/klc-state`` and a fresh clone of ``sm`` receives it. On the pre-fix code
(push → ``origin``) the ``sm``-advanced assertions FAIL; after the fix they pass.
No network — everything runs against local bare repos (AC-10 lesson from
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

import identity  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402

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


def _build_state_repo_bound_to(tmp_path: Path, remote_name: str, ticket: str,
                               *, phase: str, track: str, holder=None):
    """Create a ``.klc/`` worktree whose ``klc-state`` upstream is bound to a
    bare remote named *remote_name* (e.g. ``sm``), while ALSO wiring a decoy
    ``origin`` remote pointing at a DIFFERENT bare repo seeded with the same
    history. The decoy makes the pre-fix bug observable: old code pushes to
    ``origin`` (which fast-forwards cleanly) instead of the bound remote.

    Returns ``(klc_dir, bound_bare, origin_bare)``.
    """
    bound = _init_bare(tmp_path / f"{remote_name}.git")
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
        json.dumps(_meta(ticket, phase=phase, track=track, holder=holder),
                   indent=2) + "\n", encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")

    # Wire BOTH remotes and seed both with the branch, then bind the upstream to
    # the NON-origin remote — exactly what `klc state init sm` does.
    _git(klc, "remote", "add", "origin", str(origin))
    _git(klc, "remote", "add", remote_name, str(bound))
    _git(klc, "push", "origin", "klc-state")            # decoy has the branch too
    _git(klc, "push", "-u", remote_name, "klc-state")   # upstream := <remote_name>
    return klc, bound, origin


def _remote_phase(klc: Path, remote: str, ticket: str):
    """The ticket's committed phase on *remote*'s klc-state tip (None if absent)."""
    _git(klc, "fetch", remote)
    try:
        raw = _git(klc, "show", f"{remote}/klc-state:tickets/{ticket}/meta.json")
    except RuntimeError:
        return None
    return json.loads(raw)["phase"]


def test_upstream_remote_helper_reads_bound_remote(tmp_path):
    """The helper that threads the fix returns the branch's CONFIGURED upstream
    remote (``sm``), not the literal ``origin`` — the root of the class fix."""
    klc, _bound, _origin = _build_state_repo_bound_to(
        tmp_path, "sm", "KLC-969", phase="build:ack-needed", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"},
    )
    assert state_sync._upstream_remote(klc) == "sm"


def test_feature_on_ack_pushes_to_bound_non_origin_remote(tmp_path, monkeypatch):
    """AC-1/AC-3: with klc-state bound to ``sm`` (NOT origin), a feature-ON ack
    CAS-pushes the advance to ``sm/klc-state`` — origin is left untouched and a
    fresh clone of ``sm`` receives the change. RED on the pre-fix code (which
    pushes to origin), GREEN after threading the bound remote."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, origin = _build_state_repo_bound_to(
        tmp_path, "sm", "KLC-969", phase="build:ack-needed", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"},
    )
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    assert state_feature.enabled() is True, \
        "the klc-state worktree with an upstream must read feature ON"
    # Sanity: the branch really is bound to sm, not origin.
    assert _git(klc, "config", "--get", "branch.klc-state.remote").strip() == "sm"

    import ack as ack_mod
    rc = ack_mod.run(["KLC-969", "--pick", "1"])
    assert rc == 0, "feature-on ack must succeed against a non-origin state remote"

    # The advance landed on the BOUND remote...
    assert _remote_phase(klc, "sm", "KLC-969") != "build:ack-needed", \
        "the advance must be CAS-pushed to the BOUND remote (sm), not origin"
    # ...and NOT on the decoy origin (still at the seed phase).
    assert _remote_phase(klc, "origin", "KLC-969") == "build:ack-needed", \
        "origin must be untouched — the push must not default to a remote named origin"

    # A peer cloning `sm` sees the pushed change (the real-substrate proof).
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    peer_meta = json.loads(
        (peer / "tickets" / "KLC-969" / "meta.json").read_text(encoding="utf-8"))
    assert peer_meta["phase"] != "build:ack-needed", \
        "a peer cloning sm/klc-state must receive the pushed advance"
    assert peer_meta.get("holder") is None, \
        "the holder release must ride the same commit the peer clones"


def test_feature_on_next_pushes_to_bound_non_origin_remote(tmp_path, monkeypatch):
    """AC-1: `next` (first-grab holder + advance) also follows the bound remote.
    A second verb path proves the fix is at the CAS layer, not one call site."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, origin = _build_state_repo_bound_to(
        tmp_path, "sm", "KLC-970", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    assert state_feature.enabled() is True

    import next as next_mod
    rc = next_mod.run(["KLC-970"])
    assert rc == 0, "feature-on next must succeed against a non-origin state remote"

    assert (_remote_phase(klc, "sm", "KLC-970") or "").endswith(":work"), \
        "the advance to :work must be pushed to the BOUND remote (sm)"
    assert _remote_phase(klc, "origin", "KLC-970") == "build:ack", \
        "origin must be untouched by a next that is bound to sm"

    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    peer_meta = json.loads(
        (peer / "tickets" / "KLC-970" / "meta.json").read_text(encoding="utf-8"))
    assert peer_meta["holder"]["id"] == ALICE, \
        "the first-grabbed holder must reach the peer via sm/klc-state"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
