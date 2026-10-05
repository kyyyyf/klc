"""KLC-180 step-1 — core/skills/klc_hook.py: the logic of the single hook.

`active_ticket` finds the ticket (branch first, then the one held ticket),
`pending_line` words the human decision without writing, `heartbeat_due` and
`refresh_heartbeat` carry the old `heartbeat` verb's behaviour (feature off and
within-window are no-ops). Real git repos in tmp dirs; only identity is stubbed.
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import identity  # noqa: E402
import holder  # noqa: E402

ALICE = "alice@example.com"
BOB = "bob@example.com"


def _now_z(delta_s: float = 0.0) -> str:
    t = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=delta_s)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                       env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd), "PATH": "/usr/bin:/bin"})
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _meta(ticket: str, phase: str = "build:work", holder_=None) -> dict:
    m = {"ticket": ticket, "kind": "feature", "kind_source": "user", "phase": phase,
         "phase_history": [], "track": "M", "route_hint": "M", "route_confidence": "high",
         "affected_modules": [], "estimate": None, "layer": "code",
         "budgets": {"mutation_fix_attempts": 0}, "jira_url": None,
         "created": "2026-01-01T00:00:00Z"}
    if holder_ is not None:
        m["holder"] = holder_
    return m


def _holder(who=ALICE, since_ago=4000.0, heartbeat_ago=None) -> dict:
    h = {"id": who, "machine": "boxA", "since": _now_z(-since_ago)}
    if heartbeat_ago is not None:
        h["heartbeat_at"] = _now_z(-heartbeat_ago)
    return h


def _write(tickets: Path, ticket: str, **kw) -> Path:
    d = tickets / ticket
    d.mkdir(parents=True, exist_ok=True)
    p = d / "meta.json"
    p.write_text(json.dumps(_meta(ticket, **kw), indent=2) + "\n", encoding="utf-8")
    return p


def _repo(tmp_path: Path, branch: str) -> Path:
    _git(tmp_path, "init", "-b", branch)
    _git(tmp_path, "config", "user.email", ALICE)
    _git(tmp_path, "config", "user.name", "Alice")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "f").write_text("x")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    import klc_hook
    return tmp_path, tmp_path / ".klc" / "tickets", klc_hook


# --- active_ticket ---------------------------------------------------------

def test_active_ticket_from_branch_then_holder(env):
    root, tickets, hook = env
    _write(tickets, "KLC-901")
    _write(tickets, "KLC-902", holder_=_holder(ALICE))
    _repo(root, "feature/klc-901-some-work")
    assert hook.active_ticket(root, tickets) == "KLC-901"      # branch wins over the holder
    _git(root, "checkout", "-b", "scratch")
    assert hook.active_ticket(root, tickets) == "KLC-902"      # else the single held ticket


def test_active_ticket_none_cases(env):
    root, tickets, hook = env
    _repo(root, "scratch")
    assert hook.active_ticket(root, tickets) is None           # no tickets at all
    _write(tickets, "KLC-903", holder_=_holder(ALICE))
    _write(tickets, "KLC-904", holder_=_holder(ALICE))
    assert hook.active_ticket(root, tickets) is None           # two held: ambiguous
    _write(tickets, "KLC-904", phase="archived", holder_=_holder(ALICE))
    assert hook.active_ticket(root, tickets) == "KLC-903"      # archived is not live
    _git(root, "checkout", "-b", "feature/klc-999-ghost")
    assert hook.active_ticket(root, tickets) == "KLC-903"      # branch names no real ticket
    _write(tickets, "KLC-905", holder_=_holder(BOB))
    assert hook.active_ticket(root / "missing", tickets) == "KLC-903"  # bad cwd never raises


def test_active_ticket_never_raises_on_corrupt_meta(env):
    root, tickets, hook = env
    _repo(root, "feature/klc-906-x")
    d = tickets / "KLC-906"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{not json")
    assert hook.active_ticket(root, tickets) is None


# --- pending_line ----------------------------------------------------------

def test_pending_line_is_read_only(env):
    root, tickets, hook = env
    p = _write(tickets, "KLC-910", phase="design:ack-needed")
    before = p.read_bytes()
    line = hook.pending_line("KLC-910")
    assert line and "\n" not in line
    assert "KLC-910" in line and "design" in line and "klc go KLC-910" in line
    assert p.read_bytes() == before, "the advisory probe must not write meta.json"


def test_pending_line_none_when_nothing_pending(env):
    root, tickets, hook = env
    _write(tickets, "KLC-911", phase="build:work")             # outputs missing: the agent works
    assert hook.pending_line("KLC-911") is None
    _write(tickets, "KLC-912", phase="archived")
    assert hook.pending_line("KLC-912") is None
    assert hook.pending_line("KLC-999") is None                # unknown ticket never raises


# --- heartbeat -------------------------------------------------------------

def _state_repo(tmp_path: Path, ticket: str, holder_) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    _write(klc / "tickets", ticket, holder_=holder_)
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "origin", str(bare))
    _git(klc, "push", "-u", "origin", "klc-state")
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    return klc


def test_heartbeat_feature_off_is_noop(env):
    root, tickets, hook = env
    p = _write(tickets, "KLC-920", holder_=_holder(ALICE, since_ago=4000))
    before = p.read_bytes()
    assert hook.heartbeat_due("KLC-920", _dt.datetime.now(_dt.timezone.utc)) is False
    hook.refresh_heartbeat("KLC-920")
    assert p.read_bytes() == before


def test_heartbeat_within_window_is_noop(env):
    root, tickets, hook = env
    klc = _state_repo(root, "KLC-921", _holder(ALICE, since_ago=4000, heartbeat_ago=10))
    p = klc / "tickets" / "KLC-921" / "meta.json"
    before = p.read_bytes()
    commits = _git(klc, "rev-list", "--count", "klc-state")
    now = _dt.datetime.now(_dt.timezone.utc)
    assert hook.heartbeat_due("KLC-921", now) is False
    hook.refresh_heartbeat("KLC-921")
    assert p.read_bytes() == before
    assert _git(klc, "rev-list", "--count", "klc-state") == commits


def test_heartbeat_due_then_refresh_pushes_to_origin(env):
    root, tickets, hook = env
    klc = _state_repo(root, "KLC-922", _holder(ALICE, since_ago=4000))
    now = _dt.datetime.now(_dt.timezone.utc)
    assert hook.heartbeat_due("KLC-922", now) is True
    hook.refresh_heartbeat("KLC-922")
    local = json.loads((klc / "tickets" / "KLC-922" / "meta.json").read_text())
    assert "heartbeat_at" in local["holder"]
    _git(klc, "fetch", "origin")
    remote = json.loads(_git(klc, "show", "origin/klc-state:tickets/KLC-922/meta.json"))
    assert remote["holder"]["heartbeat_at"] == local["holder"]["heartbeat_at"]
    assert hook.heartbeat_due("KLC-922", _dt.datetime.now(_dt.timezone.utc)) is False


def test_heartbeat_not_due_for_other_holder(env):
    root, tickets, hook = env
    _state_repo(root, "KLC-923", _holder(BOB, since_ago=4000))
    assert hook.heartbeat_due("KLC-923", _dt.datetime.now(_dt.timezone.utc)) is False
    assert hook.heartbeat_due("KLC-000", _dt.datetime.now(_dt.timezone.utc)) is False


# --- step-2: spawn_heartbeat and the hook script ---------------------------

HOOK = _FW_ROOT / "klc-plugin" / "hooks" / "klc.py"


def test_spawn_heartbeat_is_detached_and_not_awaited(env, monkeypatch):
    root, tickets, hook = env
    calls = []

    class _P:
        def wait(self, *a, **k):
            raise AssertionError("the hook must never wait for the heartbeat")

    def _popen(args, **kw):
        calls.append((args, kw))
        return _P()

    monkeypatch.setattr(hook.subprocess, "Popen", _popen)
    hook.spawn_heartbeat("KLC-930")
    (args, kw), = calls
    assert kw.get("start_new_session") is True
    assert "refresh_heartbeat" in " ".join(args) and "KLC-930" in " ".join(args)
    monkeypatch.setattr(hook.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no fork")))
    hook.spawn_heartbeat("KLC-930")                            # never raises


def _hook_env(root: Path, extra_path: Path | None = None) -> dict:
    import os
    e = {k: v for k, v in os.environ.items() if k not in ("KLC_FRAMEWORK_ROOT", "KLC_TICKETS_DIR")}
    e["PROJECT_ROOT"] = str(root)
    e["HOME"] = str(root)
    e["GIT_CONFIG_GLOBAL"] = str(root / ".gitconfig")
    if extra_path is not None:
        e["PATH"] = f"{extra_path}:{e['PATH']}"
    return e


def _run_hook(root: Path, stdin: str = "{}", extra_path: Path | None = None):
    import time
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, str(HOOK)], input=stdin, cwd=str(root),
                       capture_output=True, text=True, env=_hook_env(root, extra_path),
                       timeout=20)
    return p, time.monotonic() - t0


def test_hook_emits_systemmessage_json(env):
    root, tickets, _ = env
    _write(tickets, "KLC-940", phase="design:ack-needed")
    _repo(root, "feature/klc-940-x")
    p, _ = _run_hook(root, json.dumps({"prompt": "hi", "cwd": str(root)}))
    assert p.returncode == 0 and p.stderr == ""
    obj = json.loads(p.stdout)
    assert list(obj) == ["systemMessage"]
    assert "KLC-940" in obj["systemMessage"] and "\n" not in obj["systemMessage"]
    assert "/klc:go KLC-940" in obj["systemMessage"]           # AC-2: the slash command
    assert p.stdout.strip().count("\n") == 0


def test_hook_finds_ticket_from_holder(env):
    root, tickets, _ = env
    _write(tickets, "KLC-941", phase="design:ack-needed", holder_=_holder(ALICE))
    _repo(root, "scratch")
    p, _ = _run_hook(root)
    assert p.returncode == 0
    assert "KLC-941" in json.loads(p.stdout)["systemMessage"]


def test_hook_silent_without_ticket(env):
    root, tickets, _ = env
    _repo(root, "scratch")
    p, _ = _run_hook(root)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")
    _write(tickets, "KLC-942", phase="build:work")
    _git(root, "checkout", "-b", "feature/klc-942-y")
    p, _ = _run_hook(root)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


@pytest.mark.parametrize("stdin", ["", "garbage", "[1,2", "null", '{"cwd": 5}', "\x00\xff"])
def test_hook_never_blocks_on_bad_input(env, stdin):
    root, tickets, _ = env
    _repo(root, "scratch")
    p, _ = _run_hook(root, stdin)
    assert (p.returncode, p.stderr) == (0, "")


def test_hook_never_blocks_on_corrupt_meta(env):
    root, tickets, _ = env
    _repo(root, "feature/klc-943-z")
    d = tickets / "KLC-943"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{broken")
    p, _ = _run_hook(root)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_hook_under_two_seconds_with_hanging_klc(env, tmp_path_factory):
    root, tickets, _ = env
    _write(tickets, "KLC-944", phase="design:ack-needed")
    _repo(root, "feature/klc-944-w")
    fake = tmp_path_factory.mktemp("fakebin")
    marker = fake / "called"
    klc = fake / "klc"
    klc.write_text(f"#!/bin/sh\ntouch {marker}\nsleep 30\n")
    klc.chmod(0o755)
    p, elapsed = _run_hook(root, extra_path=fake)
    assert p.returncode == 0 and "KLC-944" in p.stdout
    assert elapsed < 2.0, elapsed
    assert not marker.exists(), "the hook must not call `klc` at all"


def _load_hook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_klc180_hook_script", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_hook_spawns_detached_heartbeat_only_when_due(env, monkeypatch, capsys):
    import io
    root, tickets, hook = env
    _write(tickets, "KLC-945", phase="build:work", holder_=_holder(ALICE))
    _repo(root, "feature/klc-945-v")
    monkeypatch.chdir(root)
    spawned = []
    monkeypatch.setattr(hook, "spawn_heartbeat", spawned.append)
    script = _load_hook()
    monkeypatch.setattr(hook, "heartbeat_due", lambda t, now=None: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert script.main() == 0 and spawned == []
    monkeypatch.setattr(hook, "heartbeat_due", lambda t, now=None: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert script.main() == 0 and spawned == ["KLC-945"]
    assert capsys.readouterr().out == ""                       # build:work: nothing pending


def test_hook_survives_helper_failure(env, monkeypatch):
    import io
    root, tickets, hook = env
    _repo(root, "scratch")
    monkeypatch.chdir(root)

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(hook, "active_ticket", _boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert _load_hook().main() == 0


# --- step-2: ported from the retired heartbeat verb tests ------------------

def _two_clones(tmp_path: Path, ticket: str):
    klc = _state_repo(tmp_path, ticket, _holder(ALICE, since_ago=holder.HOLDER_TTL_SECONDS + 2000))
    bob_klc = tmp_path / "bob" / ".klc"
    bob_klc.parent.mkdir()
    _git(tmp_path, "clone", str(tmp_path / "remote.git"), str(bob_klc))
    _git(bob_klc, "config", "user.email", BOB)
    _git(bob_klc, "config", "user.name", "Bob")
    _git(bob_klc, "config", "commit.gpgsign", "false")
    return klc, tmp_path / "bob"


def test_steal_then_refresh_heartbeat_writes_nothing(env, monkeypatch):
    root, tickets, hook = env
    klc, bob_root = _two_clones(root, "KLC-924")
    monkeypatch.setenv("PROJECT_ROOT", str(bob_root))
    monkeypatch.setattr(identity, "current", lambda: BOB)
    sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))
    import steal
    assert steal.run(["KLC-924"]) == 0
    _git(klc, "fetch", "origin")
    count = _git(klc, "rev-list", "--count", "origin/klc-state")
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    hook.refresh_heartbeat("KLC-924")                          # Alice lost the ticket: no-op
    _git(klc, "fetch", "origin")
    assert _git(klc, "rev-list", "--count", "origin/klc-state") == count
    remote = json.loads(_git(klc, "show", "origin/klc-state:tickets/KLC-924/meta.json"))
    assert remote["holder"]["id"] == BOB


def test_refresh_then_steal_refuses(env, monkeypatch):
    root, tickets, hook = env
    klc, bob_root = _two_clones(root, "KLC-925")
    hook.refresh_heartbeat("KLC-925")
    monkeypatch.setenv("PROJECT_ROOT", str(bob_root))
    monkeypatch.setattr(identity, "current", lambda: BOB)
    sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))
    import steal
    assert steal.run(["KLC-925"]) != 0
    _git(klc, "fetch", "origin")
    remote = json.loads(_git(klc, "show", "origin/klc-state:tickets/KLC-925/meta.json"))
    assert remote["holder"]["id"] == ALICE


def test_refresh_heartbeat_survives_rejected_push(env):
    root, tickets, hook = env
    klc = _state_repo(root, "KLC-926", _holder(ALICE, since_ago=4000))
    pre = root / "remote.git" / "hooks" / "pre-receive"
    pre.write_text("#!/bin/sh\nexit 1\n")
    pre.chmod(0o755)
    hook.refresh_heartbeat("KLC-926")                          # must not raise
    assert _git(klc, "status", "--porcelain").strip() == ""


# --- review round 1 ---------------------------------------------------------

def test_hook_finds_ticket_from_branch(env):
    root, tickets, _ = env
    _write(tickets, "KLC-946", phase="design:ack-needed")
    _repo(root, "feature/klc-946-q")
    p, _ = _run_hook(root, json.dumps({"cwd": str(root)}))
    assert p.returncode == 0
    assert "KLC-946" in json.loads(p.stdout)["systemMessage"]


def test_pending_line_names_the_slash_command(env, monkeypatch):
    root, tickets, hook = env
    import next_move
    import phases as _ph
    from types import SimpleNamespace as NS
    cases = [
        (NS(action="pick", phase="design", state=_ph.STATE_WORK), "/klc:go KLC-7 --pick N"),
        (NS(action="x", phase="design", state=_ph.STATE_ACK_NEEDED), "/klc:go KLC-7"),
        (NS(action="ack", phase="build", state=_ph.STATE_WORK), "/klc:go KLC-7"),
    ]
    for move, want in cases:
        monkeypatch.setattr(next_move, "compute", lambda t, m=move: m)
        line = hook.pending_line("KLC-7")
        assert line and want in line, (line, want)


def test_hook_works_from_an_external_plugin_install(env, tmp_path_factory):
    """F-001: the plugin copy lives in a cache-like dir outside the repo; the
    project is found from the payload cwd, the framework from its shim."""
    import os
    import shutil
    ext = tmp_path_factory.mktemp("cache") / "mkt" / "klc" / "0.2.0"
    shutil.copytree(_FW_ROOT / "klc-plugin", ext)
    proj = tmp_path_factory.mktemp("scratch-project")
    _write(proj / ".klc" / "tickets", "KLC-950", phase="design:ack-needed")
    shim = proj / ".klc" / "bin" / "klc"
    shim.parent.mkdir(parents=True)
    shim.write_text(f'#!/usr/bin/env bash\nset -eu\nKLC_FW="{_FW_ROOT}"\nexec "$KLC_FW/scripts/klc" "$@"\n')
    _repo(proj, "feature/klc-950-x")
    sub = proj / "sub" / "dir"
    sub.mkdir(parents=True)
    e = {k: v for k, v in os.environ.items()
         if k not in ("KLC_FRAMEWORK_ROOT", "PROJECT_ROOT", "KLC_TICKETS_DIR")}
    e["HOME"] = str(proj)
    other = tmp_path_factory.mktemp("elsewhere")
    p = subprocess.run([sys.executable, str(ext / "hooks" / "klc.py")],
                       input=json.dumps({"cwd": str(sub)}), cwd=str(other),
                       capture_output=True, text=True, env=e, timeout=20)
    assert p.returncode == 0 and p.stderr == ""
    assert "KLC-950" in json.loads(p.stdout)["systemMessage"], p.stdout


def test_hook_heartbeats_every_held_work_ticket(env, monkeypatch):
    """F-003: not only the active ticket: every `:work` ticket this identity holds."""
    import io
    root, tickets, hook = env
    _write(tickets, "KLC-951", phase="build:work", holder_=_holder(ALICE))
    _write(tickets, "KLC-952", phase="build:work", holder_=_holder(ALICE))
    _write(tickets, "KLC-953", phase="design:ack-needed", holder_=_holder(ALICE))
    _write(tickets, "KLC-954", phase="build:work", holder_=_holder(BOB))
    _repo(root, "scratch")                                      # on neither branch
    assert sorted(hook.held_tickets(ALICE)) == ["KLC-951", "KLC-952"]
    monkeypatch.chdir(root)
    spawned = []
    monkeypatch.setattr(hook, "spawn_heartbeat", spawned.append)
    monkeypatch.setattr(hook, "heartbeat_due", lambda t, now=None: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert _load_hook().main() == 0
    assert sorted(spawned) == ["KLC-951", "KLC-952"]
