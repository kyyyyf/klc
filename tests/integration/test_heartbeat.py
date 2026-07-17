"""KLC-064 — `klc heartbeat`: throttled, feature-ON heartbeat_at propagation.

Drives the verb against a REAL local `klc-state` worktree bound to a LOCAL
bare-repo upstream (no network), mirroring test_klc061_wrap_verbs.py. Nothing is
stubbed except identity. The verb refreshes an actively-held ticket's
`meta.holder.heartbeat_at` and CAS-pushes it through the KLC-061 `state_tx`
holder envelope — but THROTTLED to at most one push per
`HOLDER_TTL_SECONDS // 3` per held ticket, and only when the multi-user feature
is ON. Feature-OFF and within-window calls are pure no-ops (KLC-062 no-churn).
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import io
import json
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
import state_feature  # noqa: E402
import holder  # noqa: E402

ALICE = "alice@example.com"
BOB = "bob@example.com"
PHASES_DIR = _FW_ROOT / "core" / "phases"
PLUGIN_DIR = _FW_ROOT / "klc-plugin"


def _load_heartbeat():
    """Import core/phases/heartbeat.py as a standalone module."""
    path = PHASES_DIR / "heartbeat.py"
    spec = importlib.util.spec_from_file_location("klc_phase_heartbeat", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now_z(delta_s: float = 0.0) -> str:
    t = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=delta_s)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _holder(who: str = ALICE, *, since_ago: float = 4000.0,
            heartbeat_ago: float | None = None) -> dict:
    h = {"id": who, "machine": "boxA", "since": _now_z(-since_ago)}
    if heartbeat_ago is not None:
        h["heartbeat_at"] = _now_z(-heartbeat_ago)
    return h


def _meta(ticket: str, *, phase: str, track: str, holder=None) -> dict:
    m = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if holder is not None:
        m["holder"] = holder
    return m


def _build_state_repo(tmp_path: Path, ticket: str, *, phase: str = "build:work",
                      track: str = "M", holder=None) -> Path:
    """Real `.klc/` klc-state worktree with a bare-repo upstream. Feature ON."""
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
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    return klc


def _plain_state_repo(tmp_path: Path, ticket: str, *, phase: str = "build:work",
                      track: str = "M", holder=None) -> Path:
    """Plain `.klc/` directory (no git) — feature OFF."""
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(
        json.dumps(_meta(ticket, phase=phase, track=track, holder=holder),
                   indent=2) + "\n", encoding="utf-8")
    return klc


def _local_meta(klc: Path, ticket: str) -> dict:
    return json.loads((klc / "tickets" / ticket / "meta.json").read_text())


def _remote_meta(klc: Path, ticket: str) -> dict:
    _git(klc, "fetch", "origin")
    return json.loads(_git(klc, "show", f"origin/klc-state:tickets/{ticket}/meta.json"))


def _commit_count(klc: Path) -> int:
    return int(_git(klc, "rev-list", "--count", "klc-state").strip())


def _run(mod, argv=None) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = int(mod.run(list(argv or [])))
    return rc, buf.getvalue()


# --------------------------------------------------------------------------- #
# constant
# --------------------------------------------------------------------------- #

def test_push_interval_is_one_third_of_ttl_and_below_it():
    assert holder.HEARTBEAT_PUSH_INTERVAL_SECONDS == holder.HOLDER_TTL_SECONDS // 3
    assert 0 < holder.HEARTBEAT_PUSH_INTERVAL_SECONDS < holder.HOLDER_TTL_SECONDS


# --------------------------------------------------------------------------- #
# AC-1 — feature-ON real writer via state_tx CAS-push
# --------------------------------------------------------------------------- #

def test_feature_on_first_push_advances_heartbeat_at_at_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-900", holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True
    hb = _load_heartbeat()

    rc, out = _run(hb)
    assert rc == 0, out
    local = _local_meta(klc, "KLC-900")
    assert "heartbeat_at" in local["holder"], f"heartbeat_at not written: {local['holder']}"
    remote = _remote_meta(klc, "KLC-900")
    assert remote["holder"].get("heartbeat_at") == local["holder"]["heartbeat_at"], \
        "heartbeat_at must be durable on origin (CAS-pushed), not local-only"
    # since preserved
    assert remote["holder"]["since"] == _local_meta(klc, "KLC-900")["holder"]["since"]


# --------------------------------------------------------------------------- #
# AC-2 — throttle: within-window no-op (no churn) + at most one push/window
# --------------------------------------------------------------------------- #

def test_within_window_is_readonly_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-901", holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hb = _load_heartbeat()

    _run(hb)  # first call → propagates
    bytes_after_push = (klc / "tickets" / "KLC-901" / "meta.json").read_bytes()
    commits_after_push = _commit_count(klc)

    rc, out = _run(hb)  # second call, well within the window
    assert rc == 0, out
    assert (klc / "tickets" / "KLC-901" / "meta.json").read_bytes() == bytes_after_push, \
        "within-window heartbeat must not rewrite meta.json (KLC-062 no-churn)"
    assert _git(klc, "status", "--porcelain").strip() == "", "tree must stay clean"
    assert _commit_count(klc) == commits_after_push, "no extra commit within window"


def test_at_most_one_push_per_window(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-902", holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hb = _load_heartbeat()

    before = _commit_count(klc)
    for _ in range(5):
        _run(hb)
    assert _commit_count(klc) - before == 1, \
        "exactly one CAS-push per throttle window across many calls"


# --------------------------------------------------------------------------- #
# AC-3 — steal-safety: fresh heartbeat blocks steal; TTL silence allows it
# --------------------------------------------------------------------------- #

def test_long_hold_active_holder_not_stealable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-903", holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hb = _load_heartbeat()

    _run(hb)  # ALICE (active) heartbeats → heartbeat_at fresh
    bob = {"id": BOB, "machine": "peerbox"}
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-903", bob)  # default TTL → refused (fresh)

    # Simulate a full TTL of heartbeat silence: age the heartbeat_at past the TTL.
    m = _local_meta(klc, "KLC-903")
    m["holder"]["heartbeat_at"] = _now_z(-(holder.HOLDER_TTL_SECONDS + 100))
    (klc / "tickets" / "KLC-903" / "meta.json").write_text(
        json.dumps(m, indent=2) + "\n", encoding="utf-8")
    result = holder.steal_holder("KLC-903", bob)  # now stealable
    assert result["holder"]["id"] == BOB


# --------------------------------------------------------------------------- #
# AC-4 — feature-OFF byte-parity + best-effort never crashes
# --------------------------------------------------------------------------- #

def test_feature_off_meta_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _plain_state_repo(tmp_path, "KLC-904", holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is False
    hb = _load_heartbeat()

    before = (klc / "tickets" / "KLC-904" / "meta.json").read_bytes()
    rc, out = _run(hb)
    assert rc == 0, out
    assert (klc / "tickets" / "KLC-904" / "meta.json").read_bytes() == before, \
        "feature-OFF heartbeat must leave meta.json byte-identical"
    assert not (klc / ".git").exists(), "feature-OFF must create no git repo"


def test_advisory_never_crashes_no_holder(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_state_repo(tmp_path, "KLC-905", holder=None)  # unheld
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hb = _load_heartbeat()
    rc, out = _run(hb)
    assert rc == 0 and "traceback" not in out.lower(), out


def test_advisory_never_crashes_corrupt_holder(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-906", holder=_holder(ALICE))
    # Corrupt the holder to a non-dict.
    m = _local_meta(klc, "KLC-906")
    m["holder"] = "not-a-dict"
    (klc / "tickets" / "KLC-906" / "meta.json").write_text(
        json.dumps(m, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hb = _load_heartbeat()
    rc, out = _run(hb)
    assert rc == 0 and "traceback" not in out.lower(), out


def test_advisory_never_crashes_no_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_state_repo(tmp_path, "KLC-907", holder=_holder(ALICE))

    def _boom():
        raise SystemExit("no identity")
    monkeypatch.setattr(identity, "current", _boom)
    hb = _load_heartbeat()
    rc, out = _run(hb)
    assert rc == 0, out


def test_advisory_never_crashes_on_push_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-908", holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    # Reject every push on the bare so the CAS push fails terminally.
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    hb = _load_heartbeat()

    rc, out = _run(hb)
    assert rc == 0, f"heartbeat is best-effort; a rejected push must not crash:\n{out}"
    assert "traceback" not in out.lower(), out
    assert _git(klc, "status", "--porcelain").strip() == "", \
        "a rejected push must roll back to a clean tree"
    # heartbeat_at rolled back (holder had none to begin with)
    assert "heartbeat_at" not in _local_meta(klc, "KLC-908")["holder"]


def test_other_identity_holder_not_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-909", holder=_holder(BOB, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)  # ALICE runs; BOB holds
    before = (klc / "tickets" / "KLC-909" / "meta.json").read_bytes()
    hb = _load_heartbeat()
    rc, out = _run(hb)
    assert rc == 0, out
    assert (klc / "tickets" / "KLC-909" / "meta.json").read_bytes() == before, \
        "must never refresh a holder owned by another identity"


def test_non_work_phase_not_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-910", phase="build:ack-needed",
                            holder=_holder(ALICE, since_ago=4000))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    before = (klc / "tickets" / "KLC-910" / "meta.json").read_bytes()
    hb = _load_heartbeat()
    rc, out = _run(hb)
    assert rc == 0, out
    assert (klc / "tickets" / "KLC-910" / "meta.json").read_bytes() == before, \
        "only <phase>:work tickets are heartbeated"


# --------------------------------------------------------------------------- #
# hook — non-blocking, silent, always exit 0
# --------------------------------------------------------------------------- #

def _load_hook():
    path = PLUGIN_DIR / "hooks" / "heartbeat.py"
    spec = importlib.util.spec_from_file_location("klc_hook_heartbeat", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hook_exits_0_on_child_failure(monkeypatch, capsys):
    hook = _load_hook()
    # Point KLC_BIN at a command that fails and writes to stderr.
    monkeypatch.setenv("KLC_BIN", "sh -c 'echo boom >&2; exit 3'")
    rc = hook.main()
    assert rc == 0
    out = capsys.readouterr()
    assert out.out == "", "heartbeat hook is silent — never forwards child stdout"


def test_hook_exits_0_when_bin_missing(monkeypatch):
    hook = _load_hook()
    monkeypatch.setenv("KLC_BIN", "definitely-not-a-real-binary-xyz")
    assert hook.main() == 0


# --------------------------------------------------------------------------- #
# CLI dispatch — feature-OFF smoke through scripts/klc
# --------------------------------------------------------------------------- #

def test_cli_dispatches_heartbeat_feature_off(tmp_path):
    klc = _plain_state_repo(tmp_path, "KLC-911", holder=_holder(ALICE))
    r = subprocess.run(
        [sys.executable, str(_FW_ROOT / "scripts" / "klc"), "heartbeat"],
        capture_output=True, text=True,
        env={"PROJECT_ROOT": str(tmp_path), "PATH": __import__("os").environ["PATH"],
             "HOME": str(tmp_path)},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


# --------------------------------------------------------------------------- #
# FIX-1 (P2) — per-ticket resilience: one locked ticket must not starve the scan
# --------------------------------------------------------------------------- #

def test_scan_continues_when_one_ticket_lock_fails(tmp_path, monkeypatch):
    from artefacts import LockedError

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-920", holder=_holder(ALICE, since_ago=4000))
    # A SECOND ALICE-held :work ticket, later in sorted order than KLC-920.
    tdir = klc / "tickets" / "KLC-921"
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(
        json.dumps(_meta("KLC-921", phase="build:work", track="M",
                         holder=_holder(ALICE, since_ago=4000)), indent=2) + "\n",
        encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "add KLC-921")
    _git(klc, "push", "origin", "klc-state")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    hb = _load_heartbeat()
    real_lock = hb.acquire_lock

    def flaky(ticket):
        if ticket == "KLC-920":
            raise LockedError("KLC-920 held by another live process")
        return real_lock(ticket)
    monkeypatch.setattr(hb, "acquire_lock", flaky)

    rc, out = _run(hb)
    assert rc == 0, out
    # KLC-920's lock failed → skipped; the scan MUST still reach KLC-921.
    assert "heartbeat_at" in _local_meta(klc, "KLC-921")["holder"], \
        "a locked/failing ticket must not starve the rest of the scan"


# --------------------------------------------------------------------------- #
# FIX-3 (LOW) — a deleted/unreadable process cwd must still exit 0 (AC-4)
# --------------------------------------------------------------------------- #

def test_getcwd_failure_still_exits_0(tmp_path, monkeypatch):
    import os as _os
    _plain_state_repo(tmp_path, "KLC-912", holder=_holder(ALICE))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hb = _load_heartbeat()

    real_getcwd = _os.getcwd
    state = {"n": 0}

    def boom():
        state["n"] += 1
        if state["n"] == 1:  # only the verb's own first getcwd is broken
            raise FileNotFoundError("cwd was deleted")
        return real_getcwd()
    monkeypatch.setattr(hb.os, "getcwd", boom)

    rc, out = _run(hb)
    assert rc == 0, f"a deleted cwd must not crash the advisory verb:\n{out}"
