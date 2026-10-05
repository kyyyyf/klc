"""KLC-176 (AC-10): a full S and a full M ticket end with at most ten tracked files
in the ticket directory.

The test drives the real writers and the real gates where it can: `klc intake`
writes raw.md and meta.json, the discovery(-lite) and design gates must ACCEPT the
seeded spec and design.md, step_state writes build/steps.json and the manual and
integrate acks go through lifecycle.apply_ack. Files an agent prompt would write
(spec, test-plan, impl-plan, design.md, design/scout.md, review-report,
retrospective) are seeded with their real names.

Budget rule (documented, KLC-176 review round 1):
  counted   : everything tracked under tickets/<KEY>/ except the exclusions below
  excluded  : build-log.md (optional free-form implementer notes, impl.md),
              findings.json, advisories.json (owned by KLC-173), review/** (KLC-175),
              .index.json and .lock (derived)
design/scout.md is COUNTED for M (design-scout writes it when it triggers).

Limitation: spec, plans, design.md, scout.md, review-report and retrospective are seeded by
hand, so a prompt that starts writing an extra file would not be caught here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle  # noqa: E402
import step_state  # noqa: E402
from core.shared import paths  # noqa: E402
from core.skills.phase_completion import (  # noqa: E402
    can_complete_discovery,
    can_complete_discovery_lite,
)
from core.skills.phase_completion import can_complete  # noqa: E402

BUDGET = 10
EXCLUDED_NAMES = {"build-log.md", "findings.json", "advisories.json", ".index.json", ".lock"}

_APPROACHES = """\
## Approaches
- Option A: fast impl — quick but narrow
- Option B: safer impl — slower but robust

Picked: Option A — lower risk
"""

_SPEC = """\
---
ticket: {key}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Provide a concrete implementation for the required feature.

## Acceptance Criteria
- [ ] AC-1: The gate passes when spec.md carries two approaches and a pick.

{approaches}
## Affected
test_module: core/test.py, src=core/test.py:1

## Estimate
complexity: {c}
uncertainty: 1
risk: 1
manual: 0
total: {t}
"""

_PLAN = """\
## step-1 — do the thing

- **Goal:** implement the feature
- RED: not applicable
- **Interfaces:** `def f() -> None`
- **Expected:** f runs
- **VERIFY:** pytest
- **COMMIT:** KLC-X step-1: do the thing
- **Affected:** src/x.py
"""

_DESIGN = ("# Design\n\n## Options\n- Option A: x — small\n- Option B: y — large\n"
           "Picked: Option A — small\n\n## Chosen design\nA.\n\n## Consequences\nnone\n")


def _git_project(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T"),
                 ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "i"],
                   check=True)


def _counted(tdir: Path) -> list[str]:
    out = []
    for f in sorted(tdir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(tdir)
        if rel.parts[0] == "review" or rel.name in EXCLUDED_NAMES:
            continue
        out.append(str(rel))
    return out


def _drive(root: Path, monkeypatch, key: str, track: str) -> list[str]:
    root.mkdir(parents=True)
    _git_project(root)
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run([sys.executable, str(_FW / "scripts" / "klc"), "intake", "--kind",
                        "feature", "--no-index-refresh", key, "add a thing"],
                       cwd=str(root), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    tdir = paths.klc_ticket_dir(key)
    meta = json.loads((tdir / "meta.json").read_text("utf-8"))
    meta.update({"track": track, "route_hint": track, "affected_modules": ["test_module"],
                 "layer": "code", "phase": "discovery:work",
                 "estimate": {"complexity": 1 if track == "S" else 2, "uncertainty": 1,
                              "risk": 1, "manual": 0, "total": 3 if track == "S" else 4}})
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # discovery: the REAL gate must accept the spec (Approaches section, pick)
    (tdir / "spec.md").write_text(
        _SPEC.format(key=key, approaches=_APPROACHES, c=1 if track == "S" else 2,
                     t=3 if track == "S" else 4), encoding="utf-8")
    (tdir / "impl-plan.md").write_text(_PLAN, encoding="utf-8")
    gate = can_complete_discovery_lite if track == "S" else can_complete_discovery
    ok, msg = gate(key, persist=False)
    assert ok, msg
    (tdir / "test-plan.md").write_text("# Test plan\n- AC-1: test_x\n", encoding="utf-8")
    if track == "M":
        (tdir / "design.md").write_text(_DESIGN, encoding="utf-8")
        (tdir / "design").mkdir()
        (tdir / "design" / "scout.md").write_text("# Scout\nfindings\n", encoding="utf-8")
        ok, msg = can_complete(key, "design", persist=False)
        assert ok, msg

    # build: step state in build/, transient step files in scratch (not the ticket dir)
    step_state._write_atomic(key, 1, verify={"green_sha": "abc", "result": "pass"})
    scratch = paths.transient_dir(key)
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "step-1-brief.md").write_text("brief", encoding="utf-8")
    (scratch / "retrieval_trace.json").write_text("{}", encoding="utf-8")
    (tdir / "build-log.md").write_text("## Step 1\nnotes\n", encoding="utf-8")
    # review, learn (KLC-173/175 files are excluded from the budget)
    (tdir / "review-report.md").write_text("# Review report\n", encoding="utf-8")
    (tdir / "review").mkdir()
    (tdir / "review" / "review-plan-r1.json").write_text("{}", encoding="utf-8")
    (tdir / "findings.json").write_text("{}", encoding="utf-8")
    (tdir / "advisories.json").write_text("{}", encoding="utf-8")
    (tdir / "retrospective.md").write_text(
        "# R\n\n## What the gates missed\n- none\n\n## Token cost by phase\nn/a\n\n"
        "## One process change\n- none\n", encoding="utf-8")
    # manual and integrate outcomes land in meta through the real ack writer
    for phase in ("manual", "integrate"):
        meta = json.loads((tdir / "meta.json").read_text("utf-8"))
        meta["phase"] = f"{phase}:ack-needed"
        meta["phase_history"] = [{"phase": f"{phase}:ack-needed",
                                  "started_at": "2026-10-05T00:00:00Z"}]
        (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        lifecycle.apply_ack(key, 1 if phase == "manual" else None, "walked it")
    final = json.loads((tdir / "meta.json").read_text("utf-8"))
    assert "manual" in final and "integrate" in final
    return _counted(tdir)


def test_full_s_and_m_ticket_tracked_files_at_most_ten(tmp_path, monkeypatch):
    s_files = _drive(tmp_path / "s", monkeypatch, "KLC-940", "S")
    m_files = _drive(tmp_path / "m", monkeypatch, "KLC-941", "M")
    print("S files:", s_files)
    print("M files:", m_files)
    assert len(s_files) <= BUDGET, f"S has {len(s_files)}: {s_files}"
    assert len(m_files) <= BUDGET, f"M has {len(m_files)}: {m_files}"
    assert "design/scout.md" in m_files, "M counts design/scout.md toward the budget"
    for files in (s_files, m_files):
        for gone in ("options-lite.md", "design/options.md", "design/adr.md",
                     "manual-checklist.md", "integrate.md", "retrieval_trace.json"):
            assert gone not in files, files
        assert "build-log.md" not in files          # optional notes, excluded by rule
        assert not any(f.startswith("_superseded/") for f in files), files
