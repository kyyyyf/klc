"""KLC-081: the `rework_count` increment is DURABLE — feature-ON it rides the
same state_tx / CAS-push as the backward transition that triggers it.

The increment is a plain mutation of the transition's own `meta.json` write, so
it must reach the bound upstream in the SAME commit the transition does. These
tests bind a real `.klc/` worktree to a bare remote named `sm` (NOT `origin`,
per the KLC-069 harness), plus a decoy `origin`, run a real feature-ON backward
verb, and assert:

  - a fresh clone of `sm` observes `rework_count` incremented for the redone
    phase (the increment was CAS-pushed, not merely written locally);
  - the decoy `origin` is untouched;
  - a FORWARD transition pushes `rework_count == {}` (no-op durability parity).

No network — everything runs against local bare repos.
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


def _init_bare(path: Path) -> Path:
    subprocess.run(["git", "init", "--bare", "-b", "klc-state", str(path)],
                   check=True, capture_output=True)
    return path


def _meta(ticket: str, *, phase: str, track: str = "M",
          rework_count: dict | None = None, holder: dict | None = None) -> dict:
    m = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase,
        "phase_history": [{"phase": phase, "started_at": "2026-01-01T00:00:00Z"}],
        "track": track, "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 3},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
        "rework_count": {} if rework_count is None else rework_count,
    }
    if holder is not None:
        m["holder"] = holder
    return m


def _build_bound_state_repo(tmp_path: Path, ticket: str, *, phase: str,
                            track: str = "M", rework_count: dict | None = None,
                            artefacts: dict | None = None,
                            holder: dict | None = None):
    """A .klc/ worktree on klc-state bound to a bare `sm` upstream, plus a decoy
    `origin` — the KLC-069/075/076 real-substrate harness."""
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
        json.dumps(_meta(ticket, phase=phase, track=track,
                         rework_count=rework_count, holder=holder),
                   indent=2) + "\n", encoding="utf-8")
    for rel, text in (artefacts or {}).items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")

    _git(klc, "remote", "add", "origin", str(origin))
    _git(klc, "remote", "add", "sm", str(bound))
    _git(klc, "push", "origin", "klc-state")
    _git(klc, "push", "-u", "sm", "klc-state")
    return klc, bound, origin


def _remote_meta(klc: Path, remote: str, ticket: str):
    _git(klc, "fetch", remote)
    try:
        raw = _git(klc, "show", f"{remote}/klc-state:tickets/{ticket}/meta.json")
    except RuntimeError:
        return None
    return json.loads(raw)


def _clone_meta(tmp_path: Path, bound: Path, ticket: str):
    peer = tmp_path / f"peer-{ticket}"
    _git(tmp_path, "clone", str(bound), str(peer))
    return json.loads(
        (peer / "tickets" / ticket / "meta.json").read_text(encoding="utf-8"))


_HOLDER = {"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"}


# --- abort: rework increment is CAS-pushed durably ---------------------------

def test_abort_rework_increment_is_cas_pushed(tmp_path, monkeypatch):
    """Feature-ON `klc abort` from build:work bumps rework_count[build] and
    CAS-pushes it to the bound `sm`. A fresh clone sees {build: 1}; origin is
    untouched."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    klc, bound, _o = _build_bound_state_repo(
        tmp_path, "K81-CAS-ABT", phase="build:work",
        artefacts={"build/impl-plan.md": "step 1\n"}, holder=_HOLDER)
    assert state_feature.enabled() is True
    assert _git(klc, "config", "--get", "branch.klc-state.remote").strip() == "sm"

    import abort
    assert abort.run(["K81-CAS-ABT"]) == 0

    rm = _remote_meta(klc, "sm", "K81-CAS-ABT")
    assert rm["phase"] == "design:ack"
    assert rm["rework_count"] == {"build": 1}, "the bump must be CAS-pushed to sm"
    assert _remote_meta(klc, "origin", "K81-CAS-ABT")["rework_count"] == {}, \
        "origin must be untouched"

    peer = _clone_meta(tmp_path, bound, "K81-CAS-ABT")
    assert peer["rework_count"] == {"build": 1}, \
        "a peer cloning sm must receive the incremented rework_count"


# --- needs-rework ack pick: increment is CAS-pushed durably ------------------

def test_regression_ack_rework_increment_is_cas_pushed(tmp_path, monkeypatch):
    """Feature-ON `klc ack --pick 2` (observe "regression" → build:work) bumps
    rework_count[build] durably to the bound remote."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    klc, bound, _o = _build_bound_state_repo(
        tmp_path, "K81-CAS-ACK", phase="observe:ack-needed", holder=_HOLDER)
    assert state_feature.enabled() is True

    import ack
    assert ack.run(["K81-CAS-ACK", "--pick", "2"]) == 0

    rm = _remote_meta(klc, "sm", "K81-CAS-ACK")
    assert rm["phase"] == "build:work"
    assert rm["rework_count"] == {"build": 1}
    peer = _clone_meta(tmp_path, bound, "K81-CAS-ACK")
    assert peer["rework_count"] == {"build": 1}


# --- backward jump: increment is CAS-pushed durably --------------------------

def test_backward_jump_rework_increment_is_cas_pushed(tmp_path, monkeypatch):
    """Feature-ON backward `klc jump build` from review:ack bumps
    rework_count[build] durably, and preserves a pre-existing count."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    klc, bound, _o = _build_bound_state_repo(
        tmp_path, "K81-CAS-JMP", phase="review:ack",
        rework_count={"design": 1})
    assert state_feature.enabled() is True

    import jump
    assert jump.run(["build", "K81-CAS-JMP", "--yes"]) == 0

    rm = _remote_meta(klc, "sm", "K81-CAS-JMP")
    assert rm["phase"] == "build:work"
    assert rm["rework_count"] == {"design": 1, "build": 1}, \
        "the bump must ride the jump's commit and preserve prior counts"
    peer = _clone_meta(tmp_path, bound, "K81-CAS-JMP")
    assert peer["rework_count"] == {"design": 1, "build": 1}


# --- forward transition: no-rework no-op durability parity -------------------

def test_forward_ack_pushes_empty_rework(tmp_path, monkeypatch):
    """A forward ack CAS-pushes the advance but leaves rework_count == {} — the
    increment is truly gated on backward moves, even durably."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    klc, bound, _o = _build_bound_state_repo(
        tmp_path, "K81-CAS-FWD", phase="observe:ack-needed", holder=_HOLDER)
    assert state_feature.enabled() is True

    import ack
    assert ack.run(["K81-CAS-FWD", "--pick", "1"]) == 0   # "clean" → next

    rm = _remote_meta(klc, "sm", "K81-CAS-FWD")
    assert rm["phase"] != "build:work"
    assert rm["rework_count"] == {}, "a forward move must not push any rework bump"
    peer = _clone_meta(tmp_path, bound, "K81-CAS-FWD")
    assert peer["rework_count"] == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
