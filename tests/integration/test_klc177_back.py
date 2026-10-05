"""KLC-177 step-1 (AC-6, AC-7): `klc back <KEY> <phase> --reason TEXT`.

Feature-OFF, through the real `scripts/klc` in a tmp project, so the whole
lock -> state_tx -> lifecycle path runs as an operator would run it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
KLC = FW_ROOT / "scripts" / "klc"

REASON = "the acceptance criteria miss the offline case; answer it point by point"


def _env(root: Path) -> dict[str, str]:
    e = {**os.environ, "PROJECT_ROOT": str(root)}
    e.pop("KLC_TICKETS_DIR", None)
    return e


def _bootstrap(root: Path, key: str, *, phase: str, track: str = "M",
               artefacts: dict | None = None) -> Path:
    tdir = root / ".klc" / "tickets" / key
    tdir.mkdir(parents=True)
    meta = {
        "ticket": key, "kind": "feature", "kind_source": "user", "phase": phase,
        "phase_history": [{"phase": phase, "started_at": "2026-01-01T00:00:00Z"}],
        "track": track, "route_hint": track, "affected_modules": [],
        "budgets": {"mutation_fix_attempts": 3}, "estimate": None,
        "jira_url": None, "created": "2026-01-01T00:00:00Z", "rework_count": {},
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (tdir / "raw.md").write_text("raw\n", encoding="utf-8")
    for rel, text in (artefacts or {}).items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tdir


def _klc(args: list[str], root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text(encoding="utf-8"))


def _card_path(stdout: str) -> Path:
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("cat "):
            return Path(line[4:].strip())
    raise AssertionError(f"no `cat <card>` line in output:\n{stdout}")


@pytest.mark.parametrize("start,key", [
    ("design:work", "T177-W"),
    ("design:ack-needed", "T177-N"),
    ("review:ack", "T177-A"),
])
def test_back_from_work_ack_needed_and_ack_records_rework_and_card_reason(
        tmp_path, start, key):
    tdir = _bootstrap(tmp_path, key, phase=start, artefacts={
        "spec.md": "spec\n", "design.md": "d\n", "impl-plan.md": "p\n",
        "review-report.md": "r\n"})

    r = _klc(["back", key, "discovery", "--reason", REASON], tmp_path)
    assert r.returncode == 0, r.stderr

    m = _meta(tdir)
    assert m["phase"] == "discovery:work"
    assert m["rework_count"] == {"discovery": 1}, "bumped exactly once"
    assert len(m["rework"]) == 1
    entry = m["rework"][0]
    assert entry["from"] == start and entry["to"] == "discovery"
    assert entry["reason"] == REASON
    assert entry["at"] and entry["by"]
    # the outputs of the phases discovery..current are superseded
    assert not (tdir / "spec.md").exists()
    assert not (tdir / "design.md").exists()

    card = _card_path(r.stdout)
    text = card.read_text(encoding="utf-8")
    assert "## Rework" in text
    assert REASON in text.split("## Rework", 1)[1]


def test_back_rejects_missing_reason_forward_target_terminal_and_cancel_matches_abort(
        tmp_path):
    key = "T177-R"
    tdir = _bootstrap(tmp_path, key, phase="design:work",
                      artefacts={"design.md": "d\n"})
    before = (tdir / "meta.json").read_bytes()

    for argv in (["back", key, "discovery"],
                 ["back", key, "discovery", "--reason", "   "],
                 ["back", key, "discovery", "--reason", ""],
                 ["back", key, "review", "--reason", "forward is go"],
                 ["back", key, "no-such-phase", "--reason", "x"]):
        r = _klc(argv, tmp_path)
        assert r.returncode == 2, (argv, r.returncode, r.stderr)
        assert r.stderr.strip(), argv
        assert (tdir / "meta.json").read_bytes() == before, argv
        assert (tdir / "design.md").exists(), argv

    # terminal tickets are refused untouched
    for term, k in (("archived", "T177-X"), ("cancelled", "T177-Y")):
        t2 = _bootstrap(tmp_path, k, phase=term)
        b2 = (t2 / "meta.json").read_bytes()
        r = _klc(["back", k, "discovery", "--reason", "x"], tmp_path)
        assert r.returncode == 2, (term, r.stderr)
        assert (t2 / "meta.json").read_bytes() == b2

    # --cancel behaves exactly like `abort --cancel`
    a = _bootstrap(tmp_path, "T177-CA", phase="build:work")
    b = _bootstrap(tmp_path, "T177-CB", phase="build:work")
    ra = _klc(["abort", "T177-CA", "--cancel", "--reason", "gone"], tmp_path)
    rb = _klc(["back", "T177-CB", "--cancel", "--reason", "gone"], tmp_path)
    assert ra.returncode == rb.returncode == 0, (ra.stderr, rb.stderr)
    ma, mb = _meta(a), _meta(b)
    for k in ("phase", "cancelled", "cancel_reason"):
        assert ma[k] == mb[k]
    assert mb["phase"] == "cancelled"
    # --cancel still requires a reason
    c = _bootstrap(tmp_path, "T177-CC", phase="build:work")
    bc = (c / "meta.json").read_bytes()
    rc = _klc(["back", "T177-CC", "--cancel"], tmp_path)
    assert rc.returncode == 2
    assert (c / "meta.json").read_bytes() == bc
