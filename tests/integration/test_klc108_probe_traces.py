"""KLC-108 — e2e probe traces over the LIVE index (real substrate, no
fixtures): the three probe tickets the spec measured (KLC-100, KLC-101,
KLC-102), replayed with their own recorded query against the CURRENT
(post-KLC-108) planning views.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX = REPO_ROOT / ".klc" / "index"
TICKETS = REPO_ROOT / ".klc" / "tickets"
_SKILL = REPO_ROOT / "core" / "skills" / "planning-retriever.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_retriever_probe", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _require_live_views() -> dict:
    names = ["modules.json", "file_roles.json", "module_edges.json",
            "test_map.json", "inventory.json"]
    for name in names:
        if not (INDEX / name).exists():
            pytest.skip(f"no .klc/index/{name} — run the index builders first")
    return {name.split(".")[0].replace("_", "-"): _load_json(INDEX / name)
           for name in names}


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


def _probe_trace(mod, key: str) -> dict:
    modules = _load_json(INDEX / "modules.json")
    file_roles = _load_json(INDEX / "file_roles.json")
    module_edges = _load_json(INDEX / "module_edges.json")
    test_map = _load_json(INDEX / "test_map.json")
    inventory = _load_json(INDEX / "inventory.json")
    token_idf = None
    if (INDEX / "token_idf.json").exists():
        token_idf = _load_json(INDEX / "token_idf.json")
    query = _ticket_query(key)
    return mod.build_trace(query, "deterministic", modules, file_roles,
                           module_edges, test_map, inventory, token_idf)


def test_ten_test_heavy_modules_absent_from_every_probe_primary_modules():
    """AC-11: over the klc index, the computed set of >= 80% `is_test`
    modules (A-101: the ASSERTION is the computed set, never a literal
    count — F-005 measured fourteen on 2026-09-17, not the spec's ten) is
    absent from every probe trace's `primary_modules`."""
    _require_live_views()
    mod = _load_skill()
    file_roles = _load_json(INDEX / "file_roles.json")
    test_heavy = mod._test_heavy_modules(file_roles.get("files") or {})
    assert test_heavy, "expected at least one >=80%-test module in the live index"

    for key in ("KLC-100", "KLC-101", "KLC-102"):
        trace = _probe_trace(mod, key)
        primary = {m["module_name"] for m in trace.get("primary_modules") or []}
        overlap = primary & test_heavy
        assert not overlap, f"{key}: test-heavy module(s) in primary_modules: {overlap}"


def test_klc101_probe_demotes_to_medium_not_high():
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
    _require_live_views()
    mod = _load_skill()
    trace = _probe_trace(mod, "KLC-101")
    assert trace["confidence"] != "high", (
        f"KLC-101 must not report high confidence — reasons: {trace['reasons']}")
