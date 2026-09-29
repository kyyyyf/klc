"""KLC-139 step-6 — the hermetic proof (AC-2).

`klc skeleton` (in-process or subprocess, Python or non-Python, an outline
or a refusal) leaves the project tree, its `.klc/` and its own temp
directory exactly as it found them. Every case points `TMPDIR` (and
`tempfile.tempdir`) at a fresh per-test directory and snapshots every path
under `tmp_path` before and after.

A directory's snapshot is `(type, mode)` only — never its mtime — because
creating and removing the engine's `TemporaryDirectory` inside `TMPDIR`
legitimately bumps `TMPDIR`'s own mtime (impl-plan review F-1; the KLC-136
D-204 rule: a directory's identity, not its timestamp). A file's snapshot
adds size, mtime_ns and mode, so a same-size rewrite or a chmod-only change
is still caught. The KLC-136 live guard (`tests/conftest.py`) is active for
every case here too.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
KLC = REPO / "scripts" / "klc"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402


def _snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        st = p.lstat()
        if stat.S_ISDIR(st.st_mode):
            out[rel] = ("dir", stat.S_IMODE(st.st_mode))
        else:
            out[rel] = ("file", st.st_size, st.st_mtime_ns, stat.S_IMODE(st.st_mode))
    return out


def _prep(tmp_path: Path, monkeypatch) -> Path:
    """PROJECT_ROOT, a fresh TMPDIR (env + `tempfile.tempdir`), and an empty
    `.klc/config` — the fixture every case needs before its own file."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp_dir))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_dir))
    (tmp_path / ".klc" / "config").mkdir(parents=True)
    return tmp_dir


def _fixture(tmp_path: Path, lang: str) -> Path:
    if lang == "python":
        f = tmp_path / "f.py"
        f.write_text("def f():\n    pass\n", encoding="utf-8")
    else:
        f = tmp_path / "f.ts"
        f.write_text("export function f() {}\n", encoding="utf-8")
    return f


@pytest.mark.parametrize(
    "lang,mode",
    [("python", "inprocess"), ("python", "subprocess"),
     ("nonpython", "inprocess"), ("nonpython", "subprocess")],
)
def test_skeleton_leaves_tree_and_tmp_untouched(tmp_path, monkeypatch, lang, mode):
    """AC-2: an outline call leaves `tmp_path` (project tree + .klc + tmp)
    exactly as it found it."""
    tmp_dir = _prep(tmp_path, monkeypatch)
    fixture = _fixture(tmp_path, lang)
    before = _snapshot(tmp_path)

    if mode == "inprocess":
        result = sk.skeleton(str(fixture))
        assert not result.refused
    else:
        proc = subprocess.run(
            [sys.executable, str(KLC), "skeleton", str(fixture)],
            env={**os.environ, "PROJECT_ROOT": str(tmp_path),
                 "TMPDIR": str(tmp_dir), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr

    after = _snapshot(tmp_path)
    assert before == after
    assert list(tmp_dir.iterdir()) == []


@pytest.mark.parametrize("case", ["broken-ts", "broken-py"])
def test_skeleton_refusal_leaves_tmp_untouched(tmp_path, monkeypatch, case):
    """AC-2: a refusal (the `broken-ts` case raises INSIDE the ast-grep
    engine's `TemporaryDirectory` block) still leaves everything untouched."""
    tmp_dir = _prep(tmp_path, monkeypatch)
    if case == "broken-ts":
        fixture = tmp_path / "broken.ts"
        fixture.write_text("export function broken( {\n", encoding="utf-8")
    else:
        fixture = tmp_path / "broken.py"
        fixture.write_text("def f(:\n", encoding="utf-8")

    before = _snapshot(tmp_path)
    result = sk.skeleton(str(fixture))
    assert result.refused
    after = _snapshot(tmp_path)
    assert before == after
    assert list(tmp_dir.iterdir()) == []
