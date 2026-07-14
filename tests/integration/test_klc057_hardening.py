"""KLC-057 design-hardening — feature-ON verbs against a REAL klc-state worktree.

Every prior finding, plus the new invariants of the self-healing envelope, driven
end-to-end against a real ``.klc/`` worktree bound to a LOCAL bare-repo upstream
(no network, AC-10) with NOTHING stubbed except ``identity.current``. Each test
fails on the pre-hardening code and passes after.

Covered: self-heal of a pre-dirtied tree; the ticket-subtree glob-commit (an
"unlisted" file the body writes is still pushed — supersede moves); the derived
index/prompt cards are git-ignored (no dirty-tree deadlock); ack manual-
completion WORK→ack-needed runs inside a tx; ack/next post-pull stale-guards;
intake --force peer-newer refusal; jira raw.md merge folded into the tx; and a
"10 mixed ops never wedge the tree" soak.
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


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


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


def _init_repo(tmp_path: Path, tickets: dict | None = None) -> Path:
    """Create a `.klc/` klc-state worktree bound to a bare upstream, seeded with
    the given `{ticket: meta_dict}` tickets. Feature detection reads ON after."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)
    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    (klc / ".seed").write_text("seed\n", encoding="utf-8")
    for ticket, meta in (tickets or {}).items():
        td = klc / "tickets" / ticket
        td.mkdir(parents=True)
        (td / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                      encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "origin", str(bare))
    _git(klc, "push", "-u", "origin", "klc-state")
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    return klc


def _commit_file(klc: Path, rel: str, content: str) -> None:
    """Add one extra tracked file under the worktree and push it to the bare."""
    fp = klc / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", f"add {rel}")
    _git(klc, "push", "origin", "klc-state")


def _clone_peer(tmp_path: Path, name: str, email: str) -> Path:
    peer = tmp_path / name
    _git(tmp_path, "clone", str(tmp_path / "remote.git"), str(peer))
    _git(peer, "config", "user.email", email)
    _git(peer, "config", "user.name", email.split("@")[0])
    _git(peer, "config", "commit.gpgsign", "false")
    return peer


def _remote_meta(klc: Path, ticket: str) -> dict:
    _git(klc, "fetch", "origin")
    return json.loads(_git(klc, "show", f"origin/klc-state:tickets/{ticket}/meta.json"))


def _remote_has(klc: Path, path: str) -> bool:
    _git(klc, "fetch", "origin")
    r = subprocess.run(
        ["git", "cat-file", "-e", f"origin/klc-state:{path}"],
        cwd=str(klc), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(klc)},
    )
    return r.returncode == 0


def _status(klc: Path) -> str:
    return _git(klc, "status", "--porcelain").strip()


@pytest.fixture(autouse=True)
def _alice(monkeypatch):
    monkeypatch.setattr(identity, "current", lambda: ALICE)


# --------------------------------------------------------------------------- #
# step-1: self-heal + subtree commit
# --------------------------------------------------------------------------- #

def test_self_heal_recovers_a_pre_dirtied_tracked_tree(tmp_path, monkeypatch):
    """A stray, never-pushed tracked modification present on enter must be
    self-healed away so the op still succeeds (no pull deadlock)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-3001": _meta("KLC-3001", phase="build:ack-needed", track="S",
                       holder={"id": ALICE, "machine": "box",
                               "since": "2026-01-01T00:00:00Z"}),
    })
    assert state_feature.enabled() is True

    # Dirty an UNRELATED tracked file (crash/leftover artifact).
    (klc / ".seed").write_text("DIRTY-UNPUSHED\n", encoding="utf-8")

    import ack as ack_mod
    rc = ack_mod.run(["KLC-3001", "--pick", "1"])
    assert rc == 0, "self-heal must let the op proceed past a dirty tree"
    assert _remote_meta(klc, "KLC-3001")["phase"] != "build:ack-needed"
    assert _status(klc) == "", "tree must be clean after a healed op"
    assert (klc / ".seed").read_text(encoding="utf-8") == "seed\n", \
        "the stray unpushed edit must be discarded (remote is truth)"


def test_supersede_moves_are_captured_by_the_subtree_commit(tmp_path, monkeypatch):
    """A pick that supersedes moves artefacts into ``_superseded/`` — files no
    caller lists. The subtree glob-commit must push the moves (new location in,
    old location out) without wedging the tree."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-3002": _meta("KLC-3002", phase="review-lite:ack-needed", track="XS",
                         holder={"id": ALICE, "machine": "box",
                                 "since": "2026-01-01T00:00:00Z"}),
    })
    _commit_file(klc, "tickets/KLC-3002/review-lite-report.md", "old report\n")
    assert state_feature.enabled() is True

    import ack as ack_mod
    rc = ack_mod.run(["KLC-3002", "--pick", "2"])  # request-changes → supersede
    assert rc == 0, "supersede ack must succeed"

    assert _remote_meta(klc, "KLC-3002")["phase"] == "xs-build:work"
    assert not _remote_has(klc, "tickets/KLC-3002/review-lite-report.md"), \
        "the moved-away original must be removed from the pushed tree"
    _git(klc, "fetch", "origin")
    listing = _git(klc, "ls-tree", "-r", "--name-only", "origin/klc-state")
    assert "_superseded/" in listing and "review-lite-report.md" in listing, \
        "the superseded copy must be pushed under _superseded/"
    assert _status(klc) == "", "tree must be clean after a supersede ack"


