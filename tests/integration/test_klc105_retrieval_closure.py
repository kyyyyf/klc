"""KLC-105 step-6 — a retrieval trace references only in-universe files (AC-11)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"
_init_script = _repo_root / "scripts" / "init.py"
sys.path.insert(0, str(_skills))
import planning_validate  # noqa: E402


def _load_retriever():
    spec = importlib.util.spec_from_file_location(
        "klc105_planning_retriever", _skills / "planning-retriever.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")


def _polluted_repo(tmp_path: Path) -> Path:
    root = tmp_path / "retrieval_fixture"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "widget.py").write_text(
        "def build_widget(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests" / "test_widget.py").write_text(
        "from pkg.widget import build_widget\n\n\n"
        "def test_build_widget():\n    assert build_widget(1, 2) == 3\n",
        encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")

    pollution = root / ".claude" / "worktrees" / "agent-x" / "pkg"
    pollution.mkdir(parents=True)
    (pollution / "widget.py").write_text(
        "def build_widget_pollution():\n    return 0\n", encoding="utf-8")
    return root


def _run_scan_only(root: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(_init_script), "--scan-only"],
        cwd=str(root), capture_output=True, text=True, timeout=120,
        env={**os.environ, "PROJECT_ROOT": str(root)},
    )
    assert r.returncode == 0, f"klc init --scan-only failed:\n{r.stdout}\n{r.stderr}"


def _load(p: Path) -> dict:
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def test_retrieval_trace_closure_over_universe(tmp_path):
    """AC-11: a freshly built retrieval trace references only in-universe files —
    files_to_read_first / files_likely_to_edit / tests_to_read_or_run contain no
    path outside files_rel, including no path under .claude/."""
    root = _polluted_repo(tmp_path)
    _run_scan_only(root)
    idx = root / ".klc" / "index"
    structural = _load(idx / "structural.json")
    universe = set(structural["files_rel"])

    retriever = _load_retriever()
    trace = retriever.build_trace(
        "build a widget", "deterministic",
        _load(idx / "modules.json"), _load(idx / "file_roles.json"),
        _load(idx / "module_edges.json"), _load(idx / "test_map.json"),
        _load(idx / "inventory.json"))

    for key in ("files_to_read_first", "files_likely_to_edit", "tests_to_read_or_run"):
        for f in trace.get(key) or []:
            assert f in universe, f"{key} references out-of-universe path: {f}"
            assert not f.startswith(".claude/")


def test_retrieval_closure_check_flags_injected_out_of_universe_ref(tmp_path):
    """Negative twin: inject a .claude/worktrees/... path into a copy of the built
    retrieval_trace.json's tests_to_read_or_run, run planning_validate.py's
    retrieval cross-check against it, assert the injected path is reported in
    warnings[] (exercises the existing retrieval_checked code path)."""
    root = _polluted_repo(tmp_path)
    _run_scan_only(root)
    idx = root / ".klc" / "index"

    retriever = _load_retriever()
    trace = retriever.build_trace(
        "build a widget", "deterministic",
        _load(idx / "modules.json"), _load(idx / "file_roles.json"),
        _load(idx / "module_edges.json"), _load(idx / "test_map.json"),
        _load(idx / "inventory.json"))

    injected = ".claude/worktrees/agent-x/pkg/widget.py"
    trace = dict(trace)
    trace["tests_to_read_or_run"] = list(trace.get("tests_to_read_or_run") or []) + [injected]

    report = planning_validate.validate(
        _load(idx / "modules.json"),
        file_roles=_load(idx / "file_roles.json"),
        retrieval=trace,
        inventory=_load(idx / "inventory.json"))

    assert report["counts"]["retrieval_checked"] is True
    assert any(injected in w for w in report["warnings"]), report["warnings"]
