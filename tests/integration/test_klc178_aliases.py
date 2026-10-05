"""KLC-178 step-2 — AC-6: `klc retrack` / `klc scope-fix` are hidden aliases of `klc fix`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
KLC = FW / "scripts" / "klc"


def _klc(argv, root: Path):
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    env.pop("KLC_TICKETS_DIR", None)
    p = subprocess.run([sys.executable, str(KLC), *argv], capture_output=True,
                       text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def _ticket(root: Path, key: str, phase: str, track: str = "L") -> Path:
    td = root / ".klc" / "tickets" / key
    td.mkdir(parents=True)
    meta = {"ticket": key, "kind": "tech", "phase": phase, "track": track,
            "phase_history": [], "affected_modules": ["a", "b"],
            "created": "2026-01-01T00:00:00Z"}
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return td / "meta.json"


def test_retrack_and_scope_fix_delegate_print_pointer_and_stay_hidden(tmp_path):
    mp = _ticket(tmp_path, "T-AL-1", "discovery:work")

    rc, out, err = _klc(["retrack", "T-AL-1", "M", "--reason", "too big"], tmp_path)
    assert rc == 0, err
    dep = [l for l in err.splitlines() if "deprecated" in l]
    assert len(dep) == 1 and "klc fix <KEY> track <TRACK> --reason" in dep[0]
    meta = json.loads(mp.read_text())
    assert meta["track"] == "M" and meta["track_source"] == "operator"
    assert meta["fixes"][-1]["field"] == "track" and meta["fixes"][-1]["reason"] == "too big"

    rc, out, err = _klc(["scope-fix", "T-AL-1", "--add", "c", "--reason", "widen"], tmp_path)
    assert rc == 0, err
    dep = [l for l in err.splitlines() if "deprecated" in l]
    assert len(dep) == 1 and "klc fix <KEY> modules" in dep[0]
    meta = json.loads(mp.read_text())
    assert meta["affected_modules"] == ["a", "b", "c"]
    assert meta["fixes"][-1]["field"] == "modules"

    # no archived-only gate any more: the ticket above is live (discovery)
    rc, out, err = _klc(["scope-fix", "T-AL-1", "--remove", "c", "--reason", "back"], tmp_path)
    assert rc == 0 and json.loads(mp.read_text())["affected_modules"] == ["a", "b"]

    rc, out, err = _klc(["--help"], tmp_path)
    assert rc == 0 and "retrack" not in out and "scope-fix" not in out


# --- step-4 / AC-10: bootstrap verbs are hidden aliases of doctor -------------

import pytest  # noqa: E402

_BOOT_POINTERS = {
    "install": "klc install is deprecated: use klc doctor --install <root>",
    "init": "klc init is deprecated: use klc doctor --index (agent doc passes: klc internal init --auto, klc internal init --finalize)",
    "update": "klc update is deprecated: use klc doctor --index (doc regeneration: klc internal update --regen)",
    "setup": "klc setup is deprecated: use klc doctor",
    "state": "klc state init is deprecated: use klc doctor --install <root>",
}


def _git_repo(root: Path) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (root / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    for a in (["init", "-q"], ["add", "a.py"], ["commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=env)


def _pointer_lines(err: str):
    return [l for l in err.splitlines() if "deprecated" in l]


def test_bootstrap_verbs_print_pointer_and_still_work(tmp_path):
    # install: pointer once, old work done
    proj = tmp_path / "proj"
    proj.mkdir()
    rc, out, err = _klc(["install", str(proj)], tmp_path)
    assert _pointer_lines(err) == [_BOOT_POINTERS["install"]], err
    assert rc == 0, err
    assert (proj / ".klc" / "bin" / "klc").exists()

    # init --scan-only and update: pointer once, index built
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo)
    rc, out, err = _klc(["init", "--scan-only"], repo)
    assert _pointer_lines(err) == [_BOOT_POINTERS["init"]], err
    assert rc == 0, err
    assert (repo / ".klc" / "index" / ".last-run").exists()
    rc, out, err = _klc(["update"], repo)
    assert _pointer_lines(err) == [_BOOT_POINTERS["update"]], err

    # setup: pointer once, the verb still runs (no "unknown subcommand")
    rc, out, err = _klc(["setup"], repo)
    assert _pointer_lines(err) == [_BOOT_POINTERS["setup"]], err
    assert "unknown subcommand" not in err

    # state init outside a git repo: pointer once, the old refusal is unchanged
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, out, err = _klc(["state", "init"], plain)
    assert _pointer_lines(err) == [_BOOT_POINTERS["state"]], err
    assert rc != 0 and "not inside a git repository" in err


def test_bootstrap_verbs_hidden_from_help_and_operational_table(tmp_path):
    rc, out, err = _klc(["--help"], tmp_path)
    assert rc == 0
    also = [l for l in out.splitlines() if l.strip().startswith("Also:")]
    assert len(also) == 1
    for verb in ("install", "init", "update", "setup"):
        assert verb not in also[0], verb
    assert "state" not in also[0]
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("klc_disp_s4", str(KLC))
    spec = importlib.util.spec_from_loader("klc_disp_s4", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    for verb in ("install", "init", "update", "setup", "state"):
        assert verb not in mod.OPERATIONAL_CMDS, verb
    assert set(mod._DEPRECATED_BOOTSTRAP) == {"install", "init", "update", "setup", "state"}
