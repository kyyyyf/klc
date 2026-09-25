"""tests/integration/test_klc110_meta_tx_seam.py — KLC-110 step-2: a staged
meta patch rides the SAME meta write `lifecycle.set_state` performs, so a
per-ticket metric is atomic with the phase transition (AC-8, seam half).

`phase_completion.can_complete` runs BEFORE `state_tx` is entered
(`core/phases/ack.py:93` vs `:112`), so a producer that wrote meta.json
directly would leave its record behind on a rolled-back or stale-aborted
ack. `lifecycle.stage_meta_patch` stages the mutation instead, and
`set_state` merges + consumes it inside its own write."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle as _lc  # noqa: E402


def _write_meta(tickets_dir: Path, ticket: str, meta: dict) -> Path:
    d = tickets_dir / ticket
    d.mkdir(parents=True, exist_ok=True)
    p = d / "meta.json"
    p.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def test_staged_patch_lands_in_same_meta_write_as_the_transition(tmp_path, monkeypatch):
    """AC-8 (seam): a patch staged before `set_state` is written into the
    SAME meta.json the transition writes, merged one level deep so an
    existing `metrics` key keeps its other entries."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tickets_dir = tmp_path / ".klc" / "tickets"
    meta_path = _write_meta(tickets_dir, "KLC-A", {
        "phase": "integrate:work", "track": "M",
        "metrics": {"other": 1},
    })

    _lc.stage_meta_patch("KLC-A", {"metrics": {"retrieval": {"status": "ok"}}})
    _lc.set_state("KLC-A", "integrate", "ack-needed")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["metrics"]["retrieval"] == {"status": "ok"}
    assert meta["metrics"]["other"] == 1  # existing sibling key preserved
    assert meta["phase"] == "integrate:ack-needed"


def test_transition_with_no_staged_patch_writes_byte_identical_metrics(tmp_path, monkeypatch):
    """A transition with nothing staged applies no metrics mutation at all —
    `_apply_meta_patch` is a true no-op when `_meta_patches` holds nothing
    for this ticket."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tickets_dir = tmp_path / ".klc" / "tickets"
    meta_path = _write_meta(tickets_dir, "KLC-B", {
        "phase": "integrate:work", "track": "M",
        "metrics": {"other": 1},
    })

    _lc.set_state("KLC-B", "integrate", "ack-needed")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["metrics"] == {"other": 1}
    assert meta["phase"] == "integrate:ack-needed"


def test_patch_staged_for_an_ack_that_never_transitions_is_dropped_and_never_leaks(
    tmp_path, monkeypatch
):
    """A patch staged for a ticket whose ack never calls `set_state` is
    simply dropped: it never applies to a DIFFERENT ticket's transition in
    the same process, and it never appears on the never-transitioned
    ticket's own meta.json."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tickets_dir = tmp_path / ".klc" / "tickets"
    meta_path_a = _write_meta(tickets_dir, "KLC-C", {
        "phase": "integrate:work", "track": "M", "metrics": {},
    })
    meta_path_b = _write_meta(tickets_dir, "KLC-D", {
        "phase": "integrate:work", "track": "M", "metrics": {},
    })

    _lc.stage_meta_patch("KLC-C", {"metrics": {"retrieval": {"status": "ok"}}})
    # KLC-C's ack never calls set_state (rolled back / refused). Only KLC-D transitions.
    _lc.set_state("KLC-D", "integrate", "ack-needed")

    meta_b = json.loads(meta_path_b.read_text(encoding="utf-8"))
    assert "retrieval" not in meta_b["metrics"]

    meta_a = json.loads(meta_path_a.read_text(encoding="utf-8"))
    assert "retrieval" not in meta_a["metrics"]  # never transitioned, meta untouched

    # Draining leftover process-global state so it cannot leak into another test.
    _lc._apply_meta_patch("KLC-C", {})
