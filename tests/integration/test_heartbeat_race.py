"""KLC-064 AC-5 — steal-vs-heartbeat coherence on a REAL bare-repo substrate.

Two worktrees (ALICE = active holder heartbeating, BOB = peer stealing) share a
LOCAL bare-repo `klc-state` upstream (no network, nothing stubbed except
identity). We assert the coherence invariant across interleavings:

  * DETERMINISTIC sequential orderings prove post-pull coherence:
      - heartbeat-then-steal: BOB pulls ALICE's fresh heartbeat → steal REFUSED.
      - steal-then-heartbeat: BOB steals a stale holder → ALICE's later heartbeat
        is a no-op (ALICE no longer holds).
  * A TRUE-CONCURRENT round (multiprocessing.Barrier, mirroring
    test_klc057_fuzz_concurrent.py) forces a same-base CAS race: both actors pull
    the same stale base, then push at once. `commit_and_push_cas_subtree` rejects
    the same-ticket non-fast-forward with StateConflictError (no retry, no
    clobber), so EXACTLY one writer wins and the origin holder stays coherent —
    who-wins-agnostic. This is the KLC-057 lesson: only a real CAS substrate
    surfaces the ordering, a stub hides it.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import multiprocessing as _mp
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))
sys.path.append(str(_FW_ROOT / "core" / "shared"))

import identity  # noqa: E402
import holder  # noqa: E402
import state_feature  # noqa: E402

ALICE = "alice@example.com"
BOB = "bob@example.com"
KEY = "KLC-950"
_ROUNDS = int(os.environ.get("KLC_HB_RACE_ROUNDS", "10"))
_CLEAN_ABORT_MARKERS = (
    "concurrent update", "remote state advanced", "refusing to steal",
    "actively held", "resolve manually", "still actively",
)


def _now_z(delta_s: float = 0.0) -> str:
    t = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=delta_s)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {cwd} failed: {r.stderr or r.stdout}")
    return r.stdout


def _meta(holder: dict) -> dict:
    return {
        "ticket": KEY, "kind": "feature", "kind_source": "user",
        "phase": "build:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high", "affected_modules": [],
        "estimate": None, "layer": "code", "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z", "holder": holder,
    }


def _stale_alice() -> dict:
    # since older than the default TTL, no heartbeat_at → looks stealable to BOB
    # and out-of-window (propagate) to ALICE's heartbeat.
    return {"id": ALICE, "machine": "boxA", "since": _now_z(-(holder.HOLDER_TTL_SECONDS + 2000))}


def _build_two_worktrees(tmp_path: Path):
    """bare origin + ALICE worktree (seeds KEY held-stale) + BOB clone. Returns
    (alice_root, bob_root, bare)."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    alice_root = tmp_path / "alice"
    aklc = alice_root / ".klc"
    aklc.mkdir(parents=True)
    _git(aklc, "init", "-q", "-b", "klc-state")
    _git(aklc, "config", "user.email", ALICE)
    _git(aklc, "config", "user.name", "Alice")
    _git(aklc, "config", "commit.gpgsign", "false")
    tdir = aklc / "tickets" / KEY
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps(_meta(_stale_alice()), indent=2) + "\n")
    _git(aklc, "add", "-A")
    _git(aklc, "commit", "-q", "-m", f"seed {KEY}")
    _git(aklc, "remote", "add", "origin", str(bare))
    _git(aklc, "push", "-q", "-u", "origin", "klc-state")
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")

    bob_root = tmp_path / "bob"
    bklc = bob_root / ".klc"
    _git(tmp_path, "clone", "-q", str(bare), str(bklc))
    _git(bklc, "config", "user.email", BOB)
    _git(bklc, "config", "user.name", "Bob")
    _git(bklc, "config", "commit.gpgsign", "false")
    return alice_root, bob_root, bare


def _origin_meta(any_klc: Path) -> dict:
    _git(any_klc, "fetch", "-q", "origin")
    return json.loads(_git(any_klc, "show", f"origin/klc-state:tickets/{KEY}/meta.json"))


def _origin_commit_count(any_klc: Path) -> int:
    _git(any_klc, "fetch", "-q", "origin")
    return int(_git(any_klc, "rev-list", "--count", "origin/klc-state").strip())


def _fresh(h: dict) -> bool:
    try:
        return holder._holder_age_seconds(h) < holder.HOLDER_TTL_SECONDS
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# in-process runner for the DETERMINISTIC sequential orderings
# --------------------------------------------------------------------------- #

def _run_verb(root: Path, email: str, verb: str, argv, monkeypatch) -> tuple[int, str]:
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.setattr(identity, "current", lambda: email)
    mod = __import__(verb)
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = int(mod.run(list(argv)))
    return rc, buf.getvalue()


