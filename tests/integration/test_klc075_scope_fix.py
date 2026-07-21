"""KLC-075 defect-2: `klc scope-fix` — a first-class, durable path for correcting
`meta.affected_modules`, including AFTER a ticket is archived.

Once a ticket is `archived` no further `ack` runs, so an out-of-band edit to
`affected_modules` had no state_tx to sweep it and needed a manual klc-state
commit + push. `scope-fix` wraps the edit in the same `acquire_lock → state_tx`
envelope, so an ARCHIVED-ticket correction is committed AND CAS-pushed to the
bound upstream in one envelope (feature-ON) and a pure local write (feature-OFF).

The CAS-push case is driven through a REAL git-backed klc-state substrate (a bare
remote named ``sm`` bound as the branch upstream, plus a decoy ``origin``): a
fresh clone of ``sm`` observes the corrected slice with no ack. No network.
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


def _meta(ticket: str, *, phase: str, track: str, affected) -> dict:
    return {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": list(affected), "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }


def _build_bound_state_repo(tmp_path: Path, ticket: str, *, phase: str,
                            track: str, affected):
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
        json.dumps(_meta(ticket, phase=phase, track=track, affected=affected),
                   indent=2) + "\n", encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")

    _git(klc, "remote", "add", "origin", str(origin))
    _git(klc, "remote", "add", "sm", str(bound))
    _git(klc, "push", "origin", "klc-state")
    _git(klc, "push", "-u", "sm", "klc-state")
    return klc, bound, origin


def _remote_affected(klc: Path, remote: str, ticket: str):
    _git(klc, "fetch", remote)
    try:
        raw = _git(klc, "show", f"{remote}/klc-state:tickets/{ticket}/meta.json")
    except RuntimeError:
        return None
    return json.loads(raw)["affected_modules"]


def _remote_file(klc: Path, remote: str, ticket: str, rel: str):
    """Committed bytes of tickets/<ticket>/<rel> on *remote*'s tip (or None)."""
    _git(klc, "fetch", remote)
    try:
        return _git(klc, "show", f"{remote}/klc-state:tickets/{ticket}/{rel}")
    except RuntimeError:
        return None


def _seed_tracked_extra(klc: Path, ticket: str):
    """Add tickets/<ticket>/notes.txt='baseline', commit + push to BOTH remotes,
    then leave an UNRELATED uncommitted modification to it in the worktree.
    Returns the notes path. A clean state_tx exit would sweep this modification
    onto the shared branch; the refuse/no-op paths must NOT."""
    notes = klc / "tickets" / ticket / "notes.txt"
    notes.write_text("baseline\n", encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "add notes")
    _git(klc, "push", "sm", "klc-state")
    _git(klc, "push", "origin", "klc-state")
    notes.write_text("locally-modified-unrelated\n", encoding="utf-8")  # uncommitted
    return notes


def _spawn_lock_holder(klc: Path, ticket: str):
    """Write a ticket .lock owned by a LIVE foreign PID so acquire_lock raises
    LockedError (a stale/dead PID would be reclaimed instead). Returns the
    Popen; the caller must terminate it."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"])
    lock = klc / "tickets" / ticket / ".lock"
    lock.write_text(
        json.dumps({"pid": proc.pid, "at": "2026-01-01T00:00:00Z"}) + "\n",
        encoding="utf-8")
    return proc


def test_archived_scope_fix_cas_pushes_to_bound_remote(tmp_path, monkeypatch):
    """Feature-ON: correcting the slice of an ARCHIVED ticket is CAS-pushed to
    the bound upstream (sm) — a fresh clone sees the correction with no ack.
    The decoy origin is untouched."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, origin = _build_bound_state_repo(
        tmp_path, "KLC-975", phase="archived", track="M",
        affected=["core/skills/state_tx", "core/skills/scope_delta"])

    assert state_feature.enabled() is True
    assert _git(klc, "config", "--get", "branch.klc-state.remote").strip() == "sm"

    import scope_fix as sf
    # Drop the temporarily-widened scope-guard entry.
    rc = sf.run(["KLC-975", "--remove", "core/skills/scope_delta",
                 "--reason", "drop temp scope-guard widening"])
    assert rc == 0, "scope-fix on an archived ticket must succeed"

    assert _remote_affected(klc, "sm", "KLC-975") == ["core/skills/state_tx"], \
        "the correction must be CAS-pushed to the BOUND remote (sm)"
    assert _remote_affected(klc, "origin", "KLC-975") == \
        ["core/skills/state_tx", "core/skills/scope_delta"], \
        "origin must be untouched"

    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    peer_meta = json.loads(
        (peer / "tickets" / "KLC-975" / "meta.json").read_text(encoding="utf-8"))
    assert peer_meta["affected_modules"] == ["core/skills/state_tx"], \
        "a peer cloning sm/klc-state must receive the archived-ticket correction"
    assert any(e.get("event") == "scope-fix"
               for e in peer_meta.get("phase_history", [])), \
        "the scope-fix audit entry must ride the CAS-pushed commit"


