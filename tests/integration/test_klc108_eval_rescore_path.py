"""KLC-108 — AC-14: `planning-eval` scores a trace regenerated from the
ticket's own description against the CURRENT index, so a BEFORE run and an
AFTER run cover the same corpus instead of comparing stored traces built
from different index vintages.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-eval.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_eval_rescore", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_index(idx: Path, *, keyword_for_intake: str = "ticket") -> None:
    idx.mkdir(parents=True, exist_ok=True)
    modules = {"modules": [
        {"name": "intake", "path": "core/intake/", "keywords": [keyword_for_intake]},
    ]}
    file_roles = {"files": {
        "core/intake/validation.py": {
            "module_name": "intake", "roles": ["domain_logic"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": [keyword_for_intake, "validate"],
            "symbols": ["validate_ticket"], "confidence": "high",
        },
    }}
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")
    (idx / "file_roles.json").write_text(json.dumps(file_roles), encoding="utf-8")
    (idx / "module_edges.json").write_text(json.dumps({"edges": []}), encoding="utf-8")
    (idx / "test_map.json").write_text(json.dumps({}), encoding="utf-8")
    (idx / "inventory.json").write_text(json.dumps({"symbols": []}), encoding="utf-8")


def test_eval_regenerates_trace_from_ticket_description_against_current_index(tmp_path):
    """AC-14: planning-eval scores a trace regenerated from the ticket's own
    description against the current index, not the stored trace on disk."""
    ticket_dir = tmp_path / "KLC-999"
    ticket_dir.mkdir()
    # A deliberately STALE stored trace (an older index vintage's answer).
    (ticket_dir / "retrieval_trace.json").write_text(json.dumps({
        "status": "ok", "query": "add a ticket validation rule",
        "files_to_read_first": ["stale/from/old/index.py"],
        "files_likely_to_edit": ["stale/from/old/index.py"],
        "confidence": "low",
    }), encoding="utf-8")
    idx = tmp_path / "index"
    _write_index(idx)

    mod = _load_skill()
    trace = mod.rescore_trace(ticket_dir, idx)
    assert trace is not None
    assert "core/intake/validation.py" in trace["files_to_read_first"]
    assert "stale/from/old/index.py" not in trace["files_to_read_first"]


def test_before_and_after_runs_share_the_same_corpus_selection(tmp_path):
    """AC-14: a BEFORE run and an AFTER run via --rescore select the
    identical ticket set, so the two numbers are comparable."""
    tickets_root = tmp_path / "tickets"
    for key, has_query in (("KLC-A", True), ("KLC-B", True), ("KLC-C", False)):
        d = tickets_root / key
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"ticket": key, "affected_modules": ["intake"]}))
        if has_query:
            (d / "retrieval_trace.json").write_text(json.dumps({"query": "ticket validation"}))
    idx_before = tmp_path / "before"
    _write_index(idx_before, keyword_for_intake="ticket")
    idx_after = tmp_path / "after"
    _write_index(idx_after, keyword_for_intake="validation")

    mod = _load_skill()
    before_keys = {k for k in ("KLC-A", "KLC-B", "KLC-C")
                  if mod.rescore_trace(tickets_root / k, idx_before) is not None}
    after_keys = {k for k in ("KLC-A", "KLC-B", "KLC-C")
                 if mod.rescore_trace(tickets_root / k, idx_after) is not None}
    assert before_keys == after_keys == {"KLC-A", "KLC-B"}


def test_rescore_fails_closed_when_ticket_description_unavailable(tmp_path):
    """AC-14: the re-score path fails closed (reports None, not a
    fabricated/empty-query score) when no ticket description is available."""
    ticket_dir = tmp_path / "KLC-NONE"
    ticket_dir.mkdir()
    idx = tmp_path / "index"
    _write_index(idx)
    mod = _load_skill()
    assert mod.rescore_trace(ticket_dir, idx) is None
