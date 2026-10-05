#!/usr/bin/env python3
"""KLC-178 step-3 — `klc doctor --install <root>` / `--index`, and the
informational language-tool report (AC-7, AC-8, AC-9).

Everything runs against scratch roots under pytest's tmp_path; the real
project root and its `.klc/index` are never touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
KLC = FW / "scripts" / "klc"
sys.path.insert(0, str(FW / "core" / "phases"))
sys.path.insert(0, str(FW / "core" / "skills"))
import doctor  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _repo(tmp_path: Path, name: str = "proj") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "seed")
    return repo


def _snapshot(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts or not p.is_file():
            continue
        out[str(p.relative_to(root))] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(autouse=True)
def _no_ambient_root(monkeypatch):
    monkeypatch.delenv("PROJECT_ROOT", raising=False)


def test_install_twice_is_idempotent(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert doctor.run(["--install", str(repo)]) == 0
    assert (repo / ".klc" / "bin" / "klc").exists()
    # state init ran: .klc is now the klc-state worktree
    assert (repo / ".klc" / ".git").exists()
    capsys.readouterr()

    before = _snapshot(repo / ".klc")
    assert doctor.run(["--install", str(repo)]) == 0
    out = capsys.readouterr()
    assert "already installed" in (out.out + out.err).lower()
    assert _snapshot(repo / ".klc") == before


def test_install_skips_state_init_when_root_is_not_a_git_repo(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    assert doctor.run(["--install", str(root)]) == 0
    assert (root / ".klc" / "bin" / "klc").exists()
    assert not (root / ".klc" / ".git").exists()


def test_install_stops_when_bootstrap_check_fails(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(doctor, "_has_jinja2", lambda: False)
    monkeypatch.setattr(doctor, "_bootstrap_check", lambda: 1)
    assert doctor.run(["--install", str(repo)]) == 1
    assert not (repo / ".klc").exists()


def _fake_indexer(calls, *, advance: bool):
    def fake(cmd, *a, **kw):
        calls.append([Path(cmd[1]).name, *cmd[2:]])
        root = Path(kw["env"]["PROJECT_ROOT"])
        if advance:
            idx = root / ".klc" / "index"
            idx.mkdir(parents=True, exist_ok=True)
            (idx / ".last-run").write_text(_git(root, "rev-parse", "HEAD") + "\n",
                                           encoding="utf-8")
        return 0
    return fake


def test_index_fresh_vs_stale(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)

    # no .last-run -> full scan; the (fake) run leaves a fresh baseline
    calls: list = []
    monkeypatch.setattr(doctor.subprocess, "call", _fake_indexer(calls, advance=True))
    monkeypatch.setenv("PROJECT_ROOT", str(repo))
    assert doctor.refresh_index(repo) == 0
    assert calls == [["init.py", "--scan-only"]]
    assert "fresh" in capsys.readouterr().out

    # .last-run present -> update; a run that does not move the baseline is stale
    sha = _git(repo, "rev-parse", "HEAD")
    (repo / "b.txt").write_text("y", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "second")
    calls.clear()
    monkeypatch.setattr(doctor.subprocess, "call", _fake_indexer(calls, advance=False))
    assert doctor.refresh_index(repo) == 1
    assert calls == [["update.py"]]
    out = capsys.readouterr().out
    assert f"stale: HEAD moved since {sha[:8]}" in out


def test_missing_language_server_is_informational_even_strict(tmp_path):
    repo = _repo(tmp_path)
    idx = repo / ".klc" / "index"
    idx.mkdir(parents=True)
    (idx / "project-deps.json").write_text(json.dumps({
        "languages": ["python"],
        "required": {"python": ["pylsp"]},
        "optional": {},
        "detected": {"pylsp": None},
    }), encoding="utf-8")
    env = {**os.environ, "PROJECT_ROOT": str(repo)}
    for extra in ([], ["--strict"]):
        r = subprocess.run([sys.executable, str(KLC), "doctor", "--json", *extra],
                           cwd=str(repo), env=env, capture_output=True, text=True,
                           timeout=120)
        entry = {c["check"]: c for c in json.loads(r.stdout)["checks"]}["project-tools"]
        assert entry["ok"] is True and not entry.get("warn")
        assert "pylsp" in " ".join(entry["errors"])  # printed, as information


def test_project_deps_absent_is_informational_even_strict(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".klc" / "index").mkdir(parents=True)
    env = {**os.environ, "PROJECT_ROOT": str(repo)}
    r = subprocess.run([sys.executable, str(KLC), "doctor", "--json", "--strict"],
                       cwd=str(repo), env=env, capture_output=True, text=True,
                       timeout=120)
    entry = {c["check"]: c for c in json.loads(r.stdout)["checks"]}["project-tools"]
    assert entry["ok"] is True and not entry.get("warn")


def test_install_force_reruns_install_on_installed_root(tmp_path, monkeypatch, capsys):
    """Operator addition: `--install <root> --force` regenerates even when the
    root is already installed, so the index-hook repair hint really repairs."""
    repo = _repo(tmp_path)
    assert doctor.run(["--install", str(repo)]) == 0
    capsys.readouterr()

    import install as _install
    calls = []
    real = _install.run
    monkeypatch.setattr(_install, "run", lambda argv: (calls.append(list(argv)), real(argv))[1])

    assert doctor.run(["--install", str(repo)]) == 0
    assert calls == []                      # plain re-run still a no-op
    assert doctor.run(["--install", str(repo), "--force"]) == 0
    assert calls == [[str(repo), "--force"]]


def test_hook_repair_hint_uses_install_force(tmp_path):
    import index_health
    errs, _sev = index_health.hook(tmp_path, None, None)
    assert f"klc doctor --install {tmp_path} --force" in errs[0]


def test_index_refresh_no_baseline_hint_names_doctor_index(tmp_path, monkeypatch):
    monkeypatch.delenv("KLC_NO_INDEX_REFRESH", raising=False)
    import io
    import index_refresh
    (tmp_path / ".klc" / "index").mkdir(parents=True)
    buf = io.StringIO()
    res = index_refresh.refresh_if_stale(tmp_path, out=buf)
    assert res["status"] == "uninitialised"
    assert "klc doctor --index" in buf.getvalue()
    assert "klc init" not in buf.getvalue()


# ---- review round 1 (step-6) ------------------------------------------------

def test_first_install_records_project_deps_after_one_run(tmp_path):
    """R2-001: ONE `doctor --install <root>` on a fresh root scans first, so
    setup sees structural.json and writes project-deps.json."""
    repo = _repo(tmp_path)
    for i in range(10):  # detect_languages needs >=10 files per language
        (repo / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "py")
    assert doctor.run(["--install", str(repo)]) == 0
    assert (repo / ".klc" / "index" / "structural.json").exists()
    assert (repo / ".klc" / "index" / "project-deps.json").exists()
    assert "PROJECT_ROOT" not in os.environ  # restored


def test_install_with_index_scans_once(tmp_path, monkeypatch):
    """R2-001: `--install X --index` does not scan twice on a fresh root."""
    repo = _repo(tmp_path)
    calls = []
    monkeypatch.setattr(doctor, "refresh_index",
                        lambda root, scan=True: (calls.append((root, scan)), 0)[1])
    assert doctor.run(["--install", str(repo), "--index"]) == 0
    assert [c for c in calls if c[1]] == [(repo.resolve(), True)]  # one real scan
    assert calls[-1] == (repo.resolve(), False)  # --index only reports the verdict


def test_install_with_index_indexes_the_installed_root(tmp_path, monkeypatch):
    """F-004: `--install X --index` refreshes X, not the caller's root."""
    other = tmp_path / "other"
    other.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setenv("PROJECT_ROOT", str(other))
    got = []
    monkeypatch.setattr(doctor, "install_project", lambda root, force=False: 0)
    monkeypatch.setattr(doctor, "refresh_index", lambda root, scan=True: (got.append(root), 0)[1])
    assert doctor.run(["--install", str(target), "--index"]) == 0
    assert got == [target.resolve()]


