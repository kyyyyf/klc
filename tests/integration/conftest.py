"""tests/integration/conftest.py — KLC-109 step-8: the klc109_repo factory.

Materialises one of the `tests/fixtures/klc109-<lang>/` red→green fixture
repositories into a real, isolated git repo under `tmp_path` (D-102: committed
source trees + a conftest factory, not a committed nested `.git`).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS = _REPO_ROOT / "core" / "skills"


def _load_skill(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, str(_SKILLS / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def klc137_corpus_traces(fresh_index):
    """KLC-137 D-108: every stored ticket's `raw.md` query, rebuilt into a
    trace by the POST-ticket retriever against ONE `fresh_index` mirror —
    built once per session (never per-test, D-108's "no rebuilding the 132-
    trace sweep twice"). Read from `$KLC137_CORPUS_DIR` when set, else
    `<repo>/.klc/tickets` (read only, KLC-136 group (c)). Returns
    `{ticket_key: trace}`; fails with a named reason when no `raw.md` is
    found under the resolved corpus dir — never a silent empty skip."""
    if str(_SKILLS) not in sys.path:
        sys.path.insert(0, str(_SKILLS))
    pe = _load_skill("klc137_planning_eval_corpus", "planning-eval.py")

    corpus_dir = Path(os.environ.get("KLC137_CORPUS_DIR") or (_REPO_ROOT / ".klc" / "tickets"))
    ticket_dirs = sorted(p.parent for p in corpus_dir.glob("*/raw.md"))
    if not ticket_dirs:
        raise RuntimeError(
            f"klc137_corpus_traces: no raw.md found under {corpus_dir} — set "
            f"KLC137_CORPUS_DIR to a directory of ticket subdirs, each with a raw.md")

    traces: dict[str, dict] = {}
    for ticket_dir in ticket_dirs:
        trace = pe.rescore_trace(ticket_dir, fresh_index)
        if trace is not None:
            traces[ticket_dir.name] = trace
    return traces


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
