"""KLC-076: `klc abort --cancel` — terminate a ticket to the new `cancelled`
terminal from ANY state, durably (feature-ON) via the SAME `acquire_lock →
state_tx` envelope abort/scope-fix use.

The CAS-push cases are driven through a REAL git-backed klc-state substrate (a
bare remote named ``sm`` bound as the branch upstream, plus a decoy ``origin``):
a fresh clone of ``sm`` observes the cancellation with no following ack, and the
decoy ``origin`` is untouched. No network.

Harness copied from tests/integration/test_klc075_scope_fix.py.
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


def _meta(ticket: str, *, phase: str, track: str = "M",
          holder: dict | None = None) -> dict:
    m = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase,
        "phase_history": [{"phase": phase, "started_at": "2026-01-01T00:00:00Z"}],
        "track": track, "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 3},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if holder is not None:
        m["holder"] = holder
    return m


def _build_bound_state_repo(tmp_path: Path, ticket: str, *, phase: str,
                            track: str = "M", artefacts: dict | None = None,
                            holder: dict | None = None):
    """A .klc/ worktree on klc-state bound to a bare `sm` upstream, plus a decoy
    `origin`. `artefacts` maps rel-path→text under tickets/<ticket>/."""
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
        json.dumps(_meta(ticket, phase=phase, track=track, holder=holder),
                   indent=2) + "\n",
        encoding="utf-8")
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


def _clone_and_read_meta(tmp_path: Path, bound: Path, ticket: str):
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    return json.loads(
        (peer / "tickets" / ticket / "meta.json").read_text(encoding="utf-8"))


# --- CAS: cancel from each of the three state families -----------------------

def test_cancel_from_work_cas_supersedes_and_pushes(tmp_path, monkeypatch):
    """AC-1/AC-5: cancel from `<X>:work` supersedes the current-phase artefacts
    AND CAS-pushes the cancellation to the bound upstream. A fresh clone sees
    phase=cancelled with the audit entry; the decoy origin is untouched."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-976A", phase="build:work",
        artefacts={"build/impl-plan.md": "step 1\n"})
    assert state_feature.enabled() is True
    assert _git(klc, "config", "--get", "branch.klc-state.remote").strip() == "sm"

    import abort
    rc = abort.run(["KLC-976A", "--cancel", "--reason", "superseded by KLC-999"])
    assert rc == 0, "cancel from :work must succeed"

    rm = _remote_meta(klc, "sm", "KLC-976A")
    assert rm["phase"] == "cancelled" and rm.get("cancelled") is True
    assert rm.get("cancel_reason") == "superseded by KLC-999"
    hist = rm.get("phase_history", [])
    entry = next(e for e in hist if e.get("event") == "cancelled")
    assert entry["from_phase"] == "build:work"
    assert entry["reason"] == "superseded by KLC-999"
    # `by` is the OPERATOR identity (identity.current(), from the acting user's
    # git config), recorded for the audit trail — just assert it is populated.
    assert isinstance(entry.get("by"), str) and entry["by"]
    # origin is untouched (still :work).
    assert _remote_meta(klc, "origin", "KLC-976A")["phase"] == "build:work"

    # A fresh clone of sm sees the cancellation with NO following ack, and the
    # superseded artefact rode the same commit.
    peer_meta = _clone_and_read_meta(tmp_path, bound, "KLC-976A")
    assert peer_meta["phase"] == "cancelled"
    peer = tmp_path / "peer"
    assert not (peer / "tickets" / "KLC-976A" / "build" / "impl-plan.md").exists(), \
        "the current-phase artefact must have been moved to _superseded/"
    assert list((peer / "tickets" / "KLC-976A" / "_superseded").glob("*/build/**/impl-plan.md")), \
        "the superseded artefact must ride the CAS-pushed commit"


