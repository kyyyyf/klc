"""KLC-057: wiring state_sync / identity / holder into intake / ack / next.

These integration tests drive the real verb `run()` entry points with
`state_sync` stubbed (a local no-network fixture, AC-10) and `state_feature`
forced on/off. The holder primitive is REAL — it mutates meta.json through
lifecycle.read_meta / write_meta.

step-4: intake uniqueness via CAS + holder acquire, index-append deferred.
step-5: intake happy path + holder-in-push + feature-off parity.
step-6: ack releases holder after advance, before push.
step-7: next first-grabs a free phase, refuses to steal a held phase.
step-8: output hygiene, feature-off holder, lock scope, regression.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import identity  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402


ALICE = "alice@example.com"


def _feature_on(monkeypatch, *, push=None):
    """Force the feature ON with state_sync stubbed. `push` (if given) replaces
    commit_and_push_cas_subtree; default is a no-op accept. The self-heal /
    ignore / pull entry points are stubbed to no-ops (no real git here)."""
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    monkeypatch.setattr(state_sync, "ensure_derived_ignored", lambda *a, **k: None)
    monkeypatch.setattr(state_sync, "pull_rebase_preserving", lambda *a, **k: None)
    # P1 stale-guard reads the ticket's committed tree hash; with no real git
    # here, return a constant so pre==post → the tree-hash guard is a no-op (the
    # phase-divergence guard is exercised separately).
    monkeypatch.setattr(state_sync, "ticket_tree_hash", lambda *a, **k: None)
    if push is None:
        push = lambda *a, **k: None  # noqa: E731
    monkeypatch.setattr(state_sync, "commit_and_push_cas_subtree", push)
    # Rollback's index reset must be a harmless no-op on the fake repo.
    monkeypatch.setattr(state_sync, "_git", lambda *a, **k: None)
    monkeypatch.setattr(identity, "current", lambda: ALICE)


def _feature_off(monkeypatch):
    monkeypatch.setattr(state_feature, "enabled", lambda: False)
    monkeypatch.setattr(identity, "current", lambda: ALICE)


def _meta_path(root: Path, ticket: str) -> Path:
    return root / ".klc" / "tickets" / ticket / "meta.json"


def _index_path(root: Path) -> Path:
    return root / ".klc" / "knowledge" / "tickets-index.jsonl"


# ---------------------------------------------------------------------------
# step-4: intake — taken key rejected, zero artifacts, no index pollution
# ---------------------------------------------------------------------------

def test_intake_taken_key_rejected_no_artifacts(tmp_path, monkeypatch, capsys):
    """Feature ON: a CAS push that rejects the key (StateConflictError) →
    intake exits non-zero naming the key as taken, and leaves NO meta.json,
    NO raw.md, NO ticket dir, and NO global-index entry."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    def _reject(*a, **k):
        raise state_sync.StateConflictError("key already taken by a peer")
    _feature_on(monkeypatch, push=_reject)

    import intake as intake_mod
    rc = intake_mod.run(["KLC-777", "a taken key"])
    assert rc != 0, "taken key must be rejected with a non-zero exit"

    err = capsys.readouterr().err.lower()
    assert "taken" in err and "klc-777" in err.lower(), f"unclear message: {err!r}"

    tdir = tmp_path / ".klc" / "tickets" / "KLC-777"
    assert not tdir.exists(), "no ticket dir may remain after a rejected push"
    idx = _index_path(tmp_path)
    if idx.exists():
        assert "KLC-777" not in idx.read_text(encoding="utf-8"), \
            "a rejected push must leave no global-index entry"


# ---------------------------------------------------------------------------
# step-5: intake happy path + holder-in-push + feature-off parity
# ---------------------------------------------------------------------------

