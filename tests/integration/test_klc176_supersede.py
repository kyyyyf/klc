"""KLC-176 step-3 (AC-5): supersede records the state commit instead of copying.

A tracked, unmodified output file is deleted inside the transaction and the
state repository HEAD from before the delete is recorded in meta.superseded[].
An untracked or locally modified file, or no usable git at all, keeps the legacy
`_superseded/<ts>/` move so nothing is ever lost.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW))
sys.path.insert(0, str(_FW / "core" / "skills"))

import lifecycle  # noqa: E402

KEY = "KLC-T176"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                       env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)})
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _project(tmp_path: Path, monkeypatch, *, git: bool = True) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = tmp_path / ".klc"
    tdir = klc / "tickets" / KEY
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps({"ticket": KEY, "phase": "review-lite:work"}),
                                    encoding="utf-8")
    (tdir / "review-lite-report.md").write_text("old report\n", encoding="utf-8")
    if git:
        _git(klc, "init", "-b", "klc-state")
        _git(klc, "config", "user.email", "t@example.com")
        _git(klc, "config", "user.name", "T")
        _git(klc, "config", "commit.gpgsign", "false")
        _git(klc, "add", "-A")
        _git(klc, "commit", "-m", "seed")
    return tdir


def test_supersede_deletes_tracked_files_and_records_commit(tmp_path, monkeypatch):
    tdir = _project(tmp_path, monkeypatch)
    head = _git(tmp_path / ".klc", "rev-parse", "HEAD")

    lifecycle.supersede_phases(KEY, ["review-lite"])

    assert not (tdir / "review-lite-report.md").exists()
    assert not (tdir / "_superseded").exists(), "no copy directory is created"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["superseded"] == [{"phase": "review-lite", "commit": head}]
    old = _git(tmp_path / ".klc", "show", f"{head}:tickets/{KEY}/review-lite-report.md")
    assert old == "old report"


def test_modified_or_untracked_file_uses_legacy_move(tmp_path, monkeypatch):
    tdir = _project(tmp_path, monkeypatch)
    (tdir / "review-lite-report.md").write_text("edited locally\n", encoding="utf-8")

    lifecycle.supersede_phases(KEY, ["review-lite"])

    moved = list((tdir / "_superseded").glob("*/review-lite/review-lite-report.md"))
    assert moved and moved[0].read_text(encoding="utf-8") == "edited locally\n"
    assert not (tdir / "review-lite-report.md").exists()


def test_untracked_file_uses_legacy_move(tmp_path, monkeypatch):
    tdir = _project(tmp_path, monkeypatch)
    _git(tmp_path / ".klc", "rm", "-q", "--cached", "--", f"tickets/{KEY}/review-lite-report.md")
    _git(tmp_path / ".klc", "commit", "-q", "-m", "untrack")

    lifecycle.supersede_phases(KEY, ["review-lite"])

    kept = list((tdir / "_superseded").glob("*/review-lite/review-lite-report.md"))
    assert kept and kept[0].read_text(encoding="utf-8") == "old report\n"


def test_git_unavailable_keeps_files(tmp_path, monkeypatch):
    tdir = _project(tmp_path, monkeypatch, git=False)

    lifecycle.supersede_phases(KEY, ["review-lite"])

    kept = list((tdir / "_superseded").glob("*/review-lite/review-lite-report.md"))
    assert kept and kept[0].read_text(encoding="utf-8") == "old report\n"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert all("commit" not in r for r in meta.get("superseded", []))
