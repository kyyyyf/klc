"""tests/integration/test_klc110_r1_meta_patch_discard.py — KLC-110 review
round 1, step-9a (MEDIUM, AC-8): `lifecycle._meta_patches` is a
process-global dict, only ever CONSUMED by a successful `set_state`. If the
ack's own `state_tx` aborts AFTER `can_complete(persist=True)` staged a
patch (a holder conflict, a stale-state abort, a rejected CAS push, ...),
nothing else pops it, and it would wrongly ride the NEXT successful
transition of the SAME ticket in the SAME process (an autorunner looping
`ack.run`)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"),
          str(_FW_ROOT / "core" / "phases")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle as _lc  # noqa: E402


def test_discard_meta_patch_removes_a_staged_patch():
    """AC-8: `discard_meta_patch` drops a staged patch WITHOUT applying it —
    the ticket carries nothing staged afterwards."""
    _lc.stage_meta_patch("KLC-DISC1", {"metrics": {"retrieval": {"status": "ok"}}})
    assert "KLC-DISC1" in _lc._meta_patches
    _lc.discard_meta_patch("KLC-DISC1")
    assert "KLC-DISC1" not in _lc._meta_patches


def test_discard_meta_patch_on_an_unstaged_ticket_is_a_noop():
    """A discard for a ticket with nothing staged never raises."""
    assert "KLC-NEVER-STAGED" not in _lc._meta_patches
    _lc.discard_meta_patch("KLC-NEVER-STAGED")  # must not raise
    assert "KLC-NEVER-STAGED" not in _lc._meta_patches


def _seed_ticket(tmp_path: Path, ticket: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "discovery:work",
        "phase_history": [], "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 1, "total": 5},
        "layer": "code", "affected_modules": ["core/skills"],
        "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def test_ack_discards_a_staged_patch_when_the_transition_aborts(tmp_path, monkeypatch):
    """AC-8: the ack transition (`core/phases/ack.py`, feature-off / single
    -user, no git machinery) is wrapped in try/finally so an abort AFTER
    `can_complete(persist=True)` staged a patch still discards it — the
    patch must not linger to wrongly ride a LATER transition of the same
    ticket in the same process (an autorunner looping `ack.run`).

    Feature-off's `state_tx` yields `tx=None`, so the holder-conflict branch
    (guarded by `if tx is not None`) never fires here — the realistic
    feature-off abort is `set_state` itself raising, caught by the generic
    `RuntimeError` arm the real CAS-push-failure/state-sync-failure class
    already shares (`core/phases/ack.py`'s own
    `except (..., RuntimeError):` clause)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-DISC2"
    _seed_ticket(tmp_path, ticket)

    import ack as ack_mod

    def _staging_can_complete(t, pid, persist=True):
        _lc.stage_meta_patch(t, {"metrics": {"retrieval": {"status": "ok"}}})
        return True, "advisory"

    monkeypatch.setattr(ack_mod.phase_completion, "can_complete", _staging_can_complete)

    def _raising_set_state(*a, **kw):
        raise RuntimeError("simulated state-sync failure after staging")

    monkeypatch.setattr(ack_mod._lc, "set_state", _raising_set_state)

    assert ticket not in _lc._meta_patches
    rc = ack_mod.run([ticket])
    assert rc == 1  # the RuntimeError arm caught it, transition aborted
    assert ticket not in _lc._meta_patches, (
        "a staged patch survived an aborted ack transition — it would leak "
        "into this ticket's NEXT successful transition")

    # The abort never reached a real set_state, so meta.json is untouched.
    meta = json.loads((tmp_path / ".klc" / "tickets" / ticket / "meta.json").read_text())
    assert "metrics" not in meta
