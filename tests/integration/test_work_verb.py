#!/usr/bin/env python3
"""KLC-047 — `klc work <KEY>` read-only next-action verb.

`klc work` answers "what is the single next thing to do on this ticket?" It is
purely read-only: it derives the current `<phase>:<state>` from meta.json (via
`lifecycle.read_meta_ro`, never `current_state`, so a legacy-phase ticket is not
dirtied — DRIFT-1) plus `phases.yml`, and prints the prompt-card path, the
expected outputs, and a verify command. It NEVER mutates meta.

These tests roll their own tmp meta fixtures (no shared factory exists) — the
inline `_meta()` mirrors tests/integration/test_klc061_wrap_verbs.py.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_KLC = _FW_ROOT / "scripts" / "klc"
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import work as work_mod  # noqa: E402


# --- fixtures ---------------------------------------------------------------- #

def _meta(ticket: str, *, phase: str, track: str, **extra) -> dict:
    meta = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    return meta


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "S",
          **extra) -> Path:
    """Write a plain `.klc/tickets/<ticket>/meta.json` under tmp_path and return
    the meta.json path. Feature detection (git) stays OFF (plain dir)."""
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    mp = tdir / "meta.json"
    mp.write_text(
        json.dumps(_meta(ticket, phase=phase, track=track, **extra), indent=2)
        + "\n", encoding="utf-8")
    return mp


def _run(argv) -> tuple[int, str]:
    """Run work.run(argv), capturing combined stdout+stderr. Returns (rc, out)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = int(work_mod.run(list(argv)))
    return rc, buf.getvalue()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- AC-1: :work prints phase + card + outputs ------------------------------- #

def test_work_build_state(tmp_path, monkeypatch):
    """AC-1: at `build:work`, `work --json` reports the build STEP card path for
    the current impl_step (not step 1) and the phase outputs (`build-log.md`)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-900", phase="build:work", track="S", impl_step=3)

    rc, out = _run(["KLC-900", "--json"])
    assert rc == 0, out
    info = json.loads(out)
    assert info["phase"] == "build"
    assert info["state"] == "work"
    assert info["prompt"] == ".klc/tickets/KLC-900/build/_prompt_step_3.md", \
        f"build must point at the per-step card for impl_step, got {info['prompt']!r}"
    assert "_prompt_step_1.md" not in info["prompt"], \
        "must be the CURRENT step card, not step 1"
    assert "build-log.md" in info["outputs"]


def test_work_build_state_defaults_step_1(tmp_path, monkeypatch):
    """AC-1 edge: a build:work ticket with no impl_step yet defaults to step 1."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-901", phase="build:work", track="S")

    rc, out = _run(["KLC-901", "--json"])
    assert rc == 0, out
    info = json.loads(out)
    assert info["prompt"] == ".klc/tickets/KLC-901/build/_prompt_step_1.md"


def test_work_nonbuild_work_flat_card(tmp_path, monkeypatch):
    """AC-1: a non-build `:work` phase points at the flat `<phase>/_prompt.md`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-902", phase="design:work", track="M")

    rc, out = _run(["KLC-902", "--json"])
    assert rc == 0, out
    info = json.loads(out)
    assert info["prompt"] == ".klc/tickets/KLC-902/design/_prompt.md"
    # design's outputs come from phases.yml, not hard-coded.
    assert "impl-plan.md" in info["outputs"]


def test_work_human_output_has_phase_and_card(tmp_path, monkeypatch):
    """AC-1: the human (non-json) render names the phase and the card path."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-903", phase="build:work", track="S", impl_step=2)

    rc, out = _run(["KLC-903"])
    assert rc == 0, out
    assert "build:work" in out
    assert ".klc/tickets/KLC-903/build/_prompt_step_2.md" in out
    assert "build-log.md" in out


# --- AC-2: :ack-needed picks; :ack -> klc next ------------------------------- #