def test_intake_happy_path_cas_push_succeeds(tmp_path, monkeypatch, capsys):
    """Feature ON, key free, push accepted → INTAKE_OK + exit 0, and the
    envelope ran (pull once, push once)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    pulls, pushes = [], []
    _feature_on(monkeypatch)
    monkeypatch.setattr(state_sync, "pull_rebase_preserving",
                        lambda *a, **k: pulls.append(1))
    monkeypatch.setattr(state_sync, "commit_and_push_cas_subtree",
                        lambda *a, **k: pushes.append(1))

    import intake as intake_mod
    rc = intake_mod.run(["KLC-501", "a free key"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "INTAKE_OK KLC-501" in out
    assert pulls == [1], "pull_rebase must run once on enter"
    assert pushes == [1], "the subtree CAS push must run once on clean exit"


def test_intake_acquires_holder_in_same_cas_push(tmp_path, monkeypatch):
    """AC-3: the holder is recorded in meta.json and is present at the moment
    of the CAS push (holder rides the SAME push as meta)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    seen = {}

    def _capture_push(ticket, msg, klc_dir, *a, **k):
        # Read meta.json bytes AT push time to prove holder rode this push.
        mp = _meta_path(tmp_path, ticket)
        seen["meta_at_push"] = json.loads(mp.read_text(encoding="utf-8"))

    _feature_on(monkeypatch, push=_capture_push)

    import intake as intake_mod
    rc = intake_mod.run(["KLC-502", "holder in push"])
    assert rc == 0

    meta = json.loads(_meta_path(tmp_path, "KLC-502").read_text(encoding="utf-8"))
    assert meta["holder"]["id"] == ALICE, "holder must be recorded on the first phase"
    assert meta["holder"]["machine"], "holder must carry a non-empty machine"

    assert seen["meta_at_push"]["holder"]["id"] == ALICE, \
        "holder field must be present in the meta pushed by the CAS push"


def test_feature_off_intake_behavior_identical(tmp_path, monkeypatch, capsys):
    """AC-8a: feature OFF → no holder field written, and INTAKE_OK still emitted
    (single-user behaviour unchanged)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    _feature_off(monkeypatch)

    import intake as intake_mod
    rc = intake_mod.run(["KLC-503", "single user"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "INTAKE_OK KLC-503" in out

    meta = json.loads(_meta_path(tmp_path, "KLC-503").read_text(encoding="utf-8"))
    assert "holder" not in meta, "feature-off intake must NOT write a holder field"


# ---------------------------------------------------------------------------
# step-6: ack — release holder after advance, before push
# ---------------------------------------------------------------------------

def _bootstrap_ticket(root: Path, ticket: str, *, phase: str, track: str,
                      holder=None) -> Path:
    td = root / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
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
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return td / "meta.json"


_HELD_BY_ALICE = {"id": ALICE, "machine": "box", "since": "2026-01-01T00:00:00Z"}


def test_ack_releases_holder_on_forward_transition(tmp_path, monkeypatch):
    """AC-4/AC-5: a forward ack advances the phase and clears meta.holder in the
    SAME (single) CAS push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap_ticket(tmp_path, "KLC-601", phase="build:ack-needed", track="S",
                      holder=dict(_HELD_BY_ALICE))

    seen = {}

    def _capture_push(ticket, msg, klc_dir, *a, **k):
        seen["meta_at_push"] = json.loads(
            _meta_path(tmp_path, ticket).read_text(encoding="utf-8"))
    _feature_on(monkeypatch, push=_capture_push)

    import ack as ack_mod
    rc = ack_mod.run(["KLC-601", "--pick", "1"])
    assert rc == 0, "forward ack must succeed"

    meta = json.loads(_meta_path(tmp_path, "KLC-601").read_text(encoding="utf-8"))
    assert meta.get("holder") is None, "holder must be released on forward ack"
    assert seen["meta_at_push"].get("holder") is None, \
        "the released (null) holder must ride the same CAS push"


