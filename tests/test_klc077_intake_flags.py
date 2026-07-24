"""KLC-077 — `klc intake --epic` / `--blocked-by` flag coverage (feature-OFF).

Runs the real `klc intake` verb via subprocess against a temp PROJECT_ROOT with
the multi-user feature OFF (no `.klc` git worktree → state_tx is a no-op, writes
are plain-local). Pins:

  - `--epic <ROOT>` writes meta.epic;
  - repeatable `--blocked-by "<K>@<point>[:cond]#<phase>"` parses into
    meta.blocked_by edges;
  - malformed specs / unknown points / unknown downstream phases hard-fail
    (rc != 0) and create NO ticket;
  - a plain intake (no epic flags) adds NEITHER key — existing non-epic tickets
    are completely unaffected.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
KLC = FW_ROOT / "scripts" / "klc"


def _env(root: Path) -> dict[str, str]:
    e = {**os.environ, "PROJECT_ROOT": str(root)}
    e.pop("KLC_TICKETS_DIR", None)
    # Keep intake deterministic / offline.
    e["KLC_INTAKE_TRIAGE"] = "0"
    return e


def _run(args: list[str], root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


def _meta(root: Path, key: str) -> dict:
    return json.loads((root / ".klc" / "tickets" / key / "meta.json")
                      .read_text(encoding="utf-8"))


def test_intake_epic_writes_meta_epic(tmp_path):
    r = _run(["intake", "KLC-077", "--kind", "feature",
              "--epic", "KLC-077", "epic root ticket"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert _meta(tmp_path, "KLC-077").get("epic") == "KLC-077"


def test_intake_blocked_by_parses_edges(tmp_path):
    r = _run(["intake", "KLC-079", "--kind", "feature",
              "--epic", "KLC-077",
              "--blocked-by", "KLC-077@integrated:passed#build",
              "--blocked-by", "KLC-078@integrated#build",
              "downstream skill ticket"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = _meta(tmp_path, "KLC-079")
    assert m.get("epic") == "KLC-077"
    assert m.get("blocked_by") == [
        {"on": "KLC-077", "point": "integrated",
         "condition": "passed", "phase": "build"},
        {"on": "KLC-078", "point": "integrated", "phase": "build"},
    ]


def test_intake_plain_ticket_has_no_epic_keys(tmp_path):
    r = _run(["intake", "KLC-900", "--kind", "tech", "a plain ticket"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = _meta(tmp_path, "KLC-900")
    assert "epic" not in m
    assert "blocked_by" not in m


def test_intake_bad_point_hard_fails_and_creates_nothing(tmp_path):
    r = _run(["intake", "KLC-901", "--kind", "feature",
              "--blocked-by", "KLC-077@shipped#build", "bad point"], tmp_path)
    assert r.returncode != 0
    assert not (tmp_path / ".klc" / "tickets" / "KLC-901").exists()


def test_intake_malformed_spec_hard_fails(tmp_path):
    r = _run(["intake", "KLC-902", "--kind", "feature",
              "--blocked-by", "garbage-no-delimiters", "bad shape"], tmp_path)
    assert r.returncode != 0
    assert not (tmp_path / ".klc" / "tickets" / "KLC-902").exists()


def test_intake_unknown_downstream_phase_hard_fails(tmp_path):
    r = _run(["intake", "KLC-903", "--kind", "feature",
              "--blocked-by", "KLC-077@integrated#biuld", "typo phase"], tmp_path)
    assert r.returncode != 0
    assert not (tmp_path / ".klc" / "tickets" / "KLC-903").exists()


def test_intake_self_reference_edge_hard_fails(tmp_path):
    # LOW-4: a ticket cannot list itself as an upstream (a 1-node cycle).
    r = _run(["intake", "KLC-904", "--kind", "feature",
              "--blocked-by", "KLC-904@integrated#build", "self dep"], tmp_path)
    assert r.returncode != 0
    assert "self" in r.stderr.lower()
    assert not (tmp_path / ".klc" / "tickets" / "KLC-904").exists()