def test_work_ack_needed(tmp_path, monkeypatch):
    """AC-2: at `:ack-needed` the available `klc ack --pick` picks are listed."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-904", phase="design:ack-needed", track="M")

    rc, out = _run(["KLC-904", "--json"])
    assert rc == 0, out
    info = json.loads(out)
    assert info["state"] == "ack-needed"
    labels = [lbl for _pid, lbl in info["picks"]]
    assert "option-A-minimal" in labels, f"design picks missing: {info['picks']}"
    # human render lists the picks with their numbers.
    rc2, human = _run(["KLC-904"])
    assert "option-A-minimal" in human
    assert "ack" in human.lower()


def test_work_ack(tmp_path, monkeypatch):
    """AC-2: at `:ack` the output names `klc next`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-905", phase="build:ack", track="S")

    rc, out = _run(["KLC-905", "--json"])
    assert rc == 0, out
    info = json.loads(out)
    assert info["state"] == "ack"
    assert info["next"] == "klc next KLC-905"
    rc2, human = _run(["KLC-905"])
    assert "klc next KLC-905" in human


# --- AC-3: verify command ---------------------------------------------------- #

def test_work_verify_command(tmp_path, monkeypatch):
    """AC-3: build's verify command is the pytest sweep; a non-build phase gets a
    natural check. The verify command is always present at `:work`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-906", phase="build:work", track="S", impl_step=1)
    rc, out = _run(["KLC-906", "--json"])
    info = json.loads(out)
    assert info["verify"] == "python3 -m pytest tests/ -q --ignore=tests/fixtures"

    _seed(tmp_path, "KLC-907", phase="design:work", track="M")
    rc2, out2 = _run(["KLC-907", "--json"])
    info2 = json.loads(out2)
    assert info2["verify"] == "klc status KLC-907"
    assert info2["verify"]  # present


# --- AC-4: read-only + friendly errors --------------------------------------- #

def test_work_read_only_meta_unchanged(tmp_path, monkeypatch):
    """AC-4 / regression: `work` never mutates meta.json (sha before == after)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-908", phase="build:work", track="S", impl_step=1)
    before = _sha(mp)
    for argv in (["KLC-908"], ["KLC-908", "--json"]):
        rc, out = _run(argv)
        assert rc == 0, out
    assert _sha(mp) == before, "work must not mutate meta.json"


def test_work_read_only_legacy_phase_not_migrated(tmp_path, monkeypatch):
    """AC-4 / DRIFT-1: a legacy-format phase must NOT be migrated to disk. Using
    read_meta_ro (not current_state) keeps the file byte-identical even when the
    phase string is a legacy value that read_meta would rewrite."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # legacy phase form (no colon) — read_meta(persist_migration=True) rewrites it.
    mp = _seed(tmp_path, "KLC-909", phase="build-pending", track="S")
    before = _sha(mp)
    rc, out = _run(["KLC-909"])
    assert rc == 0, out
    # legacy "build-pending" migrates to "build:work" IN MEMORY; file stays put.
    assert "build:work" in out
    assert _sha(mp) == before, "read-only work must not persist a legacy migration"


def test_work_read_only_legacy_phase_not_migrated_json(tmp_path, monkeypatch):
    """FIX-3 / AC-4: the `--json` entry point must also leave a legacy-phase
    meta.json byte-identical — the read-only guarantee holds on both paths."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-911", phase="build-pending", track="S")
    before = _sha(mp)
    rc, out = _run(["KLC-911", "--json"])
    assert rc == 0, out
    info = json.loads(out)
    assert info["phase"] == "build" and info["state"] == "work"
    assert _sha(mp) == before, "read-only --json must not persist a legacy migration"


