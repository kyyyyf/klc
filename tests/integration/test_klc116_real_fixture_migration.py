#!/usr/bin/env python3
"""KLC-116 step-4 — AC-18 (revision 2, per F-1/D-201 and F-4/D-204).

The shipped design document of KLC-105 produces no provenance-dimension
finding (companion-rule failure, absence warning, or load-bearing block) from
the consistency gate or the M-track design-acceptance gate, with no edit
other than added `evidence=` attributes; KLC-105's pre-existing
`items.py validate` failures (`dangling_refs` on `refs=step-5`/`step-6`,
`orphan_questions`) are unrelated defects, out of this ticket's scope, and
asserted byte-identical rather than fixed.

The withdrawn `test_klc109_f102_read_from_stale_artifact_still_resolves` row
(F-1/D-201: its premise — a live item that "still resolves" — was wrong twice
over, see impl-plan-review.md finding F-1) is replaced by the synthetic
resolvability pair below.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import items  # noqa: E402
import provenance  # noqa: E402


def test_klc105_options_passes_consistency_and_design_ack_with_added_attributes_only(
        tmp_path, monkeypatch):
    dst = tmp_path / ".klc" / "tickets" / "KLC-105"
    dst.parent.mkdir(parents=True)
    # KLC-106 follow-up (D-211): this fixture snapshots the DESIGN-TIME view of
    # KLC-105 — raw.md/spec.md/test-plan.md/impl-plan.md/design/discovery/
    # acceptance-test-plan/meta.json — and must not read learn/review-phase
    # artefacts (retrospective.md, review*, manual*, integrate*, build-log.md,
    # drift-*, _superseded/...). KLC-105 gained a real `retrospective.md` after
    # this test was written, whose `[!FACT F-Rn] evidence=read` items are not
    # in `<file>:<line>` shape — a live-repo condition unrelated to what this
    # test is proving (that ADDING `evidence=` attributes to design/options.md
    # alone does not regress provenance/consistency), so copying it in made
    # the fixture non-hermetic against ongoing lifecycle activity on the real
    # ticket.
    shutil.copytree(
        FW_ROOT / ".klc" / "tickets" / "KLC-105", dst,
        ignore=shutil.ignore_patterns(
            "retrospective.md", "review*", "manual*", "integrate*",
            "build-log.md", "drift-*", "_superseded", "learn", "review",
            "manual", "integrate"))
    # The `read` src below must resolve under THIS fixture's project root too.
    stub = tmp_path / "core" / "skills" / "items.py"
    stub.parent.mkdir(parents=True)
    stub.write_text((FW_ROOT / "core" / "skills" / "items.py").read_text(encoding="utf-8"),
                     encoding="utf-8")

    # Baseline is computed from the SAME hermetic snapshot, before the
    # evidence= edit below — comparing against the live ticket's full
    # dangling_refs/orphan_questions would conflate this test's own
    # copytree exclusions with unrelated drift on the live ticket.
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    baseline = items.build_index("KLC-105", write=False)
    baseline_dangling = baseline["dangling_refs"]
    baseline_orphans = baseline["orphan_questions"]

    opts = dst / "design" / "options.md"
    text = opts.read_text(encoding="utf-8")
    text, n = re.subn(
        r"(> \[!DECISION D-00[1-4]\])",
        r"\1 evidence=read src=core/skills/items.py:1",
        text,
    )
    assert n == 4, "expected exactly D-001..D-004 to gain an evidence= attribute"
    opts.write_text(text, encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert provenance.check_artefacts("KLC-105") == []
    block, _warns = provenance.design_gate("KLC-105", "M")
    assert block == ""

    modified = items.build_index("KLC-105", write=False)
    assert modified["dangling_refs"] == baseline_dangling
    assert modified["orphan_questions"] == baseline_orphans


def _seed(tmp_path: Path, ticket: str, options_md: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "tech", "phase": "build:work",
            "phase_history": [], "track": "M",
            "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
            "affected_modules": ["core/skills"], "created": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "design").mkdir()
    (tdir / "design" / "options.md").write_text(options_md, encoding="utf-8")


def test_read_src_with_file_and_line_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-960"
    real_items = FW_ROOT / "core" / "skills" / "items.py"
    dst = tmp_path / "core" / "skills" / "items.py"
    dst.parent.mkdir(parents=True)
    dst.write_text(real_items.read_text(encoding="utf-8"), encoding="utf-8")
    _seed(tmp_path, ticket, (
        "> [!DECISION D-1] evidence=read src=core/skills/items.py:133\n"
        "> use approach A\n"
    ))
    assert provenance.check_artefacts(ticket) == []


def test_read_src_naming_a_missing_file_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-961"
    _seed(tmp_path, ticket, (
        "> [!DECISION D-1] evidence=read src=core/skills/gone.py:12\n"
        "> use approach A\n"
    ))
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["D-1"]
