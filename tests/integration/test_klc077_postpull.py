"""KLC-077 MEDIUM-2 — the dependency unblock decision is made POST-pull.

The false-unblock TOCTOU: if the gate read the UPSTREAM meta BEFORE the
downstream verb's `state_tx` pulls, a locally-stale "reached" upstream could let
a downstream advance even though the pulled remote shows the upstream short (or
rolled back). Because the guard lives in `lifecycle.enter_work_guard` and runs
INSIDE the verb's `state_tx` (after `pull_rebase_preserving`), the decision uses
the SYNCED upstream.

This drives a REAL git-backed klc-state substrate (a bare remote bound as the
branch upstream). A peer advances the UPSTREAM on the remote AFTER our local
copy is seeded short; our local `klc next DOWN` pulls that advance inside the tx
and unblocks — proving the decision is post-pull (a pre-pull check would still
see the local short upstream and refuse). The reverse case (peer leaves the
upstream short) re-blocks and pushes nothing. No network — local bare repos only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import state_feature  # noqa: E402

ALICE = "alice@example.com"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)})
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _init_bare(path: Path) -> Path:
    subprocess.run(["git", "init", "--bare", "-b", "klc-state", str(path)],
                   check=True, capture_output=True)
    return path


def _meta(ticket, *, phase, track="S", blocked_by=None) -> dict:
    m = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "risk_tags": [], "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if blocked_by is not None:
        m["blocked_by"] = blocked_by
    return m


def _build_repo(tmp_path: Path, seed: dict):
    """A `.klc/` worktree whose klc-state upstream is bound to a bare remote
    `sm`. `seed` maps ticket → meta dict. Returns (klc_dir, bound_bare)."""
    bound = _init_bare(tmp_path / "sm.git")
    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    for ticket, meta in seed.items():
        tdir = klc / "tickets" / ticket
        tdir.mkdir(parents=True)
        (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                        encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "sm", str(bound))
    _git(klc, "push", "-u", "sm", "klc-state")
    return klc, bound


def _peer_set_upstream(tmp_path: Path, bound: Path, ticket: str, phase: str):
    """A peer clones the bound remote, moves `ticket` to `phase`, and pushes —
    a real remote advance our local tx will pull."""
    peer = tmp_path / f"peer-{ticket}-{phase.replace(':', '_')}"
    _git(tmp_path, "clone", str(bound), str(peer))
    _git(peer, "config", "user.email", "peer@example.com")
    _git(peer, "config", "user.name", "Peer")
    _git(peer, "config", "commit.gpgsign", "false")
    pm = peer / "tickets" / ticket / "meta.json"
    d = json.loads(pm.read_text())
    d["phase"] = phase
    pm.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", f"peer advances {ticket} to {phase}")
    _git(peer, "push", "origin", "klc-state")


_EDGE = {"on": "UP", "phase": "build", "point": "integrated"}


def test_unblock_decision_is_post_pull(tmp_path, monkeypatch):
    """Local seed: UP short (build:ack). Peer advances UP to integrate:ack on the
    remote. `klc next DOWN` pulls that advance inside its state_tx and UNBLOCKS —
    a pre-pull check would see the local short UP and refuse. Proves post-pull."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound = _build_repo(tmp_path, {
        "UP": _meta("UP", phase="build:ack"),
        "DOWN": _meta("DOWN", phase="discovery-lite:ack", blocked_by=[_EDGE]),
    })
    assert state_feature.enabled() is True

    # Peer advances UP past the point on the remote; local copy still shows short.
    _peer_set_upstream(tmp_path, bound, "UP", "integrate:ack")
    assert json.loads((klc / "tickets" / "UP" / "meta.json").read_text())["phase"] \
        == "build:ack", "local UP is still the seeded (short) state pre-pull"

    import next as next_mod
    rc = next_mod.run(["DOWN"])
    assert rc == 0, "post-pull UP is reached → DOWN must unblock"

    local_down = json.loads(
        (klc / "tickets" / "DOWN" / "meta.json").read_text())["phase"]
    assert local_down == "build:work"
    # The advance was CAS-pushed: a fresh clone sees DOWN at build:work.
    peer = tmp_path / "verify"
    _git(tmp_path, "clone", str(bound), str(peer))
    assert json.loads((peer / "tickets" / "DOWN" / "meta.json").read_text())[
        "phase"] == "build:work"


def test_feature_on_block_rolls_back_and_pushes_nothing(tmp_path, monkeypatch,
                                                        capsys):
    """Feature-ON: with the upstream short (remote truth), `klc next DOWN` blocks
    INSIDE the tx — the guard raises BlockedError, state_tx rolls the subtree
    back, and NOTHING is committed/pushed. A fresh clone still shows DOWN at its
    seeded state (the KLC-075 R3 rollback pattern applied to the dependency gate)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound = _build_repo(tmp_path, {
        "UP": _meta("UP", phase="build:ack"),      # short, on the remote too
        "DOWN": _meta("DOWN", phase="discovery-lite:ack", blocked_by=[_EDGE]),
    })
    assert state_feature.enabled() is True

    import next as next_mod
    rc = next_mod.run(["DOWN"])
    assert rc == 1, "upstream short → DOWN must refuse feature-ON"
    assert "blocked by UP until integrated" in capsys.readouterr().err

    # Local subtree rolled back to the seed; nothing pushed to the remote.
    assert json.loads((klc / "tickets" / "DOWN" / "meta.json").read_text())[
        "phase"] == "discovery-lite:ack"
    peer = tmp_path / "verify"
    _git(tmp_path, "clone", str(bound), str(peer))
    assert json.loads((peer / "tickets" / "DOWN" / "meta.json").read_text())[
        "phase"] == "discovery-lite:ack"
