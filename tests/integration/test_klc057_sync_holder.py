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
    commit_and_push_cas; default is a no-op accept."""
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    monkeypatch.setattr(state_sync, "pull_rebase", lambda *a, **k: None)
    if push is None:
        push = lambda *a, **k: None  # noqa: E731
    monkeypatch.setattr(state_sync, "commit_and_push_cas", push)
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
