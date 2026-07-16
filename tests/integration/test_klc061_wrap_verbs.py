"""KLC-061 — forward/holder verbs (ship, steal, abort, jump, jira) wrapped in state_tx.

These tests drive the verbs against a REAL local `klc-state` worktree bound to a
LOCAL bare-repo upstream (no network), mirroring test_klc057_real_repo.py. Nothing
is stubbed except identity (and the Jira client where relevant). They exercise the
actual `pull → mutate → CAS-push` sequence end-to-end so that a durable-on-origin
mutation, a deferred-Jira flush, and a clean rollback on a rejected push are all
verified on the real substrate — not through a stub (the KLC-057 lesson).
"""
from __future__ import annotations

import datetime as _dt
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
# core/shared appended (not inserted) so core/skills' yaml wrapper wins the
# yaml.py name clash — jira_sync's _pull_impl imports from core.shared.paths.
sys.path.append(str(_FW_ROOT / "core" / "shared"))

import identity  # noqa: E402
import state_feature  # noqa: E402
import holder  # noqa: E402

ALICE = "alice@example.com"
BOB = "bob@example.com"


def _now_z() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _stale_holder(who: str = BOB) -> dict:
    return {"id": who, "machine": "peerbox", "since": "2026-01-01T00:00:00Z"}


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
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    return klc


def _plain_state_repo(tmp_path: Path, ticket: str, *, phase: str, track: str,
                      holder=None) -> Path:
    """Create a PLAIN `.klc/` directory (no git) — feature reads OFF."""
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / ticket
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(
        json.dumps(_meta(ticket, phase=phase, track=track, holder=holder),
                   indent=2) + "\n", encoding="utf-8")
    return klc


def _remote_meta(klc: Path, ticket: str) -> dict:
    _git(klc, "fetch", "origin")
    raw = _git(klc, "show", f"origin/klc-state:tickets/{ticket}/meta.json")
    return json.loads(raw)


def _local_meta(klc: Path, ticket: str) -> dict:
    return json.loads((klc / "tickets" / ticket / "meta.json").read_text(encoding="utf-8"))


def _run(mod, argv) -> tuple[int, str]:
    """Run verb `mod.run(argv)`, capturing combined stdout+stderr. Returns (rc, out)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = int(mod.run(list(argv)))
    return rc, buf.getvalue()


def _reject_pushes(tmp_path: Path) -> None:
    """Install a pre-receive hook on the bare that rejects every push (fetch/pull
    still work), so commit_and_push_cas hits a terminal push failure."""
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


# =========================================================================== #
# step-1 — klc steal wrapped in state_tx
# =========================================================================== #

def test_steal_durable_on_origin(tmp_path, monkeypatch):
    """AC-2: a successful steal of a STALE holder is CAS-pushed to origin, not
    only local — the new holder is visible on the bare remote."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-960", phase="build:work", track="S",
                            holder=_stale_holder(BOB))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True

    import steal as steal_mod
    rc, out = _run(steal_mod, ["KLC-960"])
    assert rc == 0, f"steal of a stale holder must succeed:\n{out}"
    assert "STOLEN" in out, out

    remote = _remote_meta(klc, "KLC-960")
    assert remote["holder"]["id"] == ALICE, \
        f"the steal must be durable on origin, got holder={remote.get('holder')!r}"


