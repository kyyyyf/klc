"""KLC-057 step-2/step-3: state_tx — the shared pull/push transaction envelope.

step-2 pins the AC-8 no-op: feature OFF → pure pass-through (no pull, no push,
no holder writes). step-3 adds the feature-ON envelope: pull on enter, CAS push
on clean exit, and a single rollback of the touched paths on a same-ticket
StateConflictError.

All tests run against local git repos / stubbed state_sync (no network, AC-10).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402


# ---------------------------------------------------------------------------
# step-2: no-op path when feature off
# ---------------------------------------------------------------------------

def test_noop_when_feature_off(monkeypatch):
    """Feature OFF → the body runs but neither pull_rebase nor
    commit_and_push_cas is ever called, and the handle is None."""
    monkeypatch.setattr(state_feature, "enabled", lambda: False)

    calls = []
    monkeypatch.setattr(state_sync, "pull_rebase",
                        lambda *a, **k: calls.append("pull"))
    monkeypatch.setattr(state_sync, "commit_and_push_cas",
                        lambda *a, **k: calls.append("push"))

    ran = []
    with state_tx.state_tx("KLC-T1", ["tickets/KLC-T1/meta.json"], "msg") as tx:
        ran.append(True)
        assert tx is None

    assert ran == [True], "body must run on the no-op path"
    assert calls == [], f"no git calls expected when feature off, got {calls}"


# ---------------------------------------------------------------------------
# step-3: feature-on envelope — pull on enter, CAS push on exit, rollback
# ---------------------------------------------------------------------------

def _klc(tmp_path: Path) -> Path:
    kd = tmp_path / ".klc"
    (kd / "tickets").mkdir(parents=True, exist_ok=True)
    return kd


def test_happy_push_commits_touched_paths(tmp_path, monkeypatch):
    """Feature ON, clean exit → pull_rebase on enter and commit_and_push_cas
    with exactly the touched paths + msg + ticket + klc_dir; the handle is
    truthy and the file the body wrote survives (no rollback)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    kd = _klc(tmp_path)
    monkeypatch.setattr(state_feature, "enabled", lambda: True)

    pulls = []
    monkeypatch.setattr(state_sync, "pull_rebase", lambda *a, **k: pulls.append(a))
    pushes = []
    monkeypatch.setattr(state_sync, "commit_and_push_cas",
                        lambda paths, msg, ticket, klc_dir, **k:
                        pushes.append((list(paths), msg, ticket, Path(klc_dir))))

    rel = "tickets/KLC-T1/meta.json"
    (kd / "tickets" / "KLC-T1").mkdir(parents=True)
    with state_tx.state_tx("KLC-T1", [rel], "intake KLC-T1") as tx:
        assert tx is not None, "feature-on must yield a truthy handle"
        (kd / rel).write_text('{"holder": {"id": "alice"}}', encoding="utf-8")

    assert len(pulls) == 1, "pull_rebase must run exactly once on enter"
    assert len(pushes) == 1, "commit_and_push_cas must run once on clean exit"
    paths, msg, ticket, klc_arg = pushes[0]
    assert paths == [rel] and msg == "intake KLC-T1" and ticket == "KLC-T1"
    assert klc_arg == kd
    assert (kd / rel).exists(), "written file must survive a clean push"


def test_cas_conflict_rolls_back_local_state(tmp_path, monkeypatch):
    """Feature ON, commit_and_push_cas raises StateConflictError → a file the
    body CREATED is removed and a file it MODIFIED is restored to prior bytes,
    then StateConflictError propagates."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    kd = _klc(tmp_path)
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    monkeypatch.setattr(state_sync, "pull_rebase", lambda *a, **k: None)

    def _boom(*a, **k):
        raise state_sync.StateConflictError("same-ticket race")
    monkeypatch.setattr(state_sync, "commit_and_push_cas", _boom)

    td = kd / "tickets" / "KLC-T2"
    td.mkdir(parents=True)
    existing = td / "raw.md"
    existing.write_text("ORIGINAL", encoding="utf-8")
    created_rel = "tickets/KLC-T2/meta.json"
    modified_rel = "tickets/KLC-T2/raw.md"

    with pytest.raises(state_sync.StateConflictError):
        with state_tx.state_tx("KLC-T2", [created_rel, modified_rel], "intake KLC-T2"):
            (kd / created_rel).write_text("NEW", encoding="utf-8")
            (kd / modified_rel).write_text("CHANGED", encoding="utf-8")

    assert not (kd / created_rel).exists(), "created file must be rolled back (deleted)"
    assert existing.read_text(encoding="utf-8") == "ORIGINAL", \
        "modified file must be restored to prior bytes"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
