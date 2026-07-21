"""KLC-070 step-4 — pipeline wiring of the planning views into init/update.

Real-substrate: builds a throwaway git repo, runs the actual scripts/init.py and
scripts/update.py with PROJECT_ROOT pointed at it, and asserts the views appear and
degrade correctly. Confirms AC-2 (scan-only builds inventory), AC-9 (dependency order
+ degrade), and — KLC-074 — that the module SET is now built DETERMINISTICALLY by
modules_build (superseding KLC-070 AC-13, which kept modules_build unwired).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent      # worktree root
INIT = REPO / "scripts" / "init.py"
UPDATE = REPO / "scripts" / "update.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(x):\n    return x\n", encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "from pkg.mod import public_fn\n\n"
        "def test_it():\n    assert public_fn(1) == 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _run(script: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PROJECT_ROOT=str(root))
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, env=env, timeout=600)


def test_scan_only_builds_inventory(tmp_path):
    """AC-2: `init --scan-only` produces inventory.json with no LLM agent."""
    root = _make_repo(tmp_path)
    r = _run(INIT, root, "--scan-only")
    assert r.returncode == 0, r.stderr
    inv_file = root / ".klc" / "index" / "inventory.json"
    assert inv_file.exists(), "inventory.json not built in scan-only"
    inv = json.loads(inv_file.read_text(encoding="utf-8"))
    assert any(s["name"] == "public_fn" for s in inv["symbols"])


def test_views_built_in_dependency_order(tmp_path):
    """AC-9: inventory (independent) and test_map are built even before modules.json
    exists; the pipeline still exits 0 (degrade, not fail)."""
    root = _make_repo(tmp_path)
    r = _run(INIT, root, "--scan-only")
    assert r.returncode == 0, r.stderr
    idx = root / ".klc" / "index"
    assert (idx / "inventory.json").exists()
    assert (idx / "test_map.json").exists()
    # module_edges needs modules.json (absent here) → it degrades and writes nothing,
    # but the pipeline did not fail.
    assert "INIT_SCAN_OK" in r.stdout


def test_missing_optional_input_degrades(tmp_path):
    """AC-9: with depgraph removed, the views still build and init exits 0."""
    root = _make_repo(tmp_path)
    assert _run(INIT, root, "--scan-only").returncode == 0
    # Drop the optional depgraph, then re-run the view builders via update.
    (root / ".klc" / "index" / "depgraph.json").unlink()
    r = _run(UPDATE, root, "--force")
    assert r.returncode == 0, r.stderr
    # inventory does not depend on depgraph — still present and populated.
    inv = json.loads((root / ".klc" / "index" / "inventory.json").read_text())
    assert inv["symbols"]


def test_scan_only_builds_modules_deterministically(tmp_path):
    """KLC-074: `init --scan-only` now builds modules.json deterministically (no LLM
    decompose). The module SET is directory-level (`pkg/`, `tests/`), byte-reproducible
    on re-run, and covers the non-code files too."""
    root = _make_repo(tmp_path)
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "docs")

    assert _run(INIT, root, "--scan-only").returncode == 0
    idx = root / ".klc" / "index"
    mods_file = idx / "modules.json"
    assert mods_file.exists(), "modules.json not built in scan-only"
    data = json.loads(mods_file.read_text(encoding="utf-8"))
    names = {m["name"] for m in data["modules"]}
    # directory-level modules, INCLUDING the non-code docs/ dir (KLC-074 anti-orphan).
    assert {"pkg", "tests", "docs"} <= names, names
    # no LLM-style file-stem module (e.g. pkg/mod) — membership is directory-level.
    assert "pkg/mod" not in names
    # byte-reproducible membership on a second run (generated_at is the only churn).
    first = mods_file.read_text(encoding="utf-8")
    assert _run(UPDATE, root, "--force").returncode == 0
    a = json.loads(first); b = json.loads(mods_file.read_text(encoding="utf-8"))
    a.pop("generated_at", None); b.pop("generated_at", None)
    # depends_on/depended_by are filled by the edge aggregator on both runs; compare
    # the membership (name→path→files) which must be identical.
    def membership(d):
        return sorted((m["name"], m["path"], tuple(m.get("files", [])))
                      for m in d["modules"])
    assert membership(a) == membership(b)


def test_module_universe_is_git_tracked(tmp_path):
    """KLC-074 review HIGH-1: the module SET must be built from the GIT-TRACKED file
    universe, not a raw working-tree walk. An untracked/gitignored file must NOT
    fabricate a module (two devs / CI-vs-local at the same HEAD would otherwise
    compute different module sets, violating AC-3 byte-reproducibility)."""
    root = _make_repo(tmp_path)
    # Untracked working-tree junk (never `git add`ed) + a gitignored dir.
    (root / "vendor_local").mkdir()
    (root / "vendor_local" / "thirdparty.js").write_text("x=1\n", encoding="utf-8")
    (root / "coverage").mkdir()
    (root / "coverage" / "report.py").write_text("y=1\n", encoding="utf-8")
    (root / ".gitignore").write_text("coverage/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-qm", "gitignore")

    assert _run(INIT, root, "--scan-only").returncode == 0
    data = json.loads((root / ".klc" / "index" / "modules.json").read_text())
    names = {m["name"] for m in data["modules"]}
    assert "vendor_local" not in names, "untracked file fabricated a module"
    assert "coverage" not in names, "gitignored file fabricated a module"
    # the tracked package is still a module
    assert "pkg" in names


def test_module_universe_honours_baseline_excludes_over_tracked(tmp_path):
    """KLC-074 review HIGH-2: even a TRACKED file under a scanner-excluded directory
    (baseline excludes, mirrored from file_scanner) must not create a module — the
    module universe is git-tracked INTERSECT the resolved scan excludes."""
    root = _make_repo(tmp_path)
    (root / "build").mkdir()                     # 'build' is a baseline exclude
    (root / "build" / "generated.py").write_text("z=1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "tracked-build-artifact")

    assert _run(INIT, root, "--scan-only").returncode == 0
    data = json.loads((root / ".klc" / "index" / "modules.json").read_text())
    names = {m["name"] for m in data["modules"]}
    assert "build" not in names, "tracked file under an excluded dir created a module"


def test_docgen_only_skips_non_code_module(tmp_path):
    """KLC-074 review P3: `module-writer --only <non-code-module>` renders NOTHING
    (parity with --all, which already skips non-code dirs), so `klc update --regen`
    never writes a CLAUDE.md into a stale docs/config-only module. A code module named
    via --only still renders (and a deterministic modules_build module — no
    language/public_api — renders without crashing under StrictUndefined)."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)
    # A deterministic modules_build-style set: directory modules, NO language/public_api.
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": "pkg", "path": "pkg/", "files": ["pkg/m.py"],
         "depends_on": [], "depended_by": []},
        {"name": "docs", "path": "docs/", "files": ["docs/guide.md"],
         "depends_on": [], "depended_by": []},
    ]}), encoding="utf-8")
    (idx / "inventory.json").write_text(json.dumps({
        "structural": {"languages": {}, "total_lines": 0, "total_files": 2},
        "symbols": [], "notes": []}), encoding="utf-8")

    writer = REPO / "core" / "skills" / "module-writer.py"
    env = dict(os.environ, PROJECT_ROOT=str(root))

    # --all: renders the code module (pkg) but NOT the non-code dir (docs), and must
    # not crash on the deterministic modules (no language/public_api).
    r_all = subprocess.run([sys.executable, str(writer), "--all"],
                           capture_output=True, text=True, env=env, timeout=120)
    assert r_all.returncode == 0, r_all.stderr
    assert (root / "pkg" / "CLAUDE.md").exists(), "code module not rendered by --all"
    assert not (root / "docs" / "CLAUDE.md").exists(), \
        "non-code module got a CLAUDE.md via --all"

    # --only docs (the `klc update --regen` path for a stale module): the non-code
    # module is skipped, nothing new is written, and it exits 0 (parity with --all).
    r_only = subprocess.run([sys.executable, str(writer), "--only", "docs"],
                            capture_output=True, text=True, env=env, timeout=120)
    assert r_only.returncode == 0, r_only.stderr
    assert "skipping non-code module 'docs'" in r_only.stderr
    assert not (root / "docs" / "CLAUDE.md").exists(), \
        "non-code module got a CLAUDE.md via --only"