def test_steal_staleness_evaluated_after_pull(tmp_path, monkeypatch):
    """AC-2 / C-005: staleness is judged against the freshly-PULLED holder. If a
    peer refreshed the holder on origin, a local (stale) view must not steal a
    now-live holder."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-961", phase="build:work", track="S",
                            holder=_stale_holder(BOB))
    # A peer refreshes bob's holder to FRESH on origin.
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(tmp_path / "remote.git"), str(peer))
    _git(peer, "config", "user.email", BOB)
    _git(peer, "config", "user.name", "Bob")
    pmeta = json.loads((peer / "tickets" / "KLC-961" / "meta.json").read_text())
    pmeta["holder"] = {"id": BOB, "machine": "peerbox", "since": "2026-01-01T00:00:00Z",
                       "heartbeat_at": _now_z()}
    (peer / "tickets" / "KLC-961" / "meta.json").write_text(
        json.dumps(pmeta, indent=2) + "\n", encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "bob heartbeat")
    _git(peer, "push", "origin", "klc-state")

    monkeypatch.setattr(identity, "current", lambda: ALICE)
    import steal as steal_mod
    rc, out = _run(steal_mod, ["KLC-961"])
    assert rc != 0, f"steal must refuse a holder that is fresh on origin:\n{out}"
    assert "traceback" not in out.lower(), out
    remote = _remote_meta(klc, "KLC-961")
    assert remote["holder"]["id"] == BOB, "the live holder must be preserved"


def test_steal_failed_cas_push_leaves_clean_state(tmp_path, monkeypatch):
    """AC-6 (real-substrate): a steal whose CAS push is REJECTED leaves a clean
    local state — holder unchanged, tree + index clean, non-zero exit, no
    traceback. Proven on a real bare repo, not a stub."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-962", phase="build:work", track="S",
                            holder=_stale_holder(BOB))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    _reject_pushes(tmp_path)

    import steal as steal_mod
    rc, out = _run(steal_mod, ["KLC-962"])
    assert rc != 0, "steal must fail while the push is rejected"
    assert "traceback" not in out.lower(), f"no traceback may leak:\n{out}"

    status = _git(klc, "status", "--porcelain").strip()
    assert status == "", f"tree/index not clean after rollback: {status!r}"
    local = _local_meta(klc, "KLC-962")
    assert local["holder"]["id"] == BOB, \
        f"the holder mutation must roll back, got {local.get('holder')!r}"


def test_feature_off_steal_no_git(tmp_path, monkeypatch):
    """AC-5: feature OFF (plain `.klc`), steal still updates the local holder
    (single-user behaviour), writes no git, and does not error."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _plain_state_repo(tmp_path, "KLC-963", phase="build:work", track="S",
                            holder=_stale_holder(BOB))
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is False

    import steal as steal_mod
    rc, out = _run(steal_mod, ["KLC-963"])
    assert rc == 0, f"feature-off steal must succeed locally:\n{out}"
    local = _local_meta(klc, "KLC-963")
    assert local["holder"]["id"] == ALICE, "feature-off steal updates local holder"
    assert not (klc / ".git").exists(), "feature-off must not create a git repo"


# =========================================================================== #
# step-2 — klc ship routed through the wrapped ack.run (+ next.run)
# =========================================================================== #

def test_ship_cas_pushes_advance_in_same_verb(tmp_path, monkeypatch):
    """AC-1: feature-ON `klc ship` advances the phase AND the advance reaches
    origin within the same invocation (via the wrapped ack.run state_tx), not
    riding a later verb's push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-970", phase="build:ack-needed", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True

    import ship as ship_mod
    rc, out = _run(ship_mod, ["KLC-970", "--pick", "1"])
    assert rc == 0, f"feature-on ship must succeed:\n{out}"
    assert "advance_to_next" not in out, f"the double-advance bug must be gone:\n{out}"

    remote = _remote_meta(klc, "KLC-970")
    assert remote["phase"] == "review:work", \
        f"the advance must be CAS-pushed in the same verb, got {remote['phase']!r}"


