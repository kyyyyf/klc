"""KLC-137 step-4 — `build_trace` emits `line_ranges` (AC-5, AC-6, AC-7).

Real-substrate: every trace here is built by the real `build_trace` over
real `file_roles`/`inventory` views from `retriever_views` (C-005) — never a
hand-shaped trace dict.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _klc137_fixtures import retriever_views  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_project_root")

_GOLDEN = REPO_ROOT / "tests" / "integration" / "_klc137_pre_ticket_trace.json"


def _load_skill():
    spec = importlib.util.spec_from_file_location(
        "klc137_planning_retriever", str(SKILLS / "planning-retriever.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _base_trace(pr, tmp_path, query="widget"):
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    trace = pr.build_trace(query, "deterministic", modules, fr, module_edges, test_map,
                           inventory=inv, token_idf=token_idf)
    return trace, (modules, fr, module_edges, test_map, inv, token_idf)


def test_entry_only_for_symbols_whose_own_name_gave_the_strong_hit(tmp_path):
    """AC-5: `pkg/other.py` enters the read slice only through its OWN
    docstring keyword ("widget") — none of its symbol names match the query
    — so it must carry no `line_ranges` key, even though it is present in
    both candidate lists."""
    pr = _load_skill()
    trace, _views = _base_trace(pr, tmp_path)
    assert "pkg/other.py" in trace["files_to_read_first"]
    assert "pkg/other.py" in trace["files_likely_to_edit"]
    assert "pkg/other.py" not in trace["line_ranges"]
    assert "pkg/widgets.py" in trace["line_ranges"]


def test_line_ranges_keys_are_only_paths_from_the_two_candidate_lists(tmp_path):
    """AC-5: `_line_ranges` never produces a key outside the `paths` set it
    was called with — proven directly by excluding `pkg/widgets.py` (which
    unambiguously has matching symbols) from the passed set and confirming
    it gets no entry. `build_trace` itself only ever calls `_line_ranges`
    with `set(files_to_read_first) | set(files_likely_to_edit)` (D-105), so
    this closes the loop with the trace-level behaviour."""
    pr = _load_skill()
    _trace, (modules, fr, module_edges, test_map, inv, token_idf) = _base_trace(pr, tmp_path)
    qtokens = pr.tokenize("widget")
    roles = fr["files"]
    restricted = pr._line_ranges(qtokens, {"pkg/other.py"}, roles, inv, token_idf)
    assert "pkg/widgets.py" not in restricted
    full = pr._line_ranges(qtokens, {"pkg/other.py", "pkg/widgets.py"}, roles, inv, token_idf)
    assert "pkg/widgets.py" in full


def test_class_matched_by_two_rules_is_one_deduplicated_entry(tmp_path):
    """AC-5: `WidgetBuilder` (a class with a base) is matched by BOTH
    `py-public-api` and `py-class-hierarchy` — deduplication by
    `(symbol, kind, start, end)` collapses the pair into ONE entry; its
    method `build_widget` is a separate entry."""
    pr = _load_skill()
    trace, _views = _base_trace(pr, tmp_path)
    entries = trace["line_ranges"]["pkg/widgets.py"]
    widget_builder_entries = [e for e in entries if e["symbol"] == "WidgetBuilder"]
    assert len(widget_builder_entries) == 1
    assert any(e["symbol"] == "build_widget" for e in entries)


def test_file_with_more_than_25_symbols_still_respects_the_signal_cap(tmp_path):
    """AC-5: `pkg2/wide.py` carries 30 symbols; its only query-matching name
    ("widget") has the lowest IDF weight in the corpus (shared with a
    second file's purpose line) and so never makes the
    `_SYMBOL_SIGNAL_CAP` of 25 — the file still enters `files_to_read_first`
    but gets no `line_ranges` key."""
    pr = _load_skill()
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "wide25")
    assert len(fr["files"]["pkg2/wide.py"]["symbols"]) > 25
    trace = pr.build_trace("widget", "deterministic", modules, fr, module_edges, test_map,
                           inventory=inv, token_idf=token_idf)
    assert "pkg2/wide.py" in trace["files_to_read_first"]
    assert "pkg2/wide.py" not in trace["line_ranges"]


def test_line_ranges_capped_at_3_ordered_by_idf_then_start_then_name_and_byte_reproducible(tmp_path):
    """AC-6: `pkg/widgets.py` has 5 symbols matching "widget" (all tied on
    IDF weight, since "widget" is their only shared query token) — capped at
    3, kept by ascending `start`: `WidgetBuilder` (4), `build_widget` (5),
    `widget_alpha` (9); `widget_beta`/`widget_gamma` are excluded. Two
    independent `build_trace` runs on identical inputs produce byte-identical
    traces."""
    pr = _load_skill()
    trace, views = _base_trace(pr, tmp_path)
    entries = trace["line_ranges"]["pkg/widgets.py"]
    assert len(entries) == 3
    assert [e["symbol"] for e in entries] == ["WidgetBuilder", "build_widget", "widget_alpha"]
    assert [e["start"] for e in entries] == sorted(e["start"] for e in entries)

    modules, fr, module_edges, test_map, inv, token_idf = views
    trace2 = pr.build_trace("widget", "deterministic", modules, fr, module_edges, test_map,
                            inventory=inv, token_idf=token_idf)
    assert json.dumps(trace, sort_keys=True) == json.dumps(trace2, sort_keys=True)


def test_strong_hit_symbol_with_null_line_end_is_excluded_while_a_sibling_with_a_valid_range_is_kept(tmp_path):
    """AC-5 (test-plan-review F-2): `widget_alpha`'s `line_end` is nulled on
    one real inventory (simulating a regex-shaped symbol) — its own entry
    disappears, but the cap slot it freed is filled by `widget_beta` (the
    next-earliest-`start` symbol among the tied-weight candidates), never a
    fabricated or omitted-range entry."""
    pr = _load_skill()
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    mutated = copy.deepcopy(inv)
    target = next(s for s in mutated["symbols"] if s["name"] == "widget_alpha")
    assert isinstance(target["line_end"], int), "must mutate a real int, not a vacuous case"
    target["line_end"] = None

    trace = pr.build_trace("widget", "deterministic", modules, fr, module_edges, test_map,
                           inventory=mutated, token_idf=token_idf)
    entries = trace["line_ranges"]["pkg/widgets.py"]
    names = [e["symbol"] for e in entries]
    assert "widget_alpha" not in names
    assert "widget_beta" in names
    assert len(entries) == 3


@pytest.mark.parametrize("case", ["no_views", "no_modules", "no_file_roles"])
def test_status_not_ok_trace_emits_empty_line_ranges_dict(tmp_path, case):
    """AC-6: every `_empty_trace` path (status != "ok") carries
    `"line_ranges": {}` — the three ways `build_trace` degrades to
    `status:"unavailable"` (planning_indexer.md: no views at all, no
    modules.json, or no file_roles.json)."""
    pr = _load_skill()
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    empty_modules = {"modules": []}
    empty_roles = {"files": {}}
    args = {
        "no_views": (empty_modules, empty_roles),
        "no_modules": (empty_modules, fr),
        "no_file_roles": (modules, empty_roles),
    }[case]
    trace = pr.build_trace("widget", "deterministic", args[0], args[1], module_edges,
                           test_map, inventory=inv, token_idf=token_idf)
    assert trace["status"] != "ok"
    assert trace["line_ranges"] == {}


def test_status_ok_with_nonempty_degraded_inputs_still_emits_ranges(tmp_path):
    """AC-6 (spec-review D-2/Q-008): a `status:"ok"` trace with a non-empty
    `degraded_inputs` (here, an empty `module_edges`) still emits
    `line_ranges` entries — the empty-map rule is keyed on `status`, never
    on `degraded_inputs`."""
    pr = _load_skill()
    modules, fr, _module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    empty_edges = {"edges": [], "errors": [], "notes": []}
    trace = pr.build_trace("widget", "deterministic", modules, fr, empty_edges, test_map,
                           inventory=inv, token_idf=token_idf)
    assert trace["status"] == "ok"
    assert trace["degraded_inputs"]
    assert trace["line_ranges"]


def test_old_inventory_without_line_end_yields_empty_line_ranges_and_byte_identical_rest_of_trace(tmp_path):
    """AC-7: an inventory built before this ticket (no `line_end` key at
    all) yields `line_ranges: {}` with no new `degraded_inputs` entry, no
    `confidence` change, no new `reasons` line — and the REST of the trace
    is byte-identical to the golden trace the unmodified (pre-ticket)
    retriever produced on these exact fixture inputs (D-106)."""
    pr = _load_skill()
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    old_inv = copy.deepcopy(inv)
    for s in old_inv["symbols"]:
        s.pop("line_end", None)

    trace = pr.build_trace("widget", "deterministic", modules, fr, module_edges, test_map,
                           inventory=old_inv, token_idf=token_idf)
    assert trace["line_ranges"] == {}

    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    without_ranges = dict(trace)
    without_ranges.pop("line_ranges")
    assert json.dumps(without_ranges, indent=2, ensure_ascii=False) + "\n" == \
        json.dumps(golden, indent=2, ensure_ascii=False) + "\n"