def test_deterministic_build_overwrites_stale_llm_set(tmp_path):
    """KLC-074 migration: an existing LLM-style modules.json (file-stem modules) is
    REPLACED by the deterministic directory-level set on the next update — the
    cut-over migrates in place, it does not preserve the old LLM membership."""
    root = _make_repo(tmp_path)
    assert _run(INIT, root, "--scan-only").returncode == 0
    idx = root / ".klc" / "index"
    # Plant an LLM-style file-stem set (what decompose used to produce).
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": "mod", "path": "pkg/mod", "files": ["pkg/mod.py"]},
    ]}), encoding="utf-8")

    r = _run(UPDATE, root, "--force")
    assert r.returncode == 0, r.stderr

    after = json.loads((idx / "modules.json").read_text(encoding="utf-8"))
    names = {m["name"] for m in after["modules"]}
    assert "mod" not in names, "stale LLM file-stem module survived the cut-over"
    assert "pkg" in names, "deterministic directory module missing after cut-over"
    # And the detailed edges file now exists (modules.json was present).
    assert (idx / "module_edges.json").exists()


def test_update_refreshes_all_three_views(tmp_path):
    """AC-9: update.py refreshes inventory, test_map, and module_edges."""
    root = _make_repo(tmp_path)
    assert _run(INIT, root, "--scan-only").returncode == 0
    idx = root / ".klc" / "index"
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": "pkg", "path": "pkg/", "files": ["pkg/mod.py"]},
    ]}), encoding="utf-8")
    r = _run(UPDATE, root, "--force")
    assert r.returncode == 0, r.stderr
    for name in ("inventory.json", "test_map.json", "module_edges.json"):
        assert (idx / name).exists(), f"{name} missing after update"