def test_scope_fix_add_and_replace_modes(tmp_path, monkeypatch):
    """--add unions, --modules replaces. A second verb path proves the edit
    logic, still CAS-pushed. Ticket is ARCHIVED (the only phase scope-fix
    accepts)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-977", phase="archived", track="M",
        affected=["a"])
    assert state_feature.enabled() is True

    import scope_fix as sf
    assert sf.run(["KLC-977", "--add", "b,c"]) == 0
    assert _remote_affected(klc, "sm", "KLC-977") == ["a", "b", "c"]

    assert sf.run(["KLC-977", "--modules", "x,y"]) == 0
    assert _remote_affected(klc, "sm", "KLC-977") == ["x", "y"]


def test_scope_fix_refuses_non_archived(tmp_path, monkeypatch, capsys):
    """FIX-4: scope-fix is archived-only. A genuinely non-archived SYNCED ticket
    is refused (return 1); the decision writes nothing, so nothing is pushed —
    correct scope at ack instead."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _bound, origin = _build_bound_state_repo(
        tmp_path, "KLC-979", phase="review:ack-needed", track="M",
        affected=["a"])
    assert state_feature.enabled() is True

    import scope_fix as sf
    rc = sf.run(["KLC-979", "--remove", "a"])
    assert rc == 1, "scope-fix must refuse a non-archived ticket"
    err = capsys.readouterr().err
    assert "post-archive" in err and "ack" in err
    # The decision (taken inside the envelope) writes nothing → nothing is pushed.
    assert _remote_affected(klc, "sm", "KLC-979") == ["a"], \
        "a refused scope-fix must not push"
    assert _remote_affected(klc, "origin", "KLC-979") == ["a"]


def test_scope_fix_refuses_non_archived_feature_off(tmp_path, monkeypatch, capsys):
    """P2-A parity: feature-OFF also refuses a non-archived ticket (return 1),
    no write, no git."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / "KLC-987"
    tdir.mkdir(parents=True)
    meta_p = tdir / "meta.json"
    meta_p.write_text(
        json.dumps(_meta("KLC-987", phase="build:work", track="M",
                         affected=["a"])), encoding="utf-8")
    assert state_feature.enabled() is False

    import scope_fix as sf
    rc = sf.run(["KLC-987", "--remove", "a"])
    assert rc == 1, "feature-off must refuse a non-archived ticket too"
    assert "post-archive" in capsys.readouterr().err
    assert json.loads(meta_p.read_text())["affected_modules"] == ["a"], \
        "a refused scope-fix must not write"
    assert not (klc / ".git").exists()


def test_scope_fix_stale_remote_archived_applies(tmp_path, monkeypatch):
    """P2-A: the archived gate is decided against SYNCED state. The bound remote
    has archived the ticket but the local worktree is behind (still live). Old
    code read the LOCAL (live) meta before the pull and refused forever, never
    pulling. Now scope-fix enters the envelope, pulls, sees archived and applies
    the correction to sm (after the stale-guard bounce). RED before P2-A."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-985", phase="discovery:work", track="M",
        affected=["a", "b"])
    assert state_feature.enabled() is True

    # A peer archives the ticket on the bound remote; local is behind.
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    _git(peer, "config", "user.email", "peer@example.com")
    _git(peer, "config", "user.name", "Peer")
    _git(peer, "config", "commit.gpgsign", "false")
    pm = peer / "tickets" / "KLC-985" / "meta.json"
    d = json.loads(pm.read_text())
    d["phase"] = "archived"
    pm.write_text(json.dumps(d, indent=2) + "\n")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer archives")
    _git(peer, "push", "origin", "klc-state")

    import scope_fix as sf
    # An operator re-runs on the stale-guard bounce; old code refused every run.
    for _ in range(2):
        rc = sf.run(["KLC-985", "--remove", "b"])
        if rc == 0:
            break
    assert _remote_affected(klc, "sm", "KLC-985") == ["a"], \
        "after syncing, scope-fix must see the archived phase and apply on sm"


