"""KLC-108 — e2e probe traces: the three probe tickets the spec measured
(KLC-100, KLC-101, KLC-102), replayed with their own recorded query against
CURRENT (post-KLC-108) planning views.

Hermetic (KLC-136 AC-2): the `modules.json`/`file_roles.json`/
`module_edges.json`/`test_map.json`/`inventory.json`/`token_idf.json` views
come from the `fresh_index` fixture (built from the current tree), never
from `.klc/index/`, so the verdict is identical whether the live index is
absent, stale or current. The `tickets/KLC-100..102` reads (the recorded
query per ticket) stay against the live `.klc/tickets` — group (c), out of
scope (spec.md Q-003).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TICKETS = REPO_ROOT / ".klc" / "tickets"
_SKILL = REPO_ROOT / "core" / "skills" / "planning-retriever.py"

_INDEX_FILES = ("modules.json", "file_roles.json", "module_edges.json",
               "test_map.json", "inventory.json", "token_idf.json")


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_retriever_probe", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _views(index_dir: Path) -> dict:
    """AC-2: every index view this file needs, loaded from `fresh_index`'s
    directory rather than `.klc/index/` — `token_idf.json` is optional (the
    live reader tolerated its absence; the fresh one is built by
    `file_roles.py --out-idf`, so it is normally present, but this keeps the
    same degrade)."""
    out = {}
    for name in _INDEX_FILES:
        p = index_dir / name
        if p.exists():
            out[name] = _load_json(p)
    return out


def _ticket_query(key: str) -> str:
    trace_path = TICKETS / key / "retrieval_trace.json"
    if trace_path.exists():
        q = _load_json(trace_path).get("query")
        if q:
            return q
    raw = TICKETS / key / "raw.md"
    if raw.exists():
        return raw.read_text(encoding="utf-8")
    pytest.skip(f"{key}: no recorded query and no raw.md — cannot replay the probe")


def _probe_trace(mod, key: str, views: dict) -> dict:
    query = _ticket_query(key)
    return mod.build_trace(query, "deterministic", views["modules.json"],
                           views["file_roles.json"], views["module_edges.json"],
                           views["test_map.json"], views["inventory.json"],
                           views.get("token_idf.json"))


def test_ten_test_heavy_modules_absent_from_every_probe_primary_modules(fresh_index):
    """AC-11: over the fresh index, the computed set of >= 80% `is_test`
    modules (A-101: the ASSERTION is the computed set, never a literal
    count — F-005 measured fourteen on 2026-09-17, not the spec's ten) is
    absent from every probe trace's `primary_modules`."""
    views = _views(fresh_index)
    mod = _load_skill()
    test_heavy = mod._test_heavy_modules(views["file_roles.json"].get("files") or {})
    assert test_heavy, "expected at least one >=80%-test module in the fresh index"

    for key in ("KLC-100", "KLC-101", "KLC-102"):
        trace = _probe_trace(mod, key, views)
        primary = {m["module_name"] for m in trace.get("primary_modules") or []}
        overlap = primary & test_heavy
        assert not overlap, f"{key}: test-heavy module(s) in primary_modules: {overlap}"


def test_klc101_probe_demotes_to_medium_not_high(fresh_index):
    """AC-12/AC-16, Q-005: KLC-101's truth set is eleven `core/agents/*.md`
    prompts carrying no symbols at all, so no symbol-based retriever can
    rank them — `precision_at_5` for KLC-101 stays 0 by construction.
    AC-16 is satisfied by HONEST DEMOTION: `_HIGH_SEPARATION_RATIO`
    (design's `2.0` [D-006], retuned to `4.0` at build time by
    `[!DECISION D-108-7]` against the real 110/111-ticket corpus — see
    `mod._HIGH_SEPARATION_RATIO`, never hardcoded here so this docstring
    cannot go stale on a future retune) is chosen specifically so this
    probe's separation falls below it and the trace reports `medium`, not
    `high`."""
    views = _views(fresh_index)
    mod = _load_skill()
    trace = _probe_trace(mod, "KLC-101", views)
    assert trace["confidence"] != "high", (
        f"KLC-101 must not report high confidence — reasons: {trace['reasons']}")


@pytest.mark.parametrize("live_index_state", ["absent", "stale", "current"], indirect=True)
def test_probe_traces_verdict_unchanged_by_live_index_state(
        live_index_state, no_index_reads, fresh_index):
    """AC-2: the test-heavy set and the KLC-101 confidence verdict are the
    same whatever the live `.klc/index/` holds, and the check never reads
    it — both `modules.json`/`file_roles.json`/... come from `fresh_index`
    regardless of `PROJECT_ROOT`."""
    views = _views(fresh_index)
    mod = _load_skill()
    test_heavy = mod._test_heavy_modules(views["file_roles.json"].get("files") or {})
    assert test_heavy

    for key in ("KLC-100", "KLC-101", "KLC-102"):
        trace = _probe_trace(mod, key, views)
        primary = {m["module_name"] for m in trace.get("primary_modules") or []}
        assert not (primary & test_heavy), key

    trace_101 = _probe_trace(mod, "KLC-101", views)
    assert trace_101["confidence"] != "high"
    assert no_index_reads() == []
