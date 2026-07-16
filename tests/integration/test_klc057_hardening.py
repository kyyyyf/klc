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

def test_pre_dirtied_tracked_tree_does_not_wedge_and_is_preserved(tmp_path, monkeypatch):
    """A pre-dirtied tracked file present on enter must NOT block the op (the
    preserving stash-around-pull lets the rebase run) AND must be preserved —
    never discarded (that was the P1 data-loss bug)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-3001": _meta("KLC-3001", phase="build:ack-needed", track="S",
                       holder={"id": ALICE, "machine": "box",
                               "since": "2026-01-01T00:00:00Z"}),
    })
    assert state_feature.enabled() is True

    # An unrelated tracked file with an uncommitted (unpushed) edit.
    (klc / ".seed").write_text("DIRTY-UNPUSHED\n", encoding="utf-8")

    import ack as ack_mod
    rc = ack_mod.run(["KLC-3001", "--pick", "1"])
    assert rc == 0, "a dirty tree must not wedge the op"
    assert _remote_meta(klc, "KLC-3001")["phase"] != "build:ack-needed"
    assert (klc / ".seed").read_text(encoding="utf-8") == "DIRTY-UNPUSHED\n", \
        "the uncommitted edit must be PRESERVED, never discarded"


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


# --------------------------------------------------------------------------- #
# harden2 — P1: preserve (never discard) uncommitted tracked artifacts
# --------------------------------------------------------------------------- #

def test_uncommitted_tracked_artifact_is_preserved_and_pushed(tmp_path, monkeypatch):
    """P1 (data-loss): an in-progress TRACKED artifact edit that is uncommitted
    on enter must be PRESERVED across the pull and PUSHED by the subtree commit —
    never silently reverted to HEAD by a destructive self-heal."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4001": _meta("KLC-4001", phase="build:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    # An artefact committed in a prior phase, then EDITED (uncommitted) during
    # this phase — the classic in-progress work product.
    _commit_file(klc, "tickets/KLC-4001/design.md", "v1 committed\n")
    (klc / "tickets" / "KLC-4001" / "design.md").write_text(
        "v2 in-progress EDIT\n", encoding="utf-8")
    assert state_feature.enabled() is True

    import ack as ack_mod
    rc = ack_mod.run(["KLC-4001", "--pick", "1"])
    assert rc == 0, "ack must succeed"

    _git(klc, "fetch", "origin")
    pushed = _git(klc, "show", "origin/klc-state:tickets/KLC-4001/design.md")
    assert pushed == "v2 in-progress EDIT\n", \
        "the uncommitted artifact edit must be preserved AND pushed, not reverted"
    assert _remote_meta(klc, "KLC-4001")["phase"] != "build:ack-needed", \
        "the advance must ride the same push"
    assert _status(klc) == ""


def test_other_ticket_dirty_edit_is_not_destroyed(tmp_path, monkeypatch):
    """P1: an op on one ticket must NOT destroy another ticket's uncommitted
    tracked edits (the old blanket `git checkout -- .` wiped everything)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4002": _meta("KLC-4002", phase="build:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
        "KLC-4003": _meta("KLC-4003", phase="design:work", track="M"),
    })
    _commit_file(klc, "tickets/KLC-4003/notes.md", "committed notes\n")
    # KLC-4003 has an uncommitted in-progress edit while we operate on KLC-4002.
    (klc / "tickets" / "KLC-4003" / "notes.md").write_text(
        "UNSAVED work on the other ticket\n", encoding="utf-8")
    assert state_feature.enabled() is True

    import ack as ack_mod
    assert ack_mod.run(["KLC-4002", "--pick", "1"]) == 0

    assert (klc / "tickets" / "KLC-4003" / "notes.md").read_text(encoding="utf-8") \
        == "UNSAVED work on the other ticket\n", \
        "another ticket's uncommitted edit must survive this ticket's op"
    # It is (correctly) NOT pushed by KLC-4002's ticket-scoped commit.
    assert not _remote_has(klc, "tickets/KLC-4003/notes.md") or \
        _git(klc, "show", "origin/klc-state:tickets/KLC-4003/notes.md") \
        == "committed notes\n", "the other ticket's edit must not ride this push"


# --------------------------------------------------------------------------- #
# harden2 — MEDIUM: scope-conflict annotation is stderr-only when feature ON
# --------------------------------------------------------------------------- #

def test_scope_conflict_feature_on_is_stderr_only(tmp_path, monkeypatch, capsys):
    """MEDIUM: feature-ON, a scope-expansion abort must NOT write the persistent
    [!CONFLICT] note into the tracked review-report.md (a pre-decision abort has
    no tx to push it and it would dirty the tree). The stderr message still
    reaches the user; the tree stays clean."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4004": _meta("KLC-4004", phase="review:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    _commit_file(klc, "tickets/KLC-4004/review-report.md", "# review\nok\n")
    assert state_feature.enabled() is True

    import ack as ack_mod
    monkeypatch.setattr(ack_mod._sd, "compare", lambda ticket: {
        "expansion": ["mod-x"], "planned": ["mod-a"],
        "actual": ["mod-a", "mod-x"], "unknown_files": [], "drift": [],
        "skipped": "",
    })
    rc = ack_mod.run(["KLC-4004", "--pick", "1"])
    assert rc != 0, "scope expansion must abort the ack"
    err = capsys.readouterr().err.lower()
    assert "scope expansion" in err, f"stderr message missing: {err!r}"
    assert "[!conflict]" not in \
        (klc / "tickets" / "KLC-4004" / "review-report.md").read_text(encoding="utf-8").lower(), \
        "feature-on must NOT persist the conflict note into the tracked report"
    assert _status(klc) == "", "the aborted scope check must leave a clean tree"


# --------------------------------------------------------------------------- #
# harden2 — LOW: scratch/ is never swept into the shared push
# --------------------------------------------------------------------------- #

def test_scratch_dir_is_not_pushed(tmp_path, monkeypatch):
    """LOW: per-session local agent memory under tickets/<KEY>/scratch/ must be
    git-ignored so the subtree glob-commit never sweeps it into shared state."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4005": _meta("KLC-4005", phase="build:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    scratch = klc / "tickets" / "KLC-4005" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "note.md").write_text("local agent memory\n", encoding="utf-8")
    assert state_feature.enabled() is True

    import ack as ack_mod
    assert ack_mod.run(["KLC-4005", "--pick", "1"]) == 0
    assert not _remote_has(klc, "tickets/KLC-4005/scratch/note.md"), \
        "scratch/ must never be pushed to the shared state"
    assert _status(klc) == "", "scratch/ must be ignored (clean tree)"


# --------------------------------------------------------------------------- #
# harden3 — P2: a failed --force must NOT delete the restored pre-existing ticket
# --------------------------------------------------------------------------- #

def test_failed_force_intake_preserves_existing_ticket(tmp_path, monkeypatch):
    """P2 (data-loss): `intake K --force` on an EXISTING K that hits a terminal
    push failure must leave the state_tx-restored original ticket in place — the
    unconditional rmtree(tdir) must not delete a pre-existing ticket."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path, {
        "KLC-4101": _meta("KLC-4101", phase="intake:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    _commit_file(klc, "tickets/KLC-4101/raw.md", "ORIGINAL raw body\n")

    # A pre-receive hook rejects the push → terminal (non-CAS) failure AFTER the
    # body wrote the new content and state_tx restored the original on rollback.
    bare = tmp_path / "remote.git"
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    assert state_feature.enabled() is True

    import intake as intake_mod
    rc = intake_mod.run(["KLC-4101", "--force", "brand new description"])
    assert rc != 0, "the rejected push must fail the --force intake"

    raw = klc / "tickets" / "KLC-4101" / "raw.md"
    assert raw.exists(), "a failed --force must NOT delete the pre-existing ticket"
    assert raw.read_text(encoding="utf-8") == "ORIGINAL raw body\n", \
        "the original must be restored (not the half-written --force content)"
    assert (klc / "tickets" / "KLC-4101" / "meta.json").exists()
    assert _status(klc) == "", "the failed --force must leave a clean tree"


# --------------------------------------------------------------------------- #
# harden3 — P1: ack post-pull stale-guard covers ANY same-ticket change
# --------------------------------------------------------------------------- #

def test_ack_aborts_on_same_phase_pulled_change(tmp_path, monkeypatch, capsys):
    """P1: scope/gate/pick are validated pre-pull; if the pull brings ANY change
    to this ticket's committed state (even same-phase), ack must abort rather
    than apply the stale-validated pick."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4102": _meta("KLC-4102", phase="build:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    # A peer pushes a SAME-PHASE same-ticket change (a new committed artefact;
    # meta.json / phase untouched), so the phase-only guard would miss it.
    peer = _clone_peer(tmp_path, "peer", "bob@example.com")
    (peer / "tickets" / "KLC-4102" / "reviewer-note.md").write_text(
        "peer added this same-phase\n", encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer same-phase change to KLC-4102")
    _git(peer, "push", "origin", "klc-state")
    assert state_feature.enabled() is True

    import ack as ack_mod
    rc = ack_mod.run(["KLC-4102", "--pick", "1"])
    assert rc != 0, "a same-phase pulled change must abort the stale-validated ack"
    err = capsys.readouterr().err.lower()
    assert "advanced" in err or "re-run" in err, f"unclear message: {err!r}"
    assert _remote_meta(klc, "KLC-4102")["phase"] == "build:ack-needed", \
        "the pick must NOT be applied against pulled-changed state"
    assert _status(klc) == ""


# --------------------------------------------------------------------------- #
# harden4 — the stale-guard is CLASS-CLOSED in the state_tx envelope
# --------------------------------------------------------------------------- #

def test_force_intake_aborts_when_peer_changed_only_raw(tmp_path, monkeypatch):
    """P2a (envelope): `intake --force` where a peer changed ONLY raw.md
    (meta.json unchanged) must abort — the subtree-hash guard sees the raw change
    that a meta-only compare would miss; the peer's raw is preserved, no push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path, {
        "KLC-4201": _meta("KLC-4201", phase="intake:ack-needed", track="S"),
    })
    _commit_file(klc, "tickets/KLC-4201/raw.md", "original raw\n")

    # A peer changes ONLY raw.md (meta.json untouched) and pushes.
    peer = _clone_peer(tmp_path, "peer", "bob@example.com")
    (peer / "tickets" / "KLC-4201" / "raw.md").write_text(
        "PEER edited raw only\n", encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer edits only raw.md")
    _git(peer, "push", "origin", "klc-state")
    assert state_feature.enabled() is True

    import intake as intake_mod
    rc = intake_mod.run(["KLC-4201", "--force", "clobber attempt"])
    assert rc != 0, "a --force over a peer-changed (raw-only) ticket must abort"

    raw = klc / "tickets" / "KLC-4201" / "raw.md"
    assert raw.read_text(encoding="utf-8") == "PEER edited raw only\n", \
        "the peer's raw.md must be preserved (not clobbered by --force)"
    assert _remote_meta(klc, "KLC-4201")["phase"] == "intake:ack-needed"
    assert _status(klc) == ""


def test_manual_completion_aborts_on_same_phase_pulled_change(tmp_path, monkeypatch):
    """P2b (envelope): ack from :work (manual-completion) where a peer pushed a
    same-phase artifact change must abort — the WORK→ack-needed set_state must
    NOT run against pulled-changed state (previously it rechecked only phase)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4202": _meta("KLC-4202", phase="build:work", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    import phase_completion
    monkeypatch.setattr(phase_completion, "can_complete", lambda t, p: (True, ""))

    # A peer pushes a SAME-PHASE artefact change (phase stays build:work).
    peer = _clone_peer(tmp_path, "peer", "bob@example.com")
    (peer / "tickets" / "KLC-4202" / "build-log.md").write_text(
        "peer build note\n", encoding="utf-8")
    _git(peer, "add", "-A")
    _git(peer, "commit", "-m", "peer same-phase artefact on KLC-4202")
    _git(peer, "push", "origin", "klc-state")
    assert state_feature.enabled() is True

    import ack as ack_mod
    rc = ack_mod.run(["KLC-4202", "--pick", "1"])
    assert rc != 0, "manual-completion must abort on a same-phase pulled change"
    assert _remote_meta(klc, "KLC-4202")["phase"] == "build:work", \
        "the WORK→ack-needed set_state must NOT have advanced the phase"
    assert _status(klc) == ""


# --------------------------------------------------------------------------- #
# harden5 — P1 holder-auth on manual-completion; P2 upgrade untrack
# --------------------------------------------------------------------------- #

def test_manual_completion_refuses_when_peer_holds_phase(tmp_path, monkeypatch, capsys):
    """P1 (holder-auth): ack manual-completion must NOT push WORK→ack-needed for a
    phase held by ANOTHER user — the transition must be refused before any push,
    leaving the remote phase unchanged."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4301": _meta("KLC-4301", phase="build:work", track="S",
                          holder={"id": "bob@example.com", "machine": "b",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    import phase_completion
    monkeypatch.setattr(phase_completion, "can_complete", lambda t, p: (True, ""))
    assert state_feature.enabled() is True

    import ack as ack_mod  # current identity is ALICE; bob holds the phase
    rc = ack_mod.run(["KLC-4301", "--pick", "1"])
    assert rc != 0, "must not advance a phase held by another user"
    err = capsys.readouterr().err.lower()
    assert "held by" in err and "bob@example.com" in err, f"unclear: {err!r}"
    assert _remote_meta(klc, "KLC-4301")["phase"] == "build:work", \
        "no WORK→ack-needed may be pushed for another user's held phase"
    assert _status(klc) == ""


def test_upgraded_worktree_untracks_tracked_derived_index(tmp_path, monkeypatch):
    """P2 (upgrade): a derived cache TRACKED by an older layout must be untracked
    (kept on disk) by a feature-on op, so it stops dirtying the tree — and the
    tree is clean afterward."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-4302": _meta("KLC-4302", phase="build:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    # OLD layout: the derived index is committed/tracked.
    _commit_file(klc, "knowledge/tickets-index.jsonl", '{"key":"KLC-4302"}\n')
    assert _git(klc, "ls-files", "knowledge/tickets-index.jsonl").strip() != ""
    assert state_feature.enabled() is True

    import ack as ack_mod
    assert ack_mod.run(["KLC-4302", "--pick", "1"]) == 0

    assert _git(klc, "ls-files", "knowledge/tickets-index.jsonl").strip() == "", \
        "the tracked derived index must be untracked after a feature-on op"
    assert (klc / "knowledge" / "tickets-index.jsonl").exists(), \
        "the derived cache must be KEPT on disk (local-only), not deleted"
    assert _status(klc) == "", "the tree must be clean after convergence"
    assert not _remote_has(klc, "knowledge/tickets-index.jsonl"), \
        "the derived index must no longer be on the shared state"


# --------------------------------------------------------------------------- #
# harden6 — intake --force holder authorization
# --------------------------------------------------------------------------- #

def test_force_refused_over_peer_held_ticket(tmp_path, monkeypatch, capsys):
    """harden6 (INV4): `intake --force` on an EXISTING ticket held by ANOTHER
    user must be REFUSED (no overwrite, no push, no holder steal) — taking over
    goes through `klc steal`, never a silent --force."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path, {
        "KLC-4401": _meta("KLC-4401", phase="build:ack", track="S",
                          holder={"id": "bob@example.com", "machine": "b",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    assert state_feature.enabled() is True

    import intake as intake_mod  # current identity is ALICE; bob holds KLC-4401
    rc = intake_mod.run(["KLC-4401", "--force", "alice tries to steal"])
    assert rc != 0, "--force over a peer-held ticket must be refused"
    err = capsys.readouterr().err.lower()
    assert "held by" in err and "bob@example.com" in err, f"unclear: {err!r}"
    assert "steal" in err, "message should point at `klc steal`"

    remote = _remote_meta(klc, "KLC-4401")
    assert remote["phase"] == "build:ack", "peer's phase must be untouched"
    assert remote["holder"]["id"] == "bob@example.com", \
        "peer's holder must NOT be transferred to the forcing user"
    assert _status(klc) == "", "the refused --force must leave a clean tree"


def test_force_allowed_over_self_held_ticket(tmp_path, monkeypatch):
    """harden6: `intake --force` on a ticket the CURRENT user holds is still
    allowed (the legit re-intake case) — holder-auth only blocks PEER-held."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    klc = _init_repo(tmp_path, {
        "KLC-4402": _meta("KLC-4402", phase="intake:ack-needed", track="S",
                          holder={"id": ALICE, "machine": "box",
                                  "since": "2026-01-01T00:00:00Z"}),
    })
    assert state_feature.enabled() is True

    import intake as intake_mod  # ALICE holds KLC-4402
    rc = intake_mod.run(["KLC-4402", "--force", "alice re-intakes her own"])
    assert rc == 0, "--force over a self-held ticket must be allowed"
    remote = _remote_meta(klc, "KLC-4402")
    assert remote["phase"] == "intake:ack-needed"
    assert remote["holder"]["id"] == ALICE, "self re-intake keeps the current user as holder"
    assert _status(klc) == ""


# --------------------------------------------------------------------------- #
# KLC-063: tx rollback must leave a CLEAN index (tree AND index) even on an
# upgraded worktree that still tracks the shared derived index.
# --------------------------------------------------------------------------- #

def _reject_pushes(tmp_path: Path) -> None:
    """Install a pre-receive hook on the bare upstream that rejects every push,
    forcing the in-tx CAS push to fail for real (no stub)."""
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def _run_failing_tx(klc: Path, ticket: str) -> None:
    """Drive one state_tx whose body mutates the ticket subtree and whose CAS
    push is forced to fail, so the rollback path runs against real git."""
    import state_tx  # noqa: E402
    with pytest.raises(Exception):
        with state_tx.state_tx(ticket, f"{ticket} build: advance") as tx:
            assert tx is not None, "feature must be ON for this test"
            meta_fp = klc / "tickets" / ticket / "meta.json"
            d = json.loads(meta_fp.read_text(encoding="utf-8"))
            d["phase"] = "build:ack"
            meta_fp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")


def test_upgraded_worktree_rollback_leaves_clean_index(tmp_path, monkeypatch):
    """AC-3 / AC-6b: on an UPGRADED worktree that still TRACKS the shared derived
    index, a failed CAS push must leave a CLEAN index after rollback — no staged
    `rm --cached` of knowledge/tickets-index.jsonl left behind. Fails on the
    pre-fix subtree-scoped rollback reset (state_tx.py:135)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-6301": _meta("KLC-6301", phase="build:ack-needed", track="S"),
    })
    # Upgraded layout: an older KLC committed the derived cross-ticket index.
    _commit_file(klc, "knowledge/tickets-index.jsonl", '{"ticket":"KLC-6301"}\n')
    assert state_feature.enabled() is True
    assert _git(klc, "ls-files", "knowledge/tickets-index.jsonl").strip() == \
        "knowledge/tickets-index.jsonl", "derived index must be TRACKED (upgraded case)"

    _reject_pushes(tmp_path)
    _run_failing_tx(klc, "KLC-6301")

    porcelain = _git(klc, "status", "--porcelain")
    assert "knowledge/tickets-index.jsonl" not in porcelain, \
        f"derived-index untracking left staged after rollback: {porcelain!r}"
    assert _git(klc, "diff", "--cached", "--name-only").strip() == "", \
        f"index not clean after rollback: {porcelain!r}"
    assert (klc / "knowledge" / "tickets-index.jsonl").exists(), \
        "the on-disk derived index file must be untouched by the rollback"


def test_orphan_worktree_rollback_still_clean_index(tmp_path, monkeypatch):
    """AC-4: on a KLC-053-created orphan (derived index NEVER tracked) a failed
    CAS push still rolls back to a clean tree AND index — the fix is a no-op here.
    Also proves an unscoped index reset does NOT destroy another ticket's
    uncommitted working-tree edit (C-003)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-6302": _meta("KLC-6302", phase="build:ack-needed", track="S"),
        "KLC-6303": _meta("KLC-6303", phase="design:work", track="M"),
    })
    assert state_feature.enabled() is True
    # No knowledge/tickets-index.jsonl is tracked (orphan happy path).
    assert _git(klc, "ls-files", "knowledge/tickets-index.jsonl").strip() == ""

    # An uncommitted tracked edit to ANOTHER ticket must survive the rollback.
    other = klc / "tickets" / "KLC-6303" / "meta.json"
    d = json.loads(other.read_text(encoding="utf-8"))
    d["note"] = "in-progress work on another ticket"
    other.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")

    _reject_pushes(tmp_path)
    _run_failing_tx(klc, "KLC-6302")

    assert _git(klc, "diff", "--cached", "--name-only").strip() == "", \
        "index must be clean after rollback on the orphan path"
    survived = json.loads(other.read_text(encoding="utf-8"))
    assert survived.get("note") == "in-progress work on another ticket", \
        "another ticket's uncommitted working-tree edit must survive the rollback"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