def test_ack_cas_rejected_does_not_advance_remote_phase(tmp_path, monkeypatch, capsys):
    """A rejected CAS push → ack exits non-zero with a concurrent-update message
    and the in-tx holder release is rolled back (remote phase untouched)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap_ticket(tmp_path, "KLC-602", phase="build:ack-needed", track="S",
                      holder=dict(_HELD_BY_ALICE))

    def _reject(*a, **k):
        raise state_sync.StateConflictError("same-ticket race")
    _feature_on(monkeypatch, push=_reject)

    import ack as ack_mod
    rc = ack_mod.run(["KLC-602", "--pick", "1"])
    assert rc != 0, "a rejected push must fail the ack"
    err = capsys.readouterr().err.lower()
    assert "concurrent" in err or "retry" in err, f"unclear message: {err!r}"

    meta = json.loads(_meta_path(tmp_path, "KLC-602").read_text(encoding="utf-8"))
    assert meta.get("holder", {}).get("id") == ALICE, \
        "the holder release must be rolled back on a rejected push"
    # HIGH-1: the advance itself (now INSIDE the tx) must also roll back — the
    # local phase must not stay ahead of the untouched remote.
    assert meta["phase"] == "build:ack-needed", \
        "a rejected push must roll the phase back to its pre-ack value"


# ---------------------------------------------------------------------------
# step-7: next — first-grab a free phase, refuse to steal a held phase
# ---------------------------------------------------------------------------

def test_next_first_grabs_free_phase(tmp_path, monkeypatch):
    """AC-6a: entering a free phase first-grabs it — the current user becomes
    the holder and it rides the CAS push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap_ticket(tmp_path, "KLC-701", phase="build:ack", track="S")
    _feature_on(monkeypatch)

    import next as next_mod
    rc = next_mod.run(["KLC-701"])
    assert rc == 0, "next into a free phase must succeed"

    meta = json.loads(_meta_path(tmp_path, "KLC-701").read_text(encoding="utf-8"))
    assert meta["phase"].endswith(":work"), f"must advance to :work, got {meta['phase']}"
    assert meta["holder"]["id"] == ALICE, "current user must first-grab the entered phase"


def test_next_archive_syncs_and_releases_holder(tmp_path, monkeypatch):
    """MED-1: `next` that archives must still run the tx (pull/push) so the
    archived phase reaches the remote and the stale holder is released — with
    NO acquire (there is no phase to hold)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap_ticket(tmp_path, "KLC-710", phase="learn:ack", track="S",
                      holder=dict(_HELD_BY_ALICE))

    seen = {}

    def _capture_push(ticket, msg, klc_dir, *a, **k):
        seen["meta_at_push"] = json.loads(
            _meta_path(tmp_path, ticket).read_text(encoding="utf-8"))
    _feature_on(monkeypatch, push=_capture_push)

    import next as next_mod
    rc = next_mod.run(["KLC-710"])
    assert rc == 0, "next into archived must succeed"

    assert "meta_at_push" in seen, "archiving via next must still push the tx"
    assert seen["meta_at_push"]["phase"] == "archived", \
        "the archived phase must ride the CAS push"
    assert seen["meta_at_push"].get("holder") is None, \
        "the holder must be released (cleared) in the archive push"

    meta = json.loads(_meta_path(tmp_path, "KLC-710").read_text(encoding="utf-8"))
    assert meta["phase"] == "archived"
    assert meta.get("holder") is None, "no holder must remain after archive"


def test_next_refuses_to_steal_held_phase(tmp_path, monkeypatch, capsys):
    """AC-6b: a phase already held by ANOTHER user is reported as taken without
    stealing — next exits non-zero naming the holder, and the holder is unchanged
    (stealing is KLC-058, not next)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    other = {"id": "bob@example.com", "machine": "box2",
             "since": "2026-01-01T00:00:00Z"}
    _bootstrap_ticket(tmp_path, "KLC-702", phase="build:ack", track="S",
                      holder=dict(other))
    _feature_on(monkeypatch)

    import next as next_mod
    rc = next_mod.run(["KLC-702"])
    assert rc != 0, "next must refuse a phase held by another user"
    err = capsys.readouterr().err.lower()
    assert "held by" in err and "bob@example.com" in err, f"unclear message: {err!r}"

    meta = json.loads(_meta_path(tmp_path, "KLC-702").read_text(encoding="utf-8"))
    assert meta["holder"]["id"] == "bob@example.com", "the holder must be unchanged (no steal)"