def test_scope_fix_json_success_and_error_paths(tmp_path, monkeypatch, capsys):
    """P2-B: --json produces valid JSON on applied / noop / malformed paths."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _b, _o = _build_bound_state_repo(
        tmp_path, "KLC-986", phase="archived", track="M", affected=["a", "b"])
    assert state_feature.enabled() is True
    import scope_fix as sf

    assert sf.run(["KLC-986", "--remove", "b", "--json"]) == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["status"] == "applied" and obj["affected_modules"] == ["a"]
    assert obj["ticket"] == "KLC-986"

    assert sf.run(["KLC-986", "--modules", "a", "--json"]) == 0  # already [a]
    obj = json.loads(capsys.readouterr().out)
    assert obj["status"] == "noop" and obj["affected_modules"] == ["a"]

    assert sf.run(["KLC-986", "--modules", "x,,y", "--json"]) == 1
    obj = json.loads(capsys.readouterr().out)
    assert obj["status"] == "error" and obj["reason"] == "malformed-modules"


def test_scope_fix_refuse_does_not_push_preexisting(tmp_path, monkeypatch, capsys):
    """P2 (re-review): a REFUSAL must push nothing — not even an unrelated
    pre-existing subtree change. The non-archived ticket's tickets/<KEY>/ has an
    uncommitted tracked modification; scope-fix refuses; the bound `sm` must be
    byte-for-byte unchanged. RED before the abort-the-tx fix (the clean state_tx
    exit glob-committed + pushed the unrelated change)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-989", phase="review:ack-needed", track="M", affected=["a"])
    assert state_feature.enabled() is True
    _seed_tracked_extra(klc, "KLC-989")

    import scope_fix as sf
    rc = sf.run(["KLC-989", "--remove", "a"])
    assert rc == 1, "scope-fix must refuse a non-archived ticket"
    assert _remote_file(klc, "sm", "KLC-989", "notes.txt") == "baseline\n", \
        "a refusal must not push the pre-existing subtree change"
    # And the slice itself is untouched on the remote.
    assert _remote_affected(klc, "sm", "KLC-989") == ["a"]


def test_scope_fix_noop_does_not_push(tmp_path, monkeypatch, capsys):
    """P2 (re-review): a genuine no-op must push nothing — not even an unrelated
    pre-existing subtree change. Archived ticket already matching the request,
    with an uncommitted tracked modification present; scope-fix no-ops (rc 0) and
    `sm` stays byte-for-byte unchanged. RED before the abort-the-tx fix."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-990", phase="archived", track="M", affected=["a"])
    assert state_feature.enabled() is True
    _seed_tracked_extra(klc, "KLC-990")

    import scope_fix as sf
    rc = sf.run(["KLC-990", "--modules", "a"])  # already exactly [a] → no-op
    assert rc == 0, "a genuine no-op is a clean success"
    assert _remote_file(klc, "sm", "KLC-990", "notes.txt") == "baseline\n", \
        "a no-op must not push the pre-existing subtree change"
    assert _remote_affected(klc, "sm", "KLC-990") == ["a"]


def test_scope_fix_json_refused(tmp_path, monkeypatch, capsys):
    """P2-B: --json on the not-archived refusal emits valid JSON, status refused."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_bound_state_repo(
        tmp_path, "KLC-988", phase="review:ack-needed", track="M",
        affected=["a"])
    assert state_feature.enabled() is True
    import scope_fix as sf
    assert sf.run(["KLC-988", "--remove", "a", "--json"]) == 1
    obj = json.loads(capsys.readouterr().out)
    assert obj["status"] == "refused" and obj["reason"] == "not-archived"


