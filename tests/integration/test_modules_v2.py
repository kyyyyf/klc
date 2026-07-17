"""KLC-066 step-4 — deterministic modules.json v2 clustering (AC-3, AC-4).

build_modules() is a pure, no-LLM, byte-reproducible clustering. `path` stays the
canonical longest-prefix key and `name` a stable slug; no `id`, no `root_paths`.
The per-file `files` override map is deliberately empty here (needs the KLC-070
inventory) — this test pins that documented boundary too.
"""
import json
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import modules_build as mb  # noqa: E402
import module_membership as mm  # noqa: E402


STRUCTURAL = {
    "root": "/repo",
    "profile": "generic",
    "total_files": 6,
    "languages": {"python": {}},
    "directory_tree": [{"path": "core", "files": 4}, {"path": "scripts", "files": 2}],
    "entry_points": ["scripts/init.py"],
    "source_roots": [],
}
DEPGRAPH = {
    "import_graphs": {
        "python": {
            "nodes": [
                {"id": "core/skills/a.py"}, {"id": "core/skills/b.py"},
                {"id": "core/phases/intake.py"}, {"id": "scripts/init.py"},
            ],
            "edges": [
                {"from": "scripts/init.py", "to": "core/skills/a.py"},
                {"from": "core/phases/intake.py", "to": "core/skills/b.py"},
            ],
        }
    }
}


def test_deterministic_byte_identical_on_rerun():
    """AC-3: two runs over the same inputs are byte-identical (pure function)."""
    a = mb.build_modules(STRUCTURAL, DEPGRAPH)
    b = mb.build_modules(STRUCTURAL, DEPGRAPH)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # and no timestamp leaked into the membership object
    assert "generated_at" not in a


def test_path_is_canonical_and_name_is_slug():
    """AC-4: path preserved as the longest-prefix key; name is its slug."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH)
    by_name = {m["name"]: m for m in res["modules"]}
    assert "core/skills" in by_name
    assert by_name["core/skills"]["path"] == "core/skills/"
    # name is exactly the path minus the trailing slash
    for m in res["modules"]:
        assert m["name"] == m["path"].rstrip("/")


def test_no_id_and_no_root_paths_fields():
    """AC-4: v2 introduces neither `id` nor `root_paths`."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH)
    for m in res["modules"]:
        assert "id" not in m
        assert "root_paths" not in m


def test_clusters_files_by_directory():
    res = mb.build_modules(STRUCTURAL, DEPGRAPH)
    by_name = {m["name"]: m for m in res["modules"]}
    assert by_name["core/skills"]["files"] == ["core/skills/a.py", "core/skills/b.py"]
    assert by_name["scripts"]["files"] == ["scripts/init.py"]
    # entry_points under a module path are captured
    assert by_name["scripts"]["primary_entrypoints"] == ["scripts/init.py"]


def test_every_module_has_path_and_files():
    res = mb.build_modules(STRUCTURAL, DEPGRAPH)
    assert res["modules"]  # non-empty
    for m in res["modules"]:
        assert m["path"]
        assert m["files"]  # every clustered module owns at least one file


def test_result_is_resolver_compatible():
    """The produced modules.json resolves through the single file_to_module()."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH)
    r = mm.file_to_module("core/skills/a.py", res)
    assert r["primary_module"] == "core/skills"
    assert r["resolution_source"] == "longest_prefix"


def test_files_override_map_empty_documented_boundary():
    """The per-file override map is empty here (needs KLC-070 inventory)."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH)
    assert res["files"] == {}


def test_root_level_file_is_resolver_compatible():
    """FIX-2: a repo-root file (e.g. main.py) must resolve to its module, not be
    orphaned. dirname('main.py')=='' used to yield a './'-path module the resolver
    could not match; root files are now registered as `files` overrides."""
    dg = {"import_graphs": {"python": {
        "nodes": [{"id": "main.py"}, {"id": "core/skills/a.py"}],
        "edges": [{"from": "main.py", "to": "core/skills/a.py"}],
    }}}
    res = mb.build_modules(STRUCTURAL, dg)
    # main.py appears in some module's files list ...
    owning = [m["name"] for m in res["modules"] if "main.py" in m.get("files", [])]
    assert owning, "root file main.py was dropped from every module"
    # ... AND the resolver attributes it (not an orphan)
    r = mm.file_to_module("main.py", res)
    assert r["primary_module"] is not None
    assert r["resolution_source"] != "orphan"
    assert r["primary_module"] in owning


def test_root_module_public_api_not_dropped_by_public_api_filter():
    """FIX-2 (round 2): the root module must have a truthy path so
    public-api-filter does not treat it as symbol-less and drop the root file's
    public API. A path of '' would zero out public_api_total."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "public_api_filter", str(_skills / "public-api-filter.py"))
    paf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(paf)

    dg = {"import_graphs": {"python": {
        "nodes": [{"id": "main.py"}], "edges": []}}}
    res = mb.build_modules(STRUCTURAL, dg)
    root = next(m for m in res["modules"] if "main.py" in m.get("files", []))
    assert root["path"], "root module path must be truthy (not '') for public-api-filter"

    inv = {"symbols": {"python": {"items": [
        {"file": "main.py", "name": "main", "kind": "function",
         "signature": "def main(): pass"}]}}}
    _, _, sbm = paf.trim_modules(inv, res, cap=15)
    by_name = {m["name"]: m for m in res["modules"]}
    # the root file's symbol is attributed to the root module and NOT dropped
    assert "main" in [it["name"] for it in sbm.get(root["name"], [])]
    assert by_name[root["name"]]["public_api_total"] >= 1


def test_degrades_without_depgraph():
    """No depgraph → coarse directory_tree clustering + an errors[] note, not a
    crash (degrade-not-fail)."""
    res = mb.build_modules(STRUCTURAL, None)
    assert res["modules"]           # still produced something
    assert any("depgraph" in e for e in res["errors"])