# ---------------------------------------------------------------------------
# step-8: output hygiene, feature-off holder, lock scope
# ---------------------------------------------------------------------------

_FORBIDDEN = ("state-branch", "worktree", "push", "pull_rebase",
              "commit_and_push", "klc-state", "@{upstream}")


def _assert_no_git_internals(text: str) -> None:
    low = text.lower()
    for bad in _FORBIDDEN:
        assert bad not in low, f"success stdout leaked git internal {bad!r}: {text!r}"


def test_success_path_output_contains_no_git_internals(tmp_path, monkeypatch, capsys):
    """AC-7: intake/ack/next success stdout must not leak any sync internals."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    _feature_on(monkeypatch)

    import intake as intake_mod
    assert intake_mod.run(["KLC-801", "hygiene check"]) == 0
    _assert_no_git_internals(capsys.readouterr().out)

    _bootstrap_ticket(tmp_path, "KLC-802", phase="build:ack-needed", track="S",
                      holder=dict(_HELD_BY_ALICE))
    import ack as ack_mod
    assert ack_mod.run(["KLC-802", "--pick", "1"]) == 0
    _assert_no_git_internals(capsys.readouterr().out)

    _bootstrap_ticket(tmp_path, "KLC-803", phase="build:ack", track="S")
    import next as next_mod
    assert next_mod.run(["KLC-803"]) == 0
    _assert_no_git_internals(capsys.readouterr().out)


def test_feature_off_ack_next_no_holder_fields(tmp_path, monkeypatch):
    """AC-8b: with the feature OFF, ack and next write NO holder field."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _feature_off(monkeypatch)

    _bootstrap_ticket(tmp_path, "KLC-811", phase="build:ack-needed", track="S")
    import ack as ack_mod
    assert ack_mod.run(["KLC-811", "--pick", "1"]) == 0
    meta = json.loads(_meta_path(tmp_path, "KLC-811").read_text(encoding="utf-8"))
    assert "holder" not in meta, "feature-off ack must not write a holder field"

    _bootstrap_ticket(tmp_path, "KLC-812", phase="build:ack", track="S")
    import next as next_mod
    assert next_mod.run(["KLC-812"]) == 0
    meta = json.loads(_meta_path(tmp_path, "KLC-812").read_text(encoding="utf-8"))
    assert "holder" not in meta, "feature-off next must not write a holder field"


def test_sync_runs_inside_per_ticket_lock(tmp_path, monkeypatch):
    """AC-9: the CAS push happens INSIDE the per-ticket lock — the `.lock` file
    exists on disk at the moment commit_and_push_cas is invoked."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap_ticket(tmp_path, "KLC-821", phase="build:ack", track="S")

    import artefacts
    lock_seen = {}

    def _check_lock(*a, **k):
        lp = artefacts._lock_path("KLC-821")
        lock_seen["held"] = lp.exists()
    _feature_on(monkeypatch, push=_check_lock)

    import next as next_mod
    assert next_mod.run(["KLC-821"]) == 0
    assert lock_seen.get("held") is True, \
        "commit_and_push_cas must run inside the acquire_lock critical section"


def test_intake_sync_runs_inside_per_ticket_lock(tmp_path, monkeypatch):
    """MED-2 (AC-9): intake's CAS push must happen INSIDE the per-ticket lock —
    the `.lock` file exists on disk at the moment commit_and_push_cas runs."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    import artefacts
    lock_seen = {}

    def _check_lock(*a, **k):
        lp = artefacts._lock_path("KLC-841")
        lock_seen["held"] = lp.exists()
    _feature_on(monkeypatch, push=_check_lock)

    import intake as intake_mod
    assert intake_mod.run(["KLC-841", "lock scope"]) == 0
    assert lock_seen.get("held") is True, \
        "intake's commit_and_push_cas must run inside the acquire_lock section"