# --------------------------------------------------------------------------- #
# step-2: derived index / prompt cards are git-ignored
# --------------------------------------------------------------------------- #

def test_intake_index_and_prompt_cards_are_ignored(tmp_path, monkeypatch):
    """The derived index (and prompt cards) must be git-ignored so intake never
    leaves the tree dirty — and the index still reflects the new ticket."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path)
    assert state_feature.enabled() is True

    import intake as intake_mod
    assert intake_mod.run(["KLC-3003", "index ignored"]) == 0
    assert _status(klc) == "", "intake must leave a clean tree (index ignored)"

    idx = klc / "knowledge" / "tickets-index.jsonl"
    assert idx.exists() and "KLC-3003" in idx.read_text(encoding="utf-8"), \
        "the derived index must still reflect the ticket locally"
    assert not _remote_has(klc, "knowledge/tickets-index.jsonl"), \
        "the derived index must never be pushed to the shared state"


def test_intake_then_ack_does_not_wedge(tmp_path, monkeypatch):
    """HIGH (index): feature-on intake THEN ack must both succeed — the classic
    dirty-tree deadlock must be gone."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path)
    assert state_feature.enabled() is True

    import intake as intake_mod
    import ack as ack_mod
    assert intake_mod.run(["KLC-3004", "wedge check"]) == 0
    assert ack_mod.run(["KLC-3004", "--pick", "1"]) == 0, \
        "the op after intake must not deadlock on a dirty tree"
    assert _status(klc) == ""


# --------------------------------------------------------------------------- #
# step-3: intake --force peer-newer
# --------------------------------------------------------------------------- #

def test_force_overwrite_refused_when_peer_advanced(tmp_path, monkeypatch):
    """P2: --force may only overwrite the exact local record it targets; if a
    peer advanced the shared state, --force must refuse (no clobber)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path, {
        "KLC-3005": _meta("KLC-3005", phase="intake:ack-needed", track="S"),
    })

    # A peer advances KLC-3005 and pushes; our local copy stays behind.
    peer = _clone_peer(tmp_path, "peer", "bob@example.com")
    pm = peer / "tickets" / "KLC-3005" / "meta.json"
    d = json.loads(pm.read_text(encoding="utf-8"))
    d["phase"] = "build:work"
    d["owner"] = "bob@example.com"
    pm.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    _git(peer, "commit", "-am", "peer advances KLC-3005")
    _git(peer, "push", "origin", "klc-state")

    assert state_feature.enabled() is True
    import intake as intake_mod
    rc = intake_mod.run(["KLC-3005", "--force", "re-intake"])
    assert rc != 0, "--force must refuse to clobber a peer-advanced ticket"

    meta = json.loads(
        (klc / "tickets" / "KLC-3005" / "meta.json").read_text(encoding="utf-8"))
    assert meta["phase"] == "build:work", "the peer's advance must be preserved"
    assert _status(klc) == "", "tree must be clean after the refusal"


# --------------------------------------------------------------------------- #
# step-4: ack manual-completion inside a tx + stale-guard
# --------------------------------------------------------------------------- #

def test_ack_manual_completion_from_work_pushes_cleanly(tmp_path, monkeypatch):
    """The WORK→ack-needed manual-completion advance runs inside its own tx, so
    ack-from-:work pushes cleanly instead of dirtying the tree and deadlocking
    the recursion's pull."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-3006": _meta("KLC-3006", phase="build:work", track="S",
                        holder={"id": ALICE, "machine": "box",
                                "since": "2026-01-01T00:00:00Z"}),
    })
    import phase_completion
    monkeypatch.setattr(phase_completion, "can_complete", lambda t, p: (True, ""))
    assert state_feature.enabled() is True

    import ack as ack_mod
    rc = ack_mod.run(["KLC-3006", "--pick", "1"])
    assert rc == 0, "ack from :work with detected completion must succeed"
    remote = _remote_meta(klc, "KLC-3006")
    assert remote["phase"] == "review:work", \
        f"must advance past build to review:work, got {remote['phase']}"
    assert _status(klc) == "", "tree must be clean after a manual-completion ack"


