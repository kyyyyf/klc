"""KLC-175 step-1 (AC-1): `scripts/review.py --diff` takes `A..B`, `A...B` and
the literal `recorded` (the ticket's `meta.pre_merge_range`) besides a file or
one ref. Real temp git repos and the real `review.py` subprocess; an
unresolvable end exits 2 and names the bad end (fail closed)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_plan  # noqa: E402

from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone, _branch_with_commits, _git, _rev_parse, _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]
REVIEW = FW_ROOT / "scripts" / "review.py"


def _setup(tmp_path: Path, ticket: str, with_range: bool = True):
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch=f"feature/{ticket.lower()}-w")
    head = _rev_parse(clone, "HEAD")
    kw = {}
    if with_range:
        kw["pre_merge_range"] = {"base": base, "head": head,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"}
    tdir = _seed_ticket(clone, ticket, phase="build:work", track="M",
                        affected_modules=["widgets"], modules=_MODULES, **kw)
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return clone, tdir, base, head


def _review(clone: Path, tdir: Path, diff: str, monkeypatch):
    import os
    env = {**os.environ, "PROJECT_ROOT": str(clone)}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        env.pop(k, None)
    return subprocess.run([sys.executable, str(REVIEW), "--plan-only", "--diff", diff,
                           "--spec", str(tdir / "spec.md")],
                          cwd=str(clone), capture_output=True, text=True, env=env, timeout=120)


def _plan(tdir: Path) -> dict:
    return json.loads((tdir / "review" / "review-plan-r1.json").read_text(encoding="utf-8"))


def test_range_and_recorded_resolve(tmp_path, monkeypatch):
    ticket = "KLC-975"
    clone, tdir, base, head = _setup(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    expected = review_plan.diff_sha_for_ticket(ticket)
    assert expected == hashlib.sha256(
        subprocess.run(["git", "diff", base, head], cwd=str(clone),
                       capture_output=True).stdout).hexdigest()
    for arg in (f"{base}..{head}", f"{base}...{head}", "recorded"):
        for old in (tdir / "review").glob("review-plan-r*.json"):
            old.unlink()
        r = _review(clone, tdir, arg, monkeypatch)
        assert r.returncode == 0, (arg, r.stderr)
        assert _plan(tdir)["diff_sha256"] == expected, arg


def test_unresolvable_range_is_refused(tmp_path, monkeypatch):
    ticket = "KLC-976"
    clone, tdir, base, head = _setup(tmp_path, ticket)
    r = _review(clone, tdir, f"{base}..nosuchref0", monkeypatch)
    assert r.returncode == 2
    assert "end 'nosuchref0' does not resolve" in r.stderr
    r = _review(clone, tdir, f"nosuchref1...{head}", monkeypatch)
    assert r.returncode == 2
    assert "end 'nosuchref1' does not resolve" in r.stderr
    # `recorded` with no pre_merge_range fails closed
    ticket2 = "KLC-977"
    clone2, tdir2, _b, _h = _setup(tmp_path / "second", ticket2, with_range=False)
    r = _review(clone2, tdir2, "recorded", monkeypatch)
    assert r.returncode == 2
    assert "pre_merge_range" in r.stderr