def test_work_corrupt_phase(tmp_path, monkeypatch):
    """FIX-2 / AC-4: an unparseable phase (no colon) or an unknown phase id must
    fail cleanly — non-zero exit, friendly stderr, NO traceback — on both the
    human and --json paths, mirroring status.py."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-912", phase="garbage-no-colon", track="S")
    before = _sha(mp)
    for argv in (["KLC-912"], ["KLC-912", "--json"]):
        rc, out = _run(argv)
        assert rc != 0, f"corrupt phase must exit non-zero for {argv}: {out}"
        assert "traceback" not in out.lower(), f"no traceback may leak:\n{out}"
        assert "KLC-912" in out
    assert _sha(mp) == before, "a corrupt-phase report must not mutate meta"

    # A well-formed-but-unknown phase id (by_id KeyError) is handled too.
    _seed(tmp_path, "KLC-913", phase="nope:work", track="S")
    rc2, out2 = _run(["KLC-913"])
    assert rc2 != 0, out2
    assert "traceback" not in out2.lower(), out2


def test_work_unknown_ticket(tmp_path, monkeypatch):
    """AC-4: an unknown ticket exits non-zero with a friendly message and writes
    no meta (the ticket dir is never created)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    rc, out = _run(["KLC-999"])
    assert rc != 0, "unknown ticket must exit non-zero"
    assert "KLC-999" in out
    assert "traceback" not in out.lower()
    assert not (tmp_path / ".klc" / "tickets" / "KLC-999").exists(), \
        "unknown ticket must not create any meta"


def test_work_archived(tmp_path, monkeypatch):
    """AC-4: an archived ticket reports the archived marker, exit 0, no meta write."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-910", phase="archived", track="S")
    before = _sha(mp)
    rc, out = _run(["KLC-910"])
    assert rc == 0, out
    assert "archived" in out.lower()
    assert _sha(mp) == before, "archived report must not mutate meta"
    rc2, jout = _run(["KLC-910", "--json"])
    assert rc2 == 0
    info = json.loads(jout)
    assert info["phase"] == "archived"


# --- AC-5: registered + shown in --help -------------------------------------- #

def test_work_in_help():
    """AC-5: `work` appears in `klc --help` (rendered from the module docstring,
    so registration in LIFECYCLE_CMDS alone is insufficient)."""
    r = subprocess.run(
        [sys.executable, str(_KLC), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "work" in r.stdout, f"--help must list `work`:\n{r.stdout}"


def test_work_registered(tmp_path):
    """AC-5: `klc work <KEY>` routes via the dispatcher (not 'unknown subcommand'
    / 'not implemented')."""
    r = subprocess.run(
        [sys.executable, str(_KLC), "work", "KLC-NOPE"],
        capture_output=True, text=True,
        env={"PROJECT_ROOT": str(tmp_path), "PATH": os.environ["PATH"]})
    combined = r.stdout + r.stderr
    assert "unknown subcommand" not in combined
    assert "not implemented" not in combined
    # unknown ticket -> friendly non-zero, proving it reached work.run.
    assert r.returncode != 0
    assert "KLC-NOPE" in combined


def test_work_does_not_drain_jira_queue(tmp_path):
    """FIX-1: `klc work` is a read-only "what's next?" query — it must NOT drain
    the Jira queue via the dispatcher's opportunistic drain (like `remind`).

    Jira sync is enabled so that if the drain ran, `flush_queue` would rewrite
    the queue (push fails without a token → canonical json.dumps reformat) and
    change its bytes. The queue line is written non-canonically (no spaces) so a
    drain-rewrite is detectable. Post-fix `work` is in NO_DRAIN_CMDS → the file
    stays byte-identical. Run through the dispatcher, not work.run, so the drain
    path is actually exercised."""
    _seed(tmp_path, "KLC-914", phase="build:work", track="S", impl_step=1)
    cfg_dir = tmp_path / ".klc" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "jira.yml").write_text(
        "sync:\n  enabled: true\n  transport: rest\n", encoding="utf-8")
    queue = tmp_path / ".klc" / "jira-queue.jsonl"
    payload = '{"ticket":"KLC-999","status":"In Progress","phase":"build:work"}\n'
    queue.write_text(payload, encoding="utf-8")

    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("JIRA_TOKEN", None)  # ensure a push would fail (no drain expected anyway)
    r = subprocess.run(
        [sys.executable, str(_KLC), "work", "KLC-914"],
        capture_output=True, text=True, env=env)

    assert r.returncode == 0, f"stderr={r.stderr!r}"
    assert queue.exists(), "work deleted the Jira queue"
    assert queue.read_text(encoding="utf-8") == payload, \
        "work mutated the Jira queue (unexpected drain side effect)"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
