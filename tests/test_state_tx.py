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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