def test_terminal_runtime_error_surfaces_clean_message(tmp_path, monkeypatch, capsys):
    """HIGH-2: a plain RuntimeError (network/auth/protected-branch/
    non-classifiable rejection) from the sync must be caught by all three verbs
    → clean non-zero exit, NO git internals, and intake leaves no ticket dir."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    def _runtime(*a, **k):
        raise RuntimeError("fatal: remote rejected: pre-receive hook declined")
    _feature_on(monkeypatch, push=_runtime)

    import intake as intake_mod
    rc = intake_mod.run(["KLC-851", "runtime boom"])
    assert rc != 0, "intake must fail cleanly on a RuntimeError sync failure"
    _assert_no_git_internals(capsys.readouterr().err)
    assert not (tmp_path / ".klc" / "tickets" / "KLC-851").exists(), \
        "a RuntimeError sync failure must leave no half-created ticket"

    _bootstrap_ticket(tmp_path, "KLC-852", phase="build:ack-needed", track="S",
                      holder=dict(_HELD_BY_ALICE))
    import ack as ack_mod
    rc = ack_mod.run(["KLC-852", "--pick", "1"])
    assert rc != 0, "ack must fail cleanly on a RuntimeError sync failure"
    _assert_no_git_internals(capsys.readouterr().err)

    _bootstrap_ticket(tmp_path, "KLC-853", phase="build:ack", track="S")
    import next as next_mod
    rc = next_mod.run(["KLC-853"])
    assert rc != 0, "next must fail cleanly on a RuntimeError sync failure"
    _assert_no_git_internals(capsys.readouterr().err)


def test_terminal_sync_error_surfaces_clean_message(tmp_path, monkeypatch, capsys):
    """AC-7 (failure-path hygiene): a terminal non-CAS sync error (e.g.
    RetryExhaustedError) must be surfaced as a clean non-zero exit with NO git
    internals — never a raw traceback dumping git stderr to the user."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    def _exhausted(*a, **k):
        raise state_sync.RetryExhaustedError("push rejected after 3 retries")
    _feature_on(monkeypatch, push=_exhausted)

    # intake
    import intake as intake_mod
    rc = intake_mod.run(["KLC-831", "sync fails"])
    assert rc != 0, "intake must fail cleanly on a terminal sync error"
    _assert_no_git_internals(capsys.readouterr().err)
    assert not (tmp_path / ".klc" / "tickets" / "KLC-831").exists(), \
        "a terminal sync failure must leave no half-created ticket"

    # ack
    _bootstrap_ticket(tmp_path, "KLC-832", phase="build:ack-needed", track="S",
                      holder=dict(_HELD_BY_ALICE))
    import ack as ack_mod
    rc = ack_mod.run(["KLC-832", "--pick", "1"])
    assert rc != 0, "ack must fail cleanly on a terminal sync error"
    _assert_no_git_internals(capsys.readouterr().err)

    # next
    _bootstrap_ticket(tmp_path, "KLC-833", phase="build:ack", track="S")
    import next as next_mod
    rc = next_mod.run(["KLC-833"])
    assert rc != 0, "next must fail cleanly on a terminal sync error"
    _assert_no_git_internals(capsys.readouterr().err)


# ---------------------------------------------------------------------------
# round-2: conflict-path hardening (P1b stale pick, holder-conflict wording,
# identity disambiguation)
# ---------------------------------------------------------------------------

