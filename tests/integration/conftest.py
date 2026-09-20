"""tests/integration/conftest.py — KLC-109 step-8: the klc109_repo factory.

Materialises one of the `tests/fixtures/klc109-<lang>/` red→green fixture
repositories into a real, isolated git repo under `tmp_path` (D-102: committed
source trees + a conftest factory, not a committed nested `.git`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def klc109_repo(tmp_path):
    def _build(layout: str) -> Path:
        src = _FIXTURES / f"klc109-{layout}"
        plan = json.loads((src / "history.json").read_text(encoding="utf-8"))
        repo = tmp_path / layout
        shutil.copytree(src, repo, ignore=shutil.ignore_patterns("history.json"))
        _run(["git", "init"], repo)
        _run(["git", "config", "user.email", "test@test.com"], repo)
        _run(["git", "config", "user.name", "Test User"], repo)
        for phase in ("red", "green"):          # ORDER IS THE POINT OF THE FIXTURE
            for rel in plan[phase]:
                _run(["git", "add", rel], repo)
            _run(["git", "commit", "-m", f"KLC-109F step-1: {phase}"], repo)
        return repo
    return _build