def test_sequential_heartbeat_then_steal_refuses(tmp_path, monkeypatch):
    alice_root, bob_root, _ = _build_two_worktrees(tmp_path)
    aklc = alice_root / ".klc"
    assert state_feature.enabled.__module__  # sanity import

    # ALICE heartbeats first (propagates a fresh heartbeat_at to origin).
    monkeypatch.setenv("PROJECT_ROOT", str(alice_root))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True
    import heartbeat as hb
    rc_hb, out_hb = _run_verb(alice_root, ALICE, "heartbeat", [], monkeypatch)
    assert rc_hb == 0, out_hb
    assert "heartbeat_at" in _origin_meta(aklc)["holder"]

    # BOB now steals: state_tx pulls ALICE's fresh heartbeat → must REFUSE.
    rc_steal, out_steal = _run_verb(bob_root, BOB, "steal", [KEY], monkeypatch)
    assert rc_steal != 0, f"steal must refuse a freshly-heartbeated holder:\n{out_steal}"
    assert "traceback" not in out_steal.lower(), out_steal
    remote = _origin_meta(aklc)
    assert remote["holder"]["id"] == ALICE and _fresh(remote["holder"]), \
        f"active holder must be preserved, got {remote['holder']}"


def test_sequential_steal_then_heartbeat_is_noop(tmp_path, monkeypatch):
    alice_root, bob_root, _ = _build_two_worktrees(tmp_path)
    aklc = alice_root / ".klc"

    # BOB steals the stale holder first → holder becomes BOB on origin.
    rc_steal, out_steal = _run_verb(bob_root, BOB, "steal", [KEY], monkeypatch)
    assert rc_steal == 0, f"a stale holder must be stealable:\n{out_steal}"
    assert _origin_meta(aklc)["holder"]["id"] == BOB
    count_after_steal = _origin_commit_count(aklc)

    # ALICE heartbeats: state_tx pulls, sees BOB holds → writes nothing (no-op).
    rc_hb, out_hb = _run_verb(alice_root, ALICE, "heartbeat", [], monkeypatch)
    assert rc_hb == 0, out_hb
    remote = _origin_meta(aklc)
    assert remote["holder"]["id"] == BOB, "ALICE must NOT refresh a holder she lost"
    assert _origin_commit_count(aklc) == count_after_steal, \
        "a no-op heartbeat must not push a commit"


# --------------------------------------------------------------------------- #
# TRUE-CONCURRENT CAS race (multiprocessing.Barrier) — who-wins-agnostic
# --------------------------------------------------------------------------- #

def _race_worker(barrier, root: str, email: str, verb: str, argv, q) -> None:
    os.environ["PROJECT_ROOT"] = str(root)
    sys.path.insert(0, str(_FW_ROOT))
    sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
    sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))
    sys.path.append(str(_FW_ROOT / "core" / "shared"))
    import identity as _id
    import state_sync
    _id.current = lambda: email

    _orig_push = state_sync.commit_and_push_cas_subtree

    def _hooked(*a, **k):
        try:
            barrier.wait()  # release the race only once BOTH have pulled + staged
        except Exception:
            pass
        return _orig_push(*a, **k)

    state_sync.commit_and_push_cas_subtree = _hooked

    buf = io.StringIO()
    rc = -998
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            mod = __import__(verb)
            rc = int(mod.run(list(argv)))
    except BaseException as exc:  # noqa: BLE001 — a crash is a reportable outcome
        rc = -999
        buf.write(f"\nCRASH {type(exc).__name__}: {exc}\n")
    finally:
        q.put((verb, rc, buf.getvalue()))


@pytest.mark.parametrize("_round", range(_ROUNDS))
def test_concurrent_steal_vs_heartbeat_coherent(tmp_path, _round):
    alice_root, bob_root, _ = _build_two_worktrees(tmp_path)
    aklc = alice_root / ".klc"
    seed_count = _origin_commit_count(aklc)

    ctx = _mp.get_context("fork")
    barrier = ctx.Barrier(2, timeout=40)
    q = ctx.Queue()
    procs = [
        ctx.Process(target=_race_worker,
                    args=(barrier, str(alice_root), ALICE, "heartbeat", [], q)),
        ctx.Process(target=_race_worker,
                    args=(barrier, str(bob_root), BOB, "steal", [KEY], q)),
    ]
    for p in procs:
        p.start()
    results = {}
    for _ in procs:
        verb, rc, out = q.get(timeout=60)
        results[verb] = (rc, out)
    for p in procs:
        p.join(timeout=60)

    # 1. no crash in either actor.
    for verb, (rc, out) in results.items():
        assert rc != -999, f"{verb} crashed:\n{out}"
        assert "traceback" not in out.lower(), f"{verb} leaked a traceback:\n{out}"
    rc_hb, _ = results["heartbeat"]
    rc_steal, out_steal = results["steal"]
    assert rc_hb == 0, "heartbeat is best-effort and always exits 0"

    # 2. origin advanced by EXACTLY one commit — a single CAS winner, no clobber.
    assert _origin_commit_count(aklc) - seed_count == 1, \
        "exactly one writer may win the same-ticket CAS race"

    # 3. origin holder is coherent and the steal outcome matches it.
    remote = _origin_meta(aklc)
    h = remote["holder"]
    assert isinstance(h, dict) and h.get("id") in (ALICE, BOB), f"incoherent holder: {h}"
    if rc_steal == 0:
        assert h["id"] == BOB, "steal reported success but BOB is not the holder"
    else:
        assert h["id"] == ALICE and _fresh(h), \
            "steal was refused → ALICE must remain holder with a fresh heartbeat"
        assert any(m in out_steal.lower() for m in _CLEAN_ABORT_MARKERS), \
            f"a refused steal must abort cleanly with a diagnostic:\n{out_steal}"