def test_ack_stale_abort_real(tmp_path, monkeypatch):
    """ack refuses a pick validated against a phase the pull has since moved."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-3007": _meta("KLC-3007", phase="build:ack-needed", track="S",
                        holder={"id": ALICE, "machine": "box",
                                "since": "2026-01-01T00:00:00Z"}),
    })
    # A peer advances the ticket past build:ack-needed and pushes.
    peer = _clone_peer(tmp_path, "peer", "bob@example.com")
    pm = peer / "tickets" / "KLC-3007" / "meta.json"
    d = json.loads(pm.read_text(encoding="utf-8"))
    d["phase"] = "review:work"
    d["holder"] = {"id": "bob@example.com", "machine": "b",
                   "since": "2026-01-02T00:00:00Z"}
    pm.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    _git(peer, "commit", "-am", "peer advances KLC-3007")
    _git(peer, "push", "origin", "klc-state")

    assert state_feature.enabled() is True
    import ack as ack_mod
    rc = ack_mod.run(["KLC-3007", "--pick", "1"])
    assert rc != 0, "a stale ack must be refused"
    assert _remote_meta(klc, "KLC-3007")["phase"] == "review:work", \
        "the peer's advance must be untouched"
    assert _status(klc) == ""


# --------------------------------------------------------------------------- #
# step-5: next post-pull stale-guard
# --------------------------------------------------------------------------- #

def test_next_stale_abort_real(tmp_path, monkeypatch, capsys):
    """next refuses to advance from a phase the pull has since moved."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-3008": _meta("KLC-3008", phase="build:ack", track="S"),
    })
    peer = _clone_peer(tmp_path, "peer", "bob@example.com")
    pm = peer / "tickets" / "KLC-3008" / "meta.json"
    d = json.loads(pm.read_text(encoding="utf-8"))
    d["phase"] = "review:work"  # peer already advanced
    pm.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    _git(peer, "commit", "-am", "peer advances KLC-3008")
    _git(peer, "push", "origin", "klc-state")

    assert state_feature.enabled() is True
    import next as next_mod
    rc = next_mod.run(["KLC-3008"])
    assert rc != 0, "a stale next must be refused"
    err = capsys.readouterr().err.lower()
    assert "advanced" in err or "re-run" in err, f"unclear message: {err!r}"
    assert _remote_meta(klc, "KLC-3008")["phase"] == "review:work"
    assert _status(klc) == ""


# --------------------------------------------------------------------------- #
# step-6: jira raw.md merge folded into the tx
# --------------------------------------------------------------------------- #

def test_jira_raw_merge_rides_the_tx(tmp_path, monkeypatch):
    """A jira enrichment that rewrites raw.md must ride the ticket push (not
    dirty the tree post-push), and a following ack must still succeed."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path)

    import intake as intake_mod

    def _fake_enrich(ticket, mode):
        raw = klc / "tickets" / ticket / "raw.md"
        raw.write_text(raw.read_text(encoding="utf-8") + "\n<!-- jira-merged -->\n",
                       encoding="utf-8")
    monkeypatch.setattr(intake_mod, "_jira_intake_enrich", _fake_enrich)

    assert state_feature.enabled() is True
    assert intake_mod.run(["KLC-3009", "jira merge"]) == 0
    assert _status(klc) == "", "the jira merge must not dirty the tree post-push"
    _git(klc, "fetch", "origin")
    pushed = _git(klc, "show", "origin/klc-state:tickets/KLC-3009/raw.md")
    assert "jira-merged" in pushed, "the jira merge must ride the ticket push"

    import ack as ack_mod
    assert ack_mod.run(["KLC-3009", "--pick", "1"]) == 0, \
        "the op after a jira-merged intake must not deadlock"


# --------------------------------------------------------------------------- #
# step-7: soak — many mixed feature-on ops never wedge the tree
# --------------------------------------------------------------------------- #

def test_soak_ten_mixed_ops_never_wedge_the_tree(tmp_path, monkeypatch):
    """Drive 10 mixed feature-on ops (intake/ack/next across tickets) and assert
    the tracked tree is clean after every single one."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    held = {"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"}
    tickets = {}
    for i in (1, 2, 3):
        tickets[f"KLC-310{i}"] = _meta(f"KLC-310{i}", phase="build:ack", track="S")
        tickets[f"KLC-311{i}"] = _meta(f"KLC-311{i}", phase="build:ack-needed",
                                     track="S", holder=dict(held))
    klc = _init_repo(tmp_path, tickets)
    assert state_feature.enabled() is True

    import intake as intake_mod
    import ack as ack_mod
    import next as next_mod

    ops = [
        lambda: intake_mod.run(["KLC-3121", "op"]),
        lambda: next_mod.run(["KLC-3101"]),
        lambda: ack_mod.run(["KLC-3111", "--pick", "1"]),
        lambda: intake_mod.run(["KLC-3122", "op"]),
        lambda: next_mod.run(["KLC-3102"]),
        lambda: ack_mod.run(["KLC-3112", "--pick", "1"]),
        lambda: intake_mod.run(["KLC-3123", "op"]),
        lambda: next_mod.run(["KLC-3103"]),
        lambda: ack_mod.run(["KLC-3113", "--pick", "1"]),
        lambda: intake_mod.run(["KLC-3124", "op"]),
    ]
    for i, op in enumerate(ops, 1):
        rc = op()
        assert rc == 0, f"soak op #{i} failed (rc={rc})"
        assert _status(klc) == "", f"tree wedged after soak op #{i}: {_status(klc)!r}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