def test_cancel_from_ack_cas_pushes(tmp_path, monkeypatch):
    """AC-1: cancel is valid from `<X>:ack` and is CAS-pushed durably."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, _o = _build_bound_state_repo(
        tmp_path, "KLC-976B", phase="design:ack")
    assert state_feature.enabled() is True

    import abort
    assert abort.run(["KLC-976B", "--cancel", "--reason", "wontfix"]) == 0
    assert _remote_meta(klc, "sm", "KLC-976B")["phase"] == "cancelled"
    peer_meta = _clone_and_read_meta(tmp_path, bound, "KLC-976B")
    assert peer_meta["phase"] == "cancelled"
    assert peer_meta.get("cancelled") is True


def test_cancel_from_intake_ack_needed_cas_pushes(tmp_path, monkeypatch):
    """AC-1: cancel is valid from the very first state `intake:ack-needed`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _b, _o = _build_bound_state_repo(
        tmp_path, "KLC-976C", phase="intake:ack-needed")
    assert state_feature.enabled() is True

    import abort
    assert abort.run(["KLC-976C", "--cancel", "--reason", "created by mistake"]) == 0
    rm = _remote_meta(klc, "sm", "KLC-976C")
    assert rm["phase"] == "cancelled"
    entry = next(e for e in rm["phase_history"] if e.get("event") == "cancelled")
    assert entry["from_phase"] == "intake:ack-needed"


# --- terminal + refusal + non-happy ------------------------------------------

def test_recancel_is_refused_and_pushes_nothing(tmp_path, monkeypatch, capsys):
    """AC-6: a cancelled ticket is terminal — a second --cancel is refused and
    nothing is pushed."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _b, _o = _build_bound_state_repo(
        tmp_path, "KLC-976D", phase="review:ack")
    import abort
    assert abort.run(["KLC-976D", "--cancel", "--reason", "first"]) == 0
    before = _remote_meta(klc, "sm", "KLC-976D")

    rc = abort.run(["KLC-976D", "--cancel", "--reason", "second"])
    assert rc == 1, "re-cancelling a terminal ticket must be refused"
    assert "already cancelled" in capsys.readouterr().err
    after = _remote_meta(klc, "sm", "KLC-976D")
    assert after == before, "a refused re-cancel must push nothing"


def test_cancel_from_work_held_by_another_rolls_back(tmp_path, monkeypatch, capsys):
    """AC-5 durability: cancel from `:work` held by ANOTHER identity fails when
    the in-tx release_holder raises HolderConflictError. state_tx must roll the
    subtree back and push NOTHING — the bound `sm` is byte-for-byte unchanged
    (still :work, foreign holder intact) and the decoy origin is untouched."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    foreign = {"id": "someone-else@example.com", "machine": "otherbox",
               "since": "2026-01-01T00:00:00Z"}
    klc, _bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-976G", phase="build:work",
        artefacts={"build/impl-plan.md": "step 1\n"}, holder=foreign)
    assert state_feature.enabled() is True
    before_sm = _remote_meta(klc, "sm", "KLC-976G")
    before_origin = _remote_meta(klc, "origin", "KLC-976G")

    import abort
    rc = abort.run(["KLC-976G", "--cancel", "--reason", "cleanup"])
    assert rc == 1, "cancel must fail when the phase is held by another identity"
    assert "held by" in capsys.readouterr().err

    assert _remote_meta(klc, "sm", "KLC-976G") == before_sm, \
        "a failed cancel must roll back and push nothing to the bound remote"
    assert _remote_meta(klc, "origin", "KLC-976G") == before_origin
    assert before_sm["phase"] == "build:work" and before_sm.get("cancelled") is not True


def test_cancel_requires_reason(tmp_path, monkeypatch):
    """AC-1: --reason is required with --cancel."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_bound_state_repo(tmp_path, "KLC-976E", phase="design:ack")
    import abort
    with pytest.raises(SystemExit) as ei:
        abort.run(["KLC-976E", "--cancel"])
    assert ei.value.code != 0


def test_plain_abort_from_work_is_unchanged(tmp_path, monkeypatch):
    """AC-2: plain `klc abort` (no --cancel) keeps its contract — from `<X>:work`
    it steps back to the previous phase's `:ack`, NOT to cancelled, and is
    CAS-pushed."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _b, _o = _build_bound_state_repo(
        tmp_path, "KLC-976F", phase="build:work")
    assert state_feature.enabled() is True

    import abort
    assert abort.run(["KLC-976F"]) == 0
    rm = _remote_meta(klc, "sm", "KLC-976F")
    # build's previous track-M phase is design.
    assert rm["phase"] == "design:ack", rm["phase"]
    assert rm.get("cancelled") is not True, "plain abort must not cancel the ticket"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
