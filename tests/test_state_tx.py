"""KLC-057 — state_tx: the self-contained, self-healing sync envelope.

Feature OFF → pure pass-through (no git at all). Feature ON → self-heal on enter,
pull, snapshot the ticket subtree, run the body, glob-commit the subtree +
CAS-push on clean exit, and roll the subtree back (tree AND index) on any
terminal failure.

These are unit tests with a fake ``.klc`` and stubbed ``state_sync`` (no network,
AC-10); the real git behaviour is exercised by the real-bare-repo integration
tests (tests/integration/test_klc057_*.py).
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


def _klc(tmp_path: Path) -> Path:
    kd = tmp_path / ".klc"
    (kd / "tickets").mkdir(parents=True, exist_ok=True)
    return kd


def _stub_sync(monkeypatch, *, push=None):
    """Stub every git-touching state_sync entry point and record calls."""
    calls: list[str] = []
    # The envelope's stale-guard reads the subtree hash before/after the pull.
    # Return None (fresh-ticket case) so the guard is skipped and these tests
    # exercise the push/rollback path; the real hash behaviour is covered by the
    # bare-repo hardening tests.
    monkeypatch.setattr(state_sync, "ticket_tree_hash", lambda *a, **k: None)
    monkeypatch.setattr(state_sync, "ensure_derived_ignored",
                        lambda *a, **k: calls.append("ignore"))
    monkeypatch.setattr(state_sync, "pull_rebase_preserving",
                        lambda *a, **k: calls.append("pull"))
    if push is None:
        push = lambda *a, **k: calls.append("push")  # noqa: E731
    monkeypatch.setattr(state_sync, "commit_and_push_cas_subtree", push)
    # Keep the rollback's index reset a harmless no-op on the fake repo.
    monkeypatch.setattr(state_sync, "_git", lambda *a, **k: None)
    return calls


# ---------------------------------------------------------------------------
# feature OFF: pure pass-through, no git
# ---------------------------------------------------------------------------

def test_noop_when_feature_off(monkeypatch):
    monkeypatch.setattr(state_feature, "enabled", lambda: False)
    calls = _stub_sync(monkeypatch)

    ran = []
    with state_tx.state_tx("KLC-T1", "msg") as tx:
        ran.append(True)
        assert tx is None

    assert ran == [True], "body must run on the no-op path"
    assert calls == [], f"no git calls expected when feature off, got {calls}"


# ---------------------------------------------------------------------------
# feature ON: self-heal → pull → body → subtree commit
# ---------------------------------------------------------------------------

def test_signature_is_ticket_msg_only():
    import inspect
    params = list(inspect.signature(state_tx.state_tx).parameters)
    assert params == ["ticket", "msg"], f"unexpected signature: {params}"


def test_happy_path_self_heals_pulls_and_pushes_subtree(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    kd = _klc(tmp_path)
    monkeypatch.setattr(state_feature, "enabled", lambda: True)

    pushes = []
    calls = _stub_sync(
        monkeypatch,
        push=lambda ticket, msg, klc_dir, **k:
        pushes.append((ticket, msg, Path(klc_dir))),
    )

    (kd / "tickets" / "KLC-T1").mkdir(parents=True)
    with state_tx.state_tx("KLC-T1", "intake KLC-T1") as tx:
        assert tx is not None, "feature-on must yield a truthy handle"
        # A file the body writes under the subtree — no explicit path list.
        (kd / "tickets" / "KLC-T1" / "meta.json").write_text(
            '{"holder": {"id": "alice"}}', encoding="utf-8")

    assert calls[:2] == ["ignore", "pull"], \
        f"enter order must be ignore → preserving-pull, got {calls}"
    assert len(pushes) == 1, "subtree push must run once on clean exit"
    ticket, msg, klc_arg = pushes[0]
    assert ticket == "KLC-T1" and msg == "intake KLC-T1" and klc_arg == kd
    assert (kd / "tickets" / "KLC-T1" / "meta.json").exists(), \
        "written file must survive a clean push"


def test_cas_conflict_rolls_back_whole_subtree(tmp_path, monkeypatch):
    """A file the body CREATED (even one no caller listed) is removed and a
    MODIFIED file is restored, on a StateConflictError from the push."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    kd = _klc(tmp_path)
    monkeypatch.setattr(state_feature, "enabled", lambda: True)

    def _boom(*a, **k):
        raise state_sync.StateConflictError("same-ticket race")
    _stub_sync(monkeypatch, push=_boom)

    td = kd / "tickets" / "KLC-T2"
    td.mkdir(parents=True)
    (td / "raw.md").write_text("ORIGINAL", encoding="utf-8")

    with pytest.raises(state_sync.StateConflictError):
        with state_tx.state_tx("KLC-T2", "intake KLC-T2"):
            (td / "meta.json").write_text("NEW", encoding="utf-8")   # created
            (td / "raw.md").write_text("CHANGED", encoding="utf-8")   # modified
            # An UNLISTED nested file the body creates must also roll back.
            (td / "_superseded").mkdir()
            (td / "_superseded" / "x.md").write_text("MOVED", encoding="utf-8")

    assert not (td / "meta.json").exists(), "created file must be rolled back"
    assert not (td / "_superseded" / "x.md").exists(), \
        "an unlisted nested created file must also roll back"
    assert (td / "raw.md").read_text(encoding="utf-8") == "ORIGINAL", \
        "modified file must be restored to prior bytes"


def test_rolls_back_on_any_terminal_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    kd = _klc(tmp_path)
    monkeypatch.setattr(state_feature, "enabled", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("network is down")
    _stub_sync(monkeypatch, push=_boom)

    td = kd / "tickets" / "KLC-T3"
    td.mkdir(parents=True)
    (td / "meta.json").write_text("ORIGINAL", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with state_tx.state_tx("KLC-T3", "msg"):
            (td / "raw.md").write_text("NEW", encoding="utf-8")
            (td / "meta.json").write_text("CHANGED", encoding="utf-8")

    assert not (td / "raw.md").exists(), "created file must be rolled back"
    assert (td / "meta.json").read_text(encoding="utf-8") == "ORIGINAL", \
        "modified file must be restored on a non-CAS terminal error too"


def test_git_helpers_do_not_raise_when_git_binary_absent(tmp_path, monkeypatch):
    """`_git` (and thus `ticket_tree_hash`) must honour its "never raises"
    contract when the git binary is missing — a FileNotFoundError from
    subprocess is turned into a non-zero result, and ticket_tree_hash returns
    None."""
    import subprocess as _sp

    def _no_git(*a, **k):
        raise FileNotFoundError("git: command not found")
    monkeypatch.setattr(_sp, "run", _no_git)

    cp = state_sync._git(["rev-parse", "HEAD"], tmp_path)
    assert cp.returncode != 0, "a missing git binary must yield a non-zero result"
    assert state_sync.ticket_tree_hash(tmp_path, "KLC-1") is None, \
        "ticket_tree_hash must return None (not raise) when git is absent"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