def test_ship_routes_through_ack_and_next(tmp_path, monkeypatch):
    """AC-1: ship delegates to the wrapped verbs — the ack releases the phase's
    holder (proving it went through ack.run's holder lifecycle, not the old
    direct apply_ack that never released or pushed)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-971", phase="build:ack-needed", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    import ship as ship_mod
    rc, out = _run(ship_mod, ["KLC-971", "--pick", "1"])
    assert rc == 0, out
    remote = _remote_meta(klc, "KLC-971")
    assert remote["phase"] == "review:work", remote["phase"]
    assert remote.get("holder") is None, \
        f"ack.run must release the build holder, got {remote.get('holder')!r}"


def test_feature_off_ship_byte_identical(tmp_path, monkeypatch):
    """AC-5: feature OFF, ship advances the phase, exits 0, writes no holder and
    no git (byte parity — the old broken ship exited 1 on the double advance)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _plain_state_repo(tmp_path, "KLC-972", phase="build:ack-needed", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is False

    import ship as ship_mod
    rc, out = _run(ship_mod, ["KLC-972", "--pick", "1"])
    assert rc == 0, f"feature-off ship must succeed:\n{out}"
    local = _local_meta(klc, "KLC-972")
    assert local["phase"] == "review:work", local["phase"]
    assert local.get("holder") is None, "feature-off writes no holder"
    assert not (klc / ".git").exists(), "feature-off must not create a git repo"


# =========================================================================== #
# step-3 — klc abort wrapped in state_tx + release holder
# =========================================================================== #

def test_abort_cas_pushes_and_releases_holder(tmp_path, monkeypatch):
    """AC-3: feature-ON `klc abort` CAS-pushes the return to the previous `:ack`
    and releases the aborted phase's holder, in one push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-980", phase="build:work", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True

    import abort as abort_mod
    rc, out = _run(abort_mod, ["KLC-980"])
    assert rc == 0, f"feature-on abort must succeed:\n{out}"
    assert "ABORTED" in out, out

    remote = _remote_meta(klc, "KLC-980")
    assert remote["phase"] == "discovery-lite:ack", \
        f"abort must CAS-push the return to prev :ack, got {remote['phase']!r}"
    assert remote.get("holder") is None, \
        f"the aborted phase holder must be released, got {remote.get('holder')!r}"


def test_feature_off_abort_no_holder_or_git(tmp_path, monkeypatch):
    """AC-5: feature OFF, abort returns to prev :ack, writes no holder, no git."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _plain_state_repo(tmp_path, "KLC-981", phase="build:work", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is False

    import abort as abort_mod
    rc, out = _run(abort_mod, ["KLC-981"])
    assert rc == 0, f"feature-off abort must succeed:\n{out}"
    local = _local_meta(klc, "KLC-981")
    assert local["phase"] == "discovery-lite:ack", local["phase"]
    assert local.get("holder") is None, "feature-off writes no holder"
    assert not (klc / ".git").exists(), "feature-off must not create a git repo"


# =========================================================================== #
# step-4 — klc jump wrapped in state_tx + acquire holder (dry-run stays no-op)
# =========================================================================== #

def test_jump_cas_pushes_and_acquires_holder(tmp_path, monkeypatch):
    """AC-3: feature-ON `klc jump <phase> --yes` CAS-pushes the move to
    `<phase>:work` and acquires the target holder, in one push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-990", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True

    import jump as jump_mod
    rc, out = _run(jump_mod, ["review", "KLC-990", "--yes"])
    assert rc == 0, f"feature-on jump --yes must succeed:\n{out}"

    remote = _remote_meta(klc, "KLC-990")
    assert remote["phase"] == "review:work", \
        f"jump must CAS-push the move to target :work, got {remote['phase']!r}"
    assert remote.get("holder", {}).get("id") == ALICE, \
        f"the target holder must be acquired, got {remote.get('holder')!r}"


def test_jump_dryrun_is_documented_noop(tmp_path, monkeypatch):
    """AC-3: `klc jump` without --yes prints a plan and mutates NOTHING — no CAS
    push, origin and local state unchanged, no holder."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-991", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    import jump as jump_mod
    rc, out = _run(jump_mod, ["review", "KLC-991"])
    assert rc == 0, out
    assert "jump plan" in out.lower(), out
    remote = _remote_meta(klc, "KLC-991")
    assert remote["phase"] == "build:ack", "dry-run must not push a phase change"
    assert remote.get("holder") is None, "dry-run must not acquire a holder"
    local = _local_meta(klc, "KLC-991")
    assert local["phase"] == "build:ack", "dry-run must not mutate local state"


def test_feature_off_jump_no_holder_or_git(tmp_path, monkeypatch):
    """AC-5: feature OFF, jump --yes moves to target :work, no holder, no git."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _plain_state_repo(tmp_path, "KLC-992", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is False

    import jump as jump_mod
    rc, out = _run(jump_mod, ["review", "KLC-992", "--yes"])
    assert rc == 0, f"feature-off jump must succeed:\n{out}"
    local = _local_meta(klc, "KLC-992")
    assert local["phase"] == "review:work", local["phase"]
    assert local.get("holder") is None, "feature-off writes no holder"
    assert not (klc / ".git").exists(), "feature-off must not create a git repo"


# =========================================================================== #
# step-5 — klc jira reconcile pull/force-pull wrapped in state_tx
# =========================================================================== #

def _jira_cfg():
    from jira_config import JiraConfig
    return JiraConfig(
        enabled=True, mode="managed",
        base_url="https://jira.example.com", project_key="KLC",
        auth_env="JIRA_API_TOKEN", auth_user_env="",
        gitlab_base_url="https://gitlab.example.com/g/r", gitlab_branch="main",
        gitlab_blob_url_tmpl="{base_url}/-/blob/{branch}/{path}",
        klc_to_jira={"review": "In Review", "build": "In Progress",
                     "discovery-lite": "Discovery", "archived": "Done"},
        jira_to_klc={"In Review": ["review"], "In Progress": ["build"],
                     "Discovery": ["discovery-lite"], "Done": ["learn", "archived"]},
        artifact_paths={"spec": "spec.md"}, comment_links=True,
        managed_tickets=[],
    )


def test_jira_pull_wrapped_in_state_tx(tmp_path, monkeypatch):
    """AC-3/AC-4: feature-ON `klc jira reconcile force-pull` CAS-pushes the
    set_state phase move to origin (durable), with the Jira side deferred to
    after the push by the state_tx envelope."""
    from unittest.mock import patch
    from jira_client import FakeJiraClient
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-995", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    assert state_feature.enabled() is True

    cfg = _jira_cfg()
    client = FakeJiraClient(
        issues={"KLC-995": {"fields": {"status": {"name": "In Review"}}}})
    import jira as jira_mod
    with patch("jira_config.load", return_value=cfg), \
         patch("jira_client.make_client", return_value=client):
        rc = jira_mod._reconcile_pull("KLC-995", "review", force=True, reason="test")
    assert rc == 0, "feature-on jira force-pull must succeed"

    remote = _remote_meta(klc, "KLC-995")
    assert remote["phase"] == "review:work", \
        f"the jira-pull phase move must be CAS-pushed, got {remote['phase']!r}"


def test_jira_reconcile_push_is_documented_noop(tmp_path, monkeypatch):
    """AC-3: `klc jira reconcile push` writes only to the external Jira service —
    it must NOT CAS-push any klc phase change (origin phase unchanged)."""
    from unittest.mock import patch
    from jira_client import FakeJiraClient
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-996", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    cfg = _jira_cfg()
    client = FakeJiraClient(
        issues={"KLC-996": {"fields": {"status": {"name": "In Progress"}}}})
    import jira as jira_mod
    with patch("jira_config.load", return_value=cfg), \
         patch("jira_client.make_client", return_value=client):
        jira_mod._reconcile_push("KLC-996", cfg)

    remote = _remote_meta(klc, "KLC-996")
    assert remote["phase"] == "build:ack", \
        "reconcile push must not move the klc phase on origin"


# =========================================================================== #
# step-7 — review fixes: jira-pull lock + holder-auth; abort/jump Jira timing
# =========================================================================== #

def _order_spies(monkeypatch):
    """Patch the CAS push and the Jira flush to record call ORDER. Returns the
    shared order list; entries are 'push' then 'jira' on the success path."""
    import state_sync as _ss
    import lifecycle as _lc
    order: list[str] = []
    real_push = _ss.commit_and_push_cas_subtree
    real_flush = _lc.flush_jira_pushes

    def push_spy(*a, **k):
        order.append("push")
        return real_push(*a, **k)

    def flush_spy(*a, **k):
        order.append("jira")
        return real_flush(*a, **k)

    monkeypatch.setattr(_ss, "commit_and_push_cas_subtree", push_spy)
    monkeypatch.setattr(_lc, "flush_jira_pushes", flush_spy)
    return order


# --- FIX-1(a): jira-pull takes the per-ticket lock ------------------------- #

def test_jira_pull_takes_per_ticket_lock(tmp_path, monkeypatch):
    """FIX-1(a): jira-pull now does git work inside state_tx, so it must hold the
    per-ticket acquire_lock like abort/jump/steal/ack/next."""
    from unittest.mock import patch
    from jira_client import FakeJiraClient
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_state_repo(tmp_path, "KLC-997", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    import jira as jira_mod
    real_lock = jira_mod.acquire_lock  # AttributeError here == RED on unfixed code
    taken: list[str] = []

    def lock_spy(k):
        taken.append(k)
        return real_lock(k)

    monkeypatch.setattr(jira_mod, "acquire_lock", lock_spy)
    cfg = _jira_cfg()
    client = FakeJiraClient(
        issues={"KLC-997": {"fields": {"status": {"name": "In Review"}}}})
    with patch("jira_config.load", return_value=cfg), \
         patch("jira_client.make_client", return_value=client):
        rc = jira_mod._reconcile_pull("KLC-997", "review", force=True, reason="t")
    assert rc == 0, "force-pull must succeed"
    assert taken == ["KLC-997"], f"jira-pull must take the per-ticket lock, got {taken!r}"


# --- FIX-1(b): jira-pull must not move a ticket held by another user -------- #

def test_jira_pull_refuses_ticket_held_by_another_user(tmp_path, monkeypatch):
    """FIX-1(b): feature-ON, ticket in :work held by BOB, ALICE runs jira pull.
    It must NOT silently move B's held ticket on origin nor leave B attached to
    the new phase — it refuses (holder-auth), origin state unchanged."""
    from unittest.mock import patch
    from jira_client import FakeJiraClient
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-998", phase="build:work", track="S",
        holder={"id": BOB, "machine": "bobbox", "since": _now_z()})
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    cfg = _jira_cfg()
    client = FakeJiraClient(
        issues={"KLC-998": {"fields": {"status": {"name": "In Review"}}}})
    import jira as jira_mod
    with patch("jira_config.load", return_value=cfg), \
         patch("jira_client.make_client", return_value=client):
        rc = jira_mod._reconcile_pull("KLC-998", "review", force=True, reason="t")
    assert rc != 0, "jira pull must refuse to move a ticket held by another user"

    remote = _remote_meta(klc, "KLC-998")
    assert remote["phase"] == "build:work", \
        f"B's held ticket must NOT move on origin, got {remote['phase']!r}"
    assert remote.get("holder", {}).get("id") == BOB, \
        f"B's holder must be preserved (no ownership bypass), got {remote.get('holder')!r}"


def test_jira_pull_acquires_holder_for_caller(tmp_path, monkeypatch):
    """FIX-1(b) positive: an authorized jira pull (no competing holder) lands the
    caller as the holder of the new phase — no stale holder carried across."""
    from unittest.mock import patch
    from jira_client import FakeJiraClient
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-999", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    cfg = _jira_cfg()
    client = FakeJiraClient(
        issues={"KLC-999": {"fields": {"status": {"name": "In Review"}}}})
    import jira as jira_mod
    with patch("jira_config.load", return_value=cfg), \
         patch("jira_client.make_client", return_value=client):
        rc = jira_mod._reconcile_pull("KLC-999", "review", force=True, reason="t")
    assert rc == 0, "authorized jira pull must succeed"
    remote = _remote_meta(klc, "KLC-999")
    assert remote["phase"] == "review:work", remote["phase"]
    assert remote.get("holder", {}).get("id") == ALICE, \
        f"the caller must hold the new phase, got {remote.get('holder')!r}"


# --- FIX-3: abort/jump deferred-Jira TIMING -------------------------------- #

def test_abort_fires_jira_only_after_push(tmp_path, monkeypatch):
    """FIX-3(b): a successful abort flushes its deferred Jira push only AFTER the
    CAS push (order: push then jira)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_state_repo(
        tmp_path, "KLC-A01", phase="build:work", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    order = _order_spies(monkeypatch)

    import abort as abort_mod
    rc, out = _run(abort_mod, ["KLC-A01"])
    assert rc == 0, out
    assert order == ["push", "jira"], \
        f"Jira must fire only after the CAS push, got order={order!r}"


def test_abort_rolled_back_discards_jira(tmp_path, monkeypatch):
    """FIX-3(a): an abort whose CAS push is REJECTED discards its deferred Jira
    push (Jira never fires)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(
        tmp_path, "KLC-A02", phase="build:work", track="S",
        holder={"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    _reject_pushes(tmp_path)
    order = _order_spies(monkeypatch)

    import abort as abort_mod
    rc, out = _run(abort_mod, ["KLC-A02"])
    assert rc != 0, "abort must fail while the push is rejected"
    assert "jira" not in order, f"Jira must NOT fire on a rolled-back abort: {order!r}"
    assert _git(klc, "status", "--porcelain").strip() == "", "tree must be clean"


def test_jump_fires_jira_only_after_push(tmp_path, monkeypatch):
    """FIX-3(b): a successful jump flushes its deferred Jira push only AFTER the
    CAS push (order: push then jira)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _build_state_repo(tmp_path, "KLC-A03", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    order = _order_spies(monkeypatch)

    import jump as jump_mod
    rc, out = _run(jump_mod, ["review", "KLC-A03", "--yes"])
    assert rc == 0, out
    assert order == ["push", "jira"], \
        f"Jira must fire only after the CAS push, got order={order!r}"


def test_jump_rolled_back_discards_jira(tmp_path, monkeypatch):
    """FIX-3(a): a jump whose CAS push is REJECTED discards its deferred Jira
    push (Jira never fires)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-A04", phase="build:ack", track="S")
    monkeypatch.setattr(identity, "current", lambda: ALICE)
    _reject_pushes(tmp_path)
    order = _order_spies(monkeypatch)

    import jump as jump_mod
    rc, out = _run(jump_mod, ["review", "KLC-A04", "--yes"])
    assert rc != 0, "jump must fail while the push is rejected"
    assert "jira" not in order, f"Jira must NOT fire on a rolled-back jump: {order!r}"
    assert _git(klc, "status", "--porcelain").strip() == "", "tree must be clean"


# =========================================================================== #
# step-8 — same-user stale holder must be refreshed on jira-pull / jump
# =========================================================================== #

def test_jira_pull_refreshes_stale_same_user_holder(tmp_path, monkeypatch):
    """P2: ALICE already holds the ticket with a STALE holder and runs jira pull.
    acquire_holder is idempotent (keeps the old `since`), so without an explicit
    liveness refresh the just-pulled phase stays immediately stealable. After the
    fix, the holder's heartbeat is refreshed → a peer steal is refused."""
    from unittest.mock import patch
    from jira_client import FakeJiraClient
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-B01", phase="build:ack", track="S",
                            holder=_stale_holder(ALICE))
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    cfg = _jira_cfg()
    client = FakeJiraClient(
        issues={"KLC-B01": {"fields": {"status": {"name": "In Review"}}}})
    import jira as jira_mod
    with patch("jira_config.load", return_value=cfg), \
         patch("jira_client.make_client", return_value=client):
        rc = jira_mod._reconcile_pull("KLC-B01", "review", force=True, reason="t")
    assert rc == 0, "authorized same-user pull must succeed"

    # A peer must NOT be able to steal the just-pulled phase — the caller's holder
    # liveness was refreshed, so it is within TTL (fails RED: steal succeeds).
    bob_ident = {"id": BOB, "machine": "bobbox"}
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-B01", bob_ident,
                            ttl_seconds=holder.HOLDER_TTL_SECONDS)
    local = _local_meta(klc, "KLC-B01")
    assert local["holder"]["id"] == ALICE and local["holder"].get("heartbeat_at"), \
        "the same-user holder must carry a refreshed heartbeat_at"


def test_jump_refreshes_stale_same_user_holder(tmp_path, monkeypatch):
    """P2 (jump parity): ALICE holds a STALE holder and runs `klc jump --yes`.
    The same-user idempotent acquire must be followed by a liveness refresh so the
    just-jumped phase is not immediately stealable."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _build_state_repo(tmp_path, "KLC-B02", phase="build:ack", track="S",
                            holder=_stale_holder(ALICE))
    monkeypatch.setattr(identity, "current", lambda: ALICE)

    import jump as jump_mod
    rc, out = _run(jump_mod, ["review", "KLC-B02", "--yes"])
    assert rc == 0, f"same-user jump must succeed:\n{out}"

    bob_ident = {"id": BOB, "machine": "bobbox"}
    with pytest.raises(holder.HolderActiveError):
        holder.steal_holder("KLC-B02", bob_ident,
                            ttl_seconds=holder.HOLDER_TTL_SECONDS)
    local = _local_meta(klc, "KLC-B02")
    assert local["holder"]["id"] == ALICE and local["holder"].get("heartbeat_at"), \
        "the same-user holder must carry a refreshed heartbeat_at"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
