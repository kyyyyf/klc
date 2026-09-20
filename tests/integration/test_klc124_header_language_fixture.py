"""KLC-124 step-3 — AC-5: a repo holding one `.h` file and one `.cpp` file
reports exactly one language, `cpp`, with header symbols credited into that
same language's `inventory:cpp` coverage verdict.

Real substrate: the REAL `file_scanner.scan()` + `deterministic_inventory.
build_inventory()` production path, through the REAL ast-grep binary and the
REAL `generic` profile's merged ruleset (`core/rules/cpp/header-symbols.yaml`
+ `profiles/generic/sgconfig.yml`'s `.h -> cpp` languageGlobs override) —
mirrors `tests/integration/test_klc103_rule_coverage.py`'s own
`COV_FIXTURES`-driven pattern (COV_FIXTURES's `sample.h`/`sample.cpp`).
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FW_ROOT / "core" / "skills"
FIXTURES = FW_ROOT / "tests" / "fixtures" / "rules" / "coverage"

sys.path.insert(0, str(SKILLS))
import tools  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, FW_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def test_h_and_cpp_repo_reports_single_cpp_language(tmp_path, monkeypatch):
    """AC-5: `structural.json` reports exactly one language, `cpp`; the
    `.h` file's `class Widget` declaration is credited into `inventory:cpp`
    (no phantom, separately-tracked `c` entry)."""
    astgrep = _astgrep_or_skip()
    monkeypatch.chdir(tmp_path)
    shutil.copy(FIXTURES / "sample.h", tmp_path / "widget.h")
    shutil.copy(FIXTURES / "sample.cpp", tmp_path / "widget.cpp")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)

    fs = _load("fs_klc124_fixture", "core/skills/file_scanner.py")
    structural = fs.scan(tmp_path)
    assert set(structural["languages"]) == {"cpp"}, structural["languages"]

    di = _load("di_klc124_fixture", "core/skills/deterministic_inventory.py")
    ruleset = di.resolve_ruleset()
    files = ["widget.h", "widget.cpp"]
    inventory = di.build_inventory(tmp_path, ruleset, astgrep, files=files,
                                   structural=structural)
    assert inventory["errors"], inventory  # coverage verdicts land in errors[]
    cpp_verdict = next(e for e in inventory["errors"]
                       if isinstance(e, dict) and e.get("builder") == "inventory:cpp")
    assert cpp_verdict["observed"] >= 1, cpp_verdict
    assert not any(isinstance(e, dict) and e.get("builder") == "inventory:c"
                   for e in inventory["errors"]), inventory["errors"]
    widget_symbols = [s for s in inventory["symbols"] if s["file"] == "widget.h"]
    assert any(s["name"] == "Widget" for s in widget_symbols), widget_symbols
