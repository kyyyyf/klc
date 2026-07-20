"""KLC-070 step-4 — pipeline wiring of the planning views into init/update.

Real-substrate: builds a throwaway git repo, runs the actual scripts/init.py and
scripts/update.py with PROJECT_ROOT pointed at it, and asserts the views appear and
degrade correctly. Confirms AC-2 (scan-only builds inventory), AC-9 (dependency order
+ degrade), and AC-13 (module SET unchanged — modules_build stays unwired).
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


def test_module_set_unchanged(tmp_path):
    """AC-13: wiring must NOT swap modules.json to modules_build clustering — the
    module names/paths are untouched (only depends_on/depended_by are filled)."""
    root = _make_repo(tmp_path)
    assert _run(INIT, root, "--scan-only").returncode == 0
    idx = root / ".klc" / "index"
    # A file-stem module set, as the LLM decompose produces today.
    modules = {"modules": [
        {"name": "mod", "path": "pkg/mod", "files": ["pkg/mod.py"]},
        {"name": "pkg", "path": "pkg/", "files": ["pkg/mod.py"]},
    ]}
    before = {(m["name"], m["path"]) for m in modules["modules"]}
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")

    r = _run(UPDATE, root, "--force")
    assert r.returncode == 0, r.stderr

    after_raw = json.loads((idx / "modules.json").read_text(encoding="utf-8"))
    after = {(m["name"], m["path"]) for m in after_raw["modules"]}
    assert after == before, "module SET changed — modules_build must stay unwired"
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