def test_ack_aborts_on_stale_phase_after_pull(tmp_path, monkeypatch, capsys):
    """P1b: if pull_rebase brings a remote phase that differs from the phase the
    pick was validated against, ack must REFUSE rather than apply a stale pick to
    the newly-pulled phase — and must not push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap_ticket(tmp_path, "KLC-611", phase="build:ack-needed", track="S",
                      holder=dict(_HELD_BY_ALICE))

    def _advance_remote(*a, **k):
        # Simulate the pull bringing a peer's advance: the phase moved on.
        mp = _meta_path(tmp_path, "KLC-611")
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["phase"] = "review:ack-needed"
        mp.write_text(json.dumps(m), encoding="utf-8")

    pushes = []
    _feature_on(monkeypatch, push=lambda *a, **k: pushes.append(1))
    monkeypatch.setattr(state_sync, "pull_rebase_preserving", _advance_remote)

    import ack as ack_mod
    rc = ack_mod.run(["KLC-611", "--pick", "1"])
    assert rc != 0, "a stale pick must not be applied"
    err = capsys.readouterr().err.lower()
    assert "advanced" in err or "re-run" in err, f"unclear message: {err!r}"
    assert pushes == [], "no push may happen when the state is stale"
    m = json.loads(_meta_path(tmp_path, "KLC-611").read_text(encoding="utf-8"))
    assert m["phase"] == "review:ack-needed", \
        "phase must be left at the pulled remote value, not a stale-applied advance"


def test_ack_reports_holder_conflict_distinctly(tmp_path, monkeypatch, capsys):
    """LOW-1: an ack whose holder-release hits a DIFFERENT holder must say
    'phase held by <id>', not the generic 'state sync failed'."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    other = {"id": "bob@example.com", "machine": "box2",
             "since": "2026-01-01T00:00:00Z"}
    _bootstrap_ticket(tmp_path, "KLC-612", phase="build:ack-needed", track="S",
                      holder=dict(other))
    _feature_on(monkeypatch)  # identity=alice, tries to release bob's hold

    import ack as ack_mod
    rc = ack_mod.run(["KLC-612", "--pick", "1"])
    assert rc != 0
    err = capsys.readouterr().err.lower()
    assert "held by" in err and "bob@example.com" in err, f"unclear: {err!r}"
    assert "state sync failed" not in err, "must not be masked as a sync error"


def test_next_archive_release_conflict_wording(tmp_path, monkeypatch, capsys):
    """LOW-2: when archiving via next, a holder-release conflict must be worded
    for a release/archive, not with the acquire ('phase held by') phrasing."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    other = {"id": "bob@example.com", "machine": "box2",
             "since": "2026-01-01T00:00:00Z"}
    _bootstrap_ticket(tmp_path, "KLC-711", phase="learn:ack", track="S",
                      holder=dict(other))
    _feature_on(monkeypatch)

    import next as next_mod
    rc = next_mod.run(["KLC-711"])
    assert rc != 0
    err = capsys.readouterr().err.lower()
    assert "archive" in err and "bob@example.com" in err, f"unclear: {err!r}"


def test_intake_bad_identity_message_distinct(tmp_path, monkeypatch, capsys):
    """LOW-3: a real identity error (empty identity.current()) must not be masked
    as 'state sync failed' — and must leave no half-created ticket."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")
    _feature_on(monkeypatch)
    monkeypatch.setattr(identity, "current", lambda: "")

    import intake as intake_mod
    rc = intake_mod.run(["KLC-861", "no identity"])
    assert rc != 0
    err = capsys.readouterr().err.lower()
    assert "identity" in err, f"unclear: {err!r}"
    assert "state sync failed" not in err, "identity error must not read as sync failure"
    assert not (tmp_path / ".klc" / "tickets" / "KLC-861").exists(), \
        "a bad-identity failure must leave no half-created ticket"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