def test_scope_fix_stale_local_noop_still_corrects(tmp_path, monkeypatch):
    """FIX-1: when the LOCAL slice is stale, the no-op must be decided against
    SYNCED upstream state, not the stale local read. Upstream=[a,b], local=[a];
    `scope-fix --modules a` must NOT silently report 'nothing to do' and skip the
    push — it enters the envelope, so after the stale-guard re-run the correction
    ([a]) reaches the bound remote. RED before FIX-1 (the stale local read makes
    `--modules a` a false no-op that never pulls, so upstream stays [a,b])."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-980", phase="archived", track="M", affected=["a"])
    assert state_feature.enabled() is True

    # A peer widens the slice on the bound remote out-of-band; our local worktree
    # still has the committed [a] and has NOT fetched → local is stale.
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(bound), str(peer))
    _git(peer, "config", "user.email", "peer@example.com")
    _git(peer, "config", "user.name", "Peer")
    _git(peer, "config", "commit.gpgsign", "false")
    pm = peer / "tickets" / "KLC-980" / "meta.json"
    data = json.loads(pm.read_text())
    data["affected_modules"] = ["a", "b"]
    pm.write_text(json.dumps(data, indent=2) + "\n")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer widens slice")
    _git(peer, "push", "origin", "klc-state")

    import scope_fix as sf
    # Drive it the way an operator would: re-run on the stale-guard bounce.
    for _ in range(2):
        rc = sf.run(["KLC-980", "--modules", "a"])
        if rc == 0:
            break
    assert _remote_affected(klc, "sm", "KLC-980") == ["a"], \
        "the correction must reach the bound remote once decided against synced state"


def test_scope_fix_genuine_noop_is_clean_success(tmp_path, monkeypatch, capsys):
    """FIX-2: a genuine post-sync no-op (synced slice already equals the target)
    surfaces as NothingToCommitError inside the tx, which must be a CLEAN success
    (return 0, friendly 'nothing to change') — NOT a 'state sync failed' error."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-984", phase="archived", track="M", affected=["a"])
    assert state_feature.enabled() is True

    import scope_fix as sf
    rc = sf.run(["KLC-984", "--modules", "a"])  # already exactly [a]
    assert rc == 0, "a genuine no-op must be a clean success"
    out = capsys.readouterr()
    assert "nothing to change" in (out.out + out.err).lower()
    assert "state sync failed" not in (out.out + out.err).lower()


def test_scope_fix_lock_contention(tmp_path, monkeypatch, capsys):
    """FIX-6: a live foreign holder of the ticket .lock makes scope-fix fail with
    the friendly LockedError message and return 1 (no push)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, _bound, _origin = _build_bound_state_repo(
        tmp_path, "KLC-981", phase="archived", track="M", affected=["a"])
    assert state_feature.enabled() is True

    holder_proc = _spawn_lock_holder(klc, "KLC-981")
    try:
        import scope_fix as sf
        rc = sf.run(["KLC-981", "--remove", "a"])
        assert rc == 1, "scope-fix must fail under lock contention"
        assert "locked" in capsys.readouterr().err.lower()
        assert _remote_affected(klc, "sm", "KLC-981") == ["a"], "no push under lock"
    finally:
        holder_proc.terminate()
        holder_proc.wait()


def test_scope_fix_feature_off_is_pure_local_write(tmp_path, monkeypatch):
    """Feature-OFF: scope-fix writes meta, does NO push, raises no error."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / "KLC-976"
    tdir.mkdir(parents=True)
    meta_p = tdir / "meta.json"
    meta_p.write_text(
        json.dumps(_meta("KLC-976", phase="archived", track="M",
                         affected=["a", "b"])), encoding="utf-8")

    assert state_feature.enabled() is False

    import scope_fix as sf
    rc = sf.run(["KLC-976", "--remove", "b"])
    assert rc == 0
    assert json.loads(meta_p.read_text())["affected_modules"] == ["a"]
    assert not (klc / ".git").exists(), "feature-off scope-fix must touch no git"


def test_scope_fix_rejects_malformed_module_list(tmp_path, monkeypatch):
    """A malformed list (empty entry from a stray comma) is rejected before any
    write — the meta slice is left unchanged."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / "KLC-978"
    tdir.mkdir(parents=True)
    meta_p = tdir / "meta.json"
    meta_p.write_text(
        json.dumps(_meta("KLC-978", phase="archived", track="M",
                         affected=["a"])), encoding="utf-8")

    import scope_fix as sf
    rc = sf.run(["KLC-978", "--modules", "a,,b"])
    assert rc != 0, "a malformed module list must be rejected"
    assert json.loads(meta_p.read_text())["affected_modules"] == ["a"], \
        "the slice must be unchanged when the input is rejected"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
