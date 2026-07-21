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


# --------------------------------------------------------------------------- #
# KLC-074: full-file-listing clustering (non-code directories no longer orphan)
# --------------------------------------------------------------------------- #
ALL_FILES = [
    "core/skills/a.py", "core/skills/b.py", "core/phases/intake.py",
    "scripts/init.py",
    # non-code files that the import graph never sees:
    "docs/guide.md", "docs/adr/0001.md", "core/agents/review.md",
    "config/models.yml",
]


def test_all_files_covers_non_code_directories():
    """KLC-074: feeding the full tracked-file listing makes non-code directories
    (docs/, core/agents/, config/) real modules instead of orphaning their files."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH, all_files=ALL_FILES)
    names = {m["name"] for m in res["modules"]}
    assert {"docs", "docs/adr", "core/agents", "config"} <= names, names
    # and the resolver attributes a non-code file to its directory module (not orphan)
    r = mm.file_to_module("core/agents/review.md", res)
    assert r["primary_module"] == "core/agents"
    assert r["resolution_source"] == "longest_prefix"
    # a config yaml resolves too
    assert mm.file_to_module("config/models.yml", res)["primary_module"] == "config"


def test_all_files_byte_reproducible():
    """KLC-074: build_modules is pure over (structural, depgraph, all_files) — the same
    all_files list yields byte-identical membership on re-run (AC-3 preserved)."""
    a = mb.build_modules(STRUCTURAL, DEPGRAPH, all_files=ALL_FILES)
    b = mb.build_modules(STRUCTURAL, DEPGRAPH, all_files=list(reversed(ALL_FILES)))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert "generated_at" not in a


def test_all_files_source_label_and_no_degrade_error():
    """With a full listing, source is 'file_listing' and there is no depgraph-missing
    error even when depgraph is None (the listing covers everything)."""
    res = mb.build_modules(STRUCTURAL, None, all_files=ALL_FILES)
    assert all(m["source"] == "file_listing" for m in res["modules"])
    assert not res["errors"]


def test_module_file_universe_is_git_tracked_and_excluded(tmp_path):
    """KLC-074 review HIGH-1/HIGH-2: the module file universe is GIT-TRACKED intersected
    with the resolved scan excludes — untracked junk and tracked-but-excluded files are
    both dropped, and the result is sorted (byte-reproducible)."""
    import subprocess
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "m.py").write_text("x=1\n", encoding="utf-8")
    (root / "build").mkdir()                 # baseline-excluded dir
    (root / "build" / "gen.py").write_text("g=1\n", encoding="utf-8")
    (root / "untracked.py").write_text("u=1\n", encoding="utf-8")  # never git-added
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "pkg/m.py", "build/gen.py"],
                 ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)
    got, source = mb.module_file_universe(root)
    assert source.endswith("git"), source
    assert "pkg/m.py" in got
    assert "untracked.py" not in got, "untracked file leaked into the universe"
    assert "build/gen.py" not in got, "tracked-but-excluded file leaked in"
    assert got == sorted(got)


def test_empty_universe_produces_zero_modules_not_fallback():
    """KLC-074 review P2: an EMPTY-but-authoritative universe (``[]``) must yield ZERO
    modules — it must NOT be treated as 'absent' and fall back to the depgraph /
    directory_tree clustering (which would re-fabricate modules from untracked/excluded
    import-graph files, reopening HIGH-1). Distinguishes ``[]`` (legit empty) from
    ``None`` (no universe available)."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH, all_files=[])
    assert res["modules"] == [], (
        "empty universe fell back and fabricated modules: "
        f"{[m['name'] for m in res['modules']]}")


def test_none_universe_falls_back_to_depgraph():
    """The None sentinel (universe genuinely unavailable) still falls back to the
    depgraph clustering — only ``[]`` means 'zero modules'."""
    res = mb.build_modules(STRUCTURAL, DEPGRAPH, all_files=None)
    assert res["modules"], "None universe should fall back to depgraph clustering"


def test_module_file_universe_empty_git_repo_is_empty_list_not_none(tmp_path):
    """KLC-074 review P2: an initialised git repo with only UNTRACKED files has a
    legitimately empty authoritative universe → module_file_universe returns ``[]``
    (determinate), never None."""
    import subprocess
    root = tmp_path
    (root / "untracked.py").write_text("x=1\n", encoding="utf-8")  # never git-added
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)
    files, src = mb.module_file_universe(root)
    assert files == [], files
    assert files is not None
    assert src.endswith("git"), src


def test_module_file_universe_non_git_returns_none(tmp_path):
    """KLC-074 review P2: a non-git tree (no structural.files_rel, git unavailable) is a
    'cannot determine the authoritative git-tracked universe' case → returns None so the
    caller degrades to depgraph, rather than using a non-reproducible working-tree walk
    as the authoritative universe (HIGH-1)."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("x=1\n", encoding="utf-8")
    files, src = mb.module_file_universe(tmp_path)
    assert files is None, files


def test_all_files_intersects_universe_dropping_untracked_depgraph_nodes():
    """KLC-074 review: a code file present in the import graph but ABSENT from the
    tracked universe (untracked/excluded) must not create a module — build_modules
    intersects, it does not union depgraph nodes back in."""
    dg = {"import_graphs": {"python": {
        "nodes": [{"id": "pkg/keep.py"}, {"id": "build/leak.py"}], "edges": []}}}
    res = mb.build_modules(STRUCTURAL, dg, all_files=["pkg/keep.py"])
    names = {m["name"] for m in res["modules"]}
    assert "pkg" in names
    assert "build" not in names, "depgraph node outside the universe fabricated a module"
