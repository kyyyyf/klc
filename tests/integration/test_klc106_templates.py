"""KLC-106 step-7 — the generated documents stop stating "none" when the
truth is "not measured" (AC-12, AC-13).

Real-substrate tests: render_module()/render_root() are invoked for real
(Jinja2 templates on disk) against a temp PROJECT_ROOT.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"


def _load_module_writer():
    spec = importlib.util.spec_from_file_location(
        "klc106_module_writer", str(_SKILLS / "module-writer.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_index(root: Path, **artifacts) -> None:
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (idx / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


# D-213 (review round 1, HIGH finding #2): a REAL modules_build.py record —
# {"name", "path", "files", "primary_entrypoints", "source", "depends_on",
# "depended_by"} — carries no "language" field; no builder ever writes one
# (this repo's own live .klc/index/modules.json confirms it, and
# modules_build.py's own output shape has none). Injecting a "language" key
# here would mask exactly the bug this ticket fixes (feedback-mock-real-
# contract: mock the real contract, not a convenient one).
MODULE = {"name": "modA", "path": "src/a", "files": ["src/a/mod.py"],
         "primary_entrypoints": [], "source": "directory_tree",
         "depends_on": [], "depended_by": []}


def _render(tmp_path, monkeypatch, depgraph=None, **extra_artifacts):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / "src" / "a").mkdir(parents=True, exist_ok=True)
    artifacts = {"inventory": {"symbols": [], "notes": []},
                 "modules": {"modules": [MODULE], "cycles": [], "notes": []}}
    artifacts.update(extra_artifacts)
    if depgraph is not None:
        artifacts["depgraph"] = depgraph
    _write_index(tmp_path, **artifacts)
    mw = _load_module_writer()
    out = mw.render_module(dict(MODULE), tmp_path / "src" / "a" / "CLAUDE.md")
    return out.read_text(encoding="utf-8"), mw


# --------------------------------------------------------------------- AC-12

def test_module_template_renders_none_only_when_graph_healthy_and_genuinely_empty(
        tmp_path, monkeypatch):
    """Table-driven over (graph_degraded, edges): only the (healthy, empty)
    cell may render `_none_`; every degraded/absent cell renders "not
    indexed", never the two conflated. The graph's `nodes` list carries the
    module's OWN file (`src/a/mod.py`, matching MODULE["files"]) — D-213:
    coverage is decided by which graph's nodes include the module's files,
    never by a `language` key modules.json does not have."""
    cases = [
        ("absent", None),
        ("degraded", {"import_graphs": {"python": {
            "edges": [], "nodes": [{"id": "src/a/mod.py"}],
            "degraded": True, "reason": "x"}}}),
        ("healthy", {"import_graphs": {"python": {
            "edges": [], "nodes": [{"id": "src/a/mod.py"}],
            "degraded": False, "reason": "x"}}}),
    ]
    for label, depgraph in cases:
        text, _ = _render(tmp_path, monkeypatch, depgraph=depgraph)
        if label == "healthy":
            assert "_none_" in text, label
            assert "not indexed" not in text, label
        else:
            assert "not indexed (dependency graph unavailable)" in text, label
            assert "_none_" not in text, label


def test_module_template_renders_not_indexed_when_graph_absent_or_degraded(
        tmp_path, monkeypatch):
    text, _ = _render(tmp_path, monkeypatch, depgraph=None)
    assert "not indexed (dependency graph unavailable)" in text
    text2, _ = _render(tmp_path, monkeypatch, depgraph={"import_graphs": {"python": {
        "edges": [], "nodes": [{"id": "src/a/mod.py"}],
        "degraded": True, "reason": "x"}}})
    assert "not indexed (dependency graph unavailable)" in text2


def test_module_template_renders_not_indexed_when_no_graph_covers_the_module_files(
        tmp_path, monkeypatch):
    """D-213 regression guard: a HEALTHY graph that simply does not cover
    this module's files (e.g. a different language/module entirely) must
    still render "not indexed", never `_none_` — the module was never
    measured, so an empty depends_on says nothing about it."""
    text, _ = _render(tmp_path, monkeypatch, depgraph={"import_graphs": {"python": {
        "edges": [], "nodes": [{"id": "src/other/unrelated.py"}],
        "degraded": False, "reason": "x"}}})
    assert "not indexed (dependency graph unavailable)" in text
    assert "_none_" not in text


def test_deps_fallback_none_against_real_modules_build_shaped_record(tmp_path, monkeypatch):
    """D-213 (review round 1, HIGH finding #2): the fix must work against a
    module dict shaped EXACTLY like modules_build.py's real output — no
    'language' key injected, matching this repo's own live
    .klc/index/modules.json. The previous version of this test only proved
    the function worked for a shape the pipeline never produces."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    real_module = {"name": "modA", "path": "src/a", "files": ["src/a/mod.py"],
                   "primary_entrypoints": [], "source": "directory_tree",
                   "depends_on": [], "depended_by": []}
    assert "language" not in real_module
    (tmp_path / "src" / "a").mkdir(parents=True, exist_ok=True)
    _write_index(
        tmp_path,
        inventory={"symbols": [], "notes": []},
        modules={"modules": [real_module], "cycles": [], "notes": []},
        depgraph={"import_graphs": {"python": {
            "edges": [], "nodes": [{"id": "src/a/mod.py"}],
            "degraded": False, "reason": "x"}}})
    mw = _load_module_writer()
    out = mw.render_module(dict(real_module), tmp_path / "src" / "a" / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    assert "_none_" in text
    assert "not indexed" not in text


# review round 2, MEDIUM (module-writer.py:303): D-213's `all(degraded)`
# completeness check requires EVERY covering graph to be degraded before
# falling back to "not indexed" — a two-language module with ONE healthy
# and ONE degraded covering graph slips through `all(...)` as False and
# renders `_none_`, claiming a full measurement when half the module's
# dependency picture is actually unmeasured. D-214 fixes this.
def test_deps_fallback_reports_partial_when_only_some_covering_graphs_are_degraded(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    module = {"name": "modAB", "path": "src/ab",
              "files": ["src/ab/mod.py", "src/ab/mod.ts"],
              "primary_entrypoints": [], "source": "directory_tree",
              "depends_on": [], "depended_by": []}
    (tmp_path / "src" / "ab").mkdir(parents=True, exist_ok=True)
    _write_index(
        tmp_path,
        inventory={"symbols": [], "notes": []},
        modules={"modules": [module], "cycles": [], "notes": []},
        depgraph={"import_graphs": {
            "python": {"edges": [], "nodes": [{"id": "src/ab/mod.py"}],
                       "degraded": False, "reason": "x"},
            "typescript": {"edges": [], "nodes": [{"id": "src/ab/mod.ts"}],
                           "degraded": True, "reason": "y"},
        }})
    mw = _load_module_writer()
    out = mw.render_module(dict(module), tmp_path / "src" / "ab" / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    # Neither conflated reading is acceptable: not a clean "_none_" (that
    # would hide the typescript graph's degradation) and not the blanket
    # "not indexed" (that would hide the python graph's real, healthy
    # measurement) — the text must name the partial state honestly.
    assert "_none_" not in text
    assert "not indexed (dependency graph unavailable)" not in text
    assert "typescript" in text
    assert "partial" in text.lower()


def test_deps_fallback_not_indexed_when_module_has_no_files(tmp_path, monkeypatch):
    """A module with an empty `files` list can never be covered by any
    graph's node membership check — must stay "not indexed", never
    silently fall through to `_none_`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    module = {"name": "modEmpty", "path": "src/empty", "files": [],
              "primary_entrypoints": [], "source": "directory_tree",
              "depends_on": [], "depended_by": []}
    (tmp_path / "src" / "empty").mkdir(parents=True, exist_ok=True)
    _write_index(
        tmp_path,
        inventory={"symbols": [], "notes": []},
        modules={"modules": [module], "cycles": [], "notes": []},
        depgraph={"import_graphs": {"python": {
            "edges": [], "nodes": [{"id": "src/a/mod.py"}],
            "degraded": False, "reason": "x"}}})
    mw = _load_module_writer()
    out = mw.render_module(dict(module), tmp_path / "src" / "empty" / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    assert "not indexed (dependency graph unavailable)" in text
    assert "_none_" not in text


def test_deps_fallback_not_indexed_for_module_scoped_non_path_node_graph(
        tmp_path, monkeypatch):
    """Review round 2 MEDIUM: a producer whose graph nodes are keyed by a
    module-scoped id rather than a repo-relative file path (the shape the
    cpp-unreal `*.Build.cs` walk uses — `{"id": "MyGameModule", "path":
    "Source/MyGameModule/MyGameModule.Build.cs"}`, never one of the
    module's own `.cpp`/`.h` files) must never be silently read as covering
    a module just because it happens to be healthy. `_graph_covers_files`
    only matches file-path node ids against `module['files']`, so this
    stays "not indexed" — the conservative, honest reading when coverage
    genuinely cannot be determined by file identity — never `_none_`. This
    fixture is deliberately generic (not literally named cpp-unreal/ue,
    which KLC-122 is removing) — it guards the SHAPE, not the producer."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    module = {"name": "MyGameModule", "path": "Source/MyGameModule",
              "files": ["Source/MyGameModule/Foo.cpp", "Source/MyGameModule/Foo.h"],
              "primary_entrypoints": [], "source": "directory_tree",
              "depends_on": [], "depended_by": []}
    (tmp_path / "Source" / "MyGameModule").mkdir(parents=True, exist_ok=True)
    _write_index(
        tmp_path,
        inventory={"symbols": [], "notes": []},
        modules={"modules": [module], "cycles": [], "notes": []},
        depgraph={"import_graphs": {"module-scoped": {
            "edges": [],
            "nodes": [{"id": "MyGameModule",
                       "path": "Source/MyGameModule/MyGameModule.Build.cs"}],
            "degraded": False, "reason": "x"}}})
    mw = _load_module_writer()
    out = mw.render_module(dict(module), tmp_path / "Source" / "MyGameModule" / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    assert "not indexed (dependency graph unavailable)" in text
    assert "_none_" not in text


# --------------------------------------------------------------------- AC-13

def _render_root(tmp_path, monkeypatch, **extra_artifacts):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    artifacts = {"inventory": {"symbols": [], "notes": []},
                 "modules": {"modules": [], "cycles": [], "notes": []},
                 "structural": {"total_files": 1, "total_lines": 1, "languages": {}}}
    artifacts.update(extra_artifacts)
    mw = _load_module_writer()
    out = mw.render_root(tmp_path / "CLAUDE.md")
    return out.read_text(encoding="utf-8"), mw


def test_root_claude_md_lists_degraded_builders_with_metric_ratio_reason(
        tmp_path, monkeypatch):
    depgraph = {"import_graphs": {}, "package_graphs": {}, "errors": [
        {"builder": "dep_graph:import-graph.py", "artifact": "depgraph.json",
         "metric": "node-coverage", "observed": 1, "universe": 20,
         "ratio": 0.05, "threshold": 0.25, "degraded": True,
         "reason": "node-coverage 0.05 below threshold 0.25 (1/20)"}]}
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_index(tmp_path,
                 inventory={"symbols": [], "notes": []},
                 modules={"modules": [], "cycles": [], "notes": []},
                 structural={"total_files": 1, "total_lines": 1, "languages": {}},
                 depgraph=depgraph)
    mw = _load_module_writer()
    out = mw.render_root(tmp_path / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    assert "dep_graph:import-graph.py" in text
    assert "0.05" in text
    assert "node-coverage 0.05 below threshold 0.25 (1/20)" in text


def test_root_claude_md_omits_degraded_section_when_nothing_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_index(tmp_path,
                 inventory={"symbols": [], "notes": []},
                 modules={"modules": [], "cycles": [], "notes": []},
                 structural={"total_files": 1, "total_lines": 1, "languages": {}})
    mw = _load_module_writer()
    out = mw.render_root(tmp_path / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    assert "DEGRADED" not in text


def test_root_claude_md_keeps_notes_truncation_line_with_more_than_ten_notes_and_nothing_degraded(
        tmp_path, monkeypatch):
    """Review F-6 regression guard: >10 notes, nothing degraded -> the
    existing truncation tail must still appear, byte-identical to the
    pre-KLC-106 render."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    notes = [f"note-{i}" for i in range(13)]
    _write_index(tmp_path,
                 inventory={"symbols": [], "notes": notes},
                 modules={"modules": [], "cycles": [], "notes": []},
                 structural={"total_files": 1, "total_lines": 1, "languages": {}})
    mw = _load_module_writer()
    out = mw.render_root(tmp_path / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    assert "_… 3 more; see `.klc/index/inventory.json` and `.klc/index/modules.json`._" in text