def test_file_roles_and_symbol_usage_wired(tmp_path):
    """KLC-071 AC-7: file_roles and symbol_usage build after inventory in both init
    (scan-only) and update, degrade-not-fail (no callgraph → symbol_usage still
    written; here without modules.json file_roles still classifies from inventory)."""
    root = _make_repo(tmp_path)
    r = _run(INIT, root, "--scan-only")
    assert r.returncode == 0, r.stderr
    idx = root / ".klc" / "index"
    # file_roles needs only inventory (required) — built even without modules.json.
    fr = json.loads((idx / "file_roles.json").read_text(encoding="utf-8"))
    assert "pkg/mod.py" in fr["files"]
    assert fr["files"]["pkg/mod.py"]["eligible_as_primary"] is True
    # symbol_usage degrades to file-level import usage (no callgraph) but still exists.
    su = json.loads((idx / "symbol_usage.json").read_text(encoding="utf-8"))
    assert "pkg/mod.py::public_fn" in su["symbols"]
    tested = su["symbols"]["pkg/mod.py::public_fn"]["tested_by"]
    assert "tests/test_mod.py" in tested  # the test imports the defining file

    # update refreshes both too.
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": "pkg", "path": "pkg/", "files": ["pkg/mod.py"]},
    ]}), encoding="utf-8")
    assert _run(UPDATE, root, "--force").returncode == 0
    for name in ("file_roles.json", "symbol_usage.json"):
        assert (idx / name).exists(), f"{name} missing after update"