@pytest.mark.parametrize("argv", [
    ["--force"],
    ["--force", "--index"],
    ["--json", "--install", "X"],
    ["--json", "--index"],
])
def test_invalid_flag_combinations_are_usage_errors(tmp_path, monkeypatch, capsys, argv):
    """F-004: combinations that would be silently ignored are argparse errors."""
    argv = [str(tmp_path) if a == "X" else a for a in argv]
    monkeypatch.setattr(doctor, "install_project", lambda *a, **k: pytest.fail("ran"))
    monkeypatch.setattr(doctor, "refresh_index", lambda *a, **k: pytest.fail("ran"))
    with pytest.raises(SystemExit) as e:
        doctor.run(argv)
    assert e.value.code == 2
    assert capsys.readouterr().err.strip()


def _doctor_json(capsys, *argv):
    doctor.run(["--json", *argv])
    return {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}


def _path_with(tmp_path, monkeypatch, *, ast_grep: bool):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if ast_grep:
        exe = bindir / "ast-grep"
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
    base = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if d and not (Path(d) / "ast-grep").exists() and not (Path(d) / "sg").exists()]
    monkeypatch.setenv("PATH", os.pathsep.join([str(bindir), *base]))


def test_ast_grep_missing_warns_and_fails_under_strict(tmp_path, monkeypatch, capsys):
    """F-010: the indexer needs ast-grep, so doctor checks for it."""
    repo = _repo(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(repo))
    _path_with(tmp_path, monkeypatch, ast_grep=False)
    entry = _doctor_json(capsys)["ast-grep"]
    assert entry["ok"] is True and entry.get("warn") is True
    assert "ast-grep" in " ".join(entry["errors"])
    entry = _doctor_json(capsys, "--strict")["ast-grep"]
    assert entry["ok"] is False


def test_ast_grep_present_passes(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(repo))
    _path_with(tmp_path, monkeypatch, ast_grep=True)
    entry = _doctor_json(capsys, "--strict")["ast-grep"]
    assert entry["ok"] is True and not entry.get("warn") and entry["errors"] == []


def test_init_and_update_pointers_are_honest_about_agent_passes(tmp_path):
    """F-002: the doc-generation passes doctor does not do stay reachable, and the
    deprecation pointer says where."""
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    for verb, flag in (("init", "--finalize"), ("update", "--regen")):
        r = subprocess.run([sys.executable, str(KLC), verb, "--help"], env=env,
                           capture_output=True, text=True, timeout=60)
        assert f"klc internal {verb} {flag}" in r.stderr, r.stderr
        r = subprocess.run([sys.executable, str(KLC), "internal", verb, "--help"], env=env,
                           capture_output=True, text=True, timeout=60)
        assert "deprecated" not in r.stderr and "usage: klc internal" not in r.stderr, r.stderr
        assert r.returncode == 0, r.stderr


def test_install_next_steps_teach_the_new_verbs(tmp_path, capsys):
    """F-006: install.run's next steps no longer send the operator to `init`."""
    import install as _install
    root = tmp_path / "p"
    root.mkdir()
    assert _install.run([str(root)]) == 0
    out = capsys.readouterr().out
    assert "<shim> init" not in out and "klc doctor --index" in out
    shim = (root / ".klc" / "bin" / "klc").read_text(encoding="utf-8")
    assert "klc install" not in shim and "klc doctor --install <project> --force" in shim
