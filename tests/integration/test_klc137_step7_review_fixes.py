"""KLC-137 step-7 — review round 1 fixes.

code-review: F-1 (MEDIUM, AC-7 crash on a non-dict symbol element), F-2
(MEDIUM, AC-6 primary sort key untested), F-3 (LOW, AC-3 stale docstring
example). external-review: the same AC-7/AC-6 pair plus the AC-9 stale-range
guard (MEDIUM: a block that grows/shrinks inside the range) and the AC-3
docstring duplicate (LOW). One test per finding, written FIRST and confirmed
RED against the unmodified tree before any fix landed.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
AGENTS = REPO_ROOT / "core" / "agents"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _klc137_fixtures import retriever_views  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_project_root")

_SLICE_PROMPTS = ("discovery.md", "discovery-lite.md", "design.md", "design-scout.md")


def _load_skill():
    spec = importlib.util.spec_from_file_location(
        "klc137_step7_planning_retriever", str(SKILLS / "planning-retriever.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_line_ranges_orders_by_idf_weight_descending_not_only_by_start(tmp_path):
    """AC-6 (code-review MEDIUM + external MEDIUM): the "weighted" fixture
    gives `rare_gizmo_widget` the corpus's HIGHEST weight (its own token
    "gizmo" is unique to its file) while `WidgetBuilder`/`build_widget`/
    `widget_alpha`/`widget_beta` all match only through "widget" (the
    corpus's LOWEST weight, shared with a second file's purpose line) —
    `rare_gizmo_widget` sits LAST by `start` (17, latest of the five) but
    must rank FIRST in `line_ranges`, proving the primary sort key is IDF
    weight descending, not merely the `start` tiebreak (mutation-verified by
    the review: reversing the weight key left every prior test green)."""
    pr = _load_skill()
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "weighted")
    trace = pr.build_trace("widget gizmo", "deterministic", modules, fr, module_edges,
                           test_map, inventory=inv, token_idf=token_idf)
    entries = trace["line_ranges"]["pkg3/mod.py"]
    assert len(entries) == 3
    assert entries[0]["symbol"] == "rare_gizmo_widget", (
        "the rare-token symbol must rank first despite its later start")
    assert entries[0]["start"] == 17
    assert [e["symbol"] for e in entries[1:]] == ["WidgetBuilder", "build_widget"]


def test_non_dict_symbol_element_is_skipped_not_crashed(tmp_path):
    """AC-7 (code-review MEDIUM / external LOW): a stray non-dict element in
    `inventory['symbols']` (the review's own repro: `inv['symbols'].append(1)`)
    must not crash `build_trace` — `_symbols_by_file_name` skips it, matching
    `planning_validate.py`'s own `isinstance(s, dict)` guard, and the trace
    still returns `status:'ok'` with real ranges for the well-formed
    symbols."""
    pr = _load_skill()
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    malformed = copy.deepcopy(inv)
    malformed["symbols"].append(1)
    trace = pr.build_trace("widget", "deterministic", modules, fr, module_edges, test_map,
                           inventory=malformed, token_idf=token_idf)
    assert trace["status"] == "ok"
    assert trace["line_ranges"], "well-formed symbols must still produce ranges"


def test_stale_range_guard_covers_a_grown_block_and_says_ranges_are_a_starting_point():
    """AC-9 (external MEDIUM): the stale-range guard must also cover the
    common staleness case — lines added/removed INSIDE the block, where the
    symbol name is still on `start` but `end` no longer bounds the real
    block — and must tell the agent the (at most 3) ranges are a starting
    point, not the whole read. All four slice-opening prompts carry the
    same short wording; the four fields the retriever/index/prompt-honesty
    suites already pin (`line_ranges`, `symbol`, `start`, "whole file")
    must all still be present."""
    for name in _SLICE_PROMPTS:
        text = (AGENTS / name).read_text(encoding="utf-8")
        assert "starting point" in text, f"{name} does not say ranges are a starting point"
        assert "`end`" in text, f"{name} does not name `end` in the staleness guard"
        for needle in ("`line_ranges`", "`symbol`", "`start`", "whole file"):
            assert needle in text, f"{name} lacks {needle!r}"


def test_architecture_md_documents_that_decorators_sit_above_start():
    """AC-9 (external LOW): Python ranges start at the `def`/`class` line
    and exclude decorators — documented next to the staleness guidance in
    `docs/architecture.md` (the alternative fix the review itself offered,
    used instead of lengthening the byte-constrained prompts further)."""
    text = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    start = text.index("## Symbol line ranges (KLC-137)")
    nxt = text.find("\n## ", start + 1)
    section = text[start: nxt if nxt != -1 else len(text)]
    assert "decorator" in section.lower()
    assert "above `start`" in section or "above the `start`" in section


def test_deterministic_inventory_docstring_has_no_stale_symbol_shape_example():
    """AC-3 (code-review LOW / external LOW): the module docstring's inline
    symbol-shape example is a second, driftable copy of `SYMBOL_FIELDS`
    (its own comment says the schema is 'stated ONCE' elsewhere) — it must
    not exist as a second copy any more; the docstring points at
    `core.shared.inventory.CANONICAL_SCHEMA` instead."""
    text = (SKILLS / "deterministic_inventory.py").read_text(encoding="utf-8")
    # the retired inline example this finding is about
    assert '"name": str, "kind": str, "file": str, "line": int,' not in text
