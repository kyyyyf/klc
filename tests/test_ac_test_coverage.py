"""KLC-095 (V-02) — AC→implemented-test coverage gate at build.

The deterministic double of KLC-085's plan-time coverage check: KLC-085 proves
each SAOC acceptance criterion is covered in the test PLAN; this skill proves the
planned coverage actually LANDED as a real, collected, passing implemented test.

Layout mirrors the three impl-plan steps:
  * step-1 — build_map: each AC → its implemented test, covered/drift/miss.
  * step-2 — check(): severity + track scaling + operator override + degrade.
  * step-3 — the can_complete_build integration (block path + surface path).

Single source of truth (C-001): ACs come only through spec_saoc.parse_acs and the
plan-declared locations only through testplan_review.coverage_map; this file never
re-implements either.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ac_test_coverage as acov  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — spec / test-plan text builders and a tmp tests/ tree.
# ---------------------------------------------------------------------------

def _spec(*ac_ids: str) -> str:
    """A minimal SAOC spec.md body naming each AC id (well-formed four parts)."""
    lines = ["---", "ticket: KLC-XXX", "kind: feature", "---", "", "## Acceptance Criteria"]
    for ac in ac_ids:
        lines.append(f"- [ ] {ac}: subject · acts · object · when a thing happens")
    lines += ["", "## Estimate", "- total: 1"]
    return "\n".join(lines)


def _test_plan(*rows: tuple[str, str]) -> str:
    """A test-plan.md with an `## Acceptance coverage` table.

    Each row is (ac_id, location); an empty/placeholder location marks the AC
    planned-but-uncovered (has_real_test False).
    """
    lines = [
        "---", "ticket: KLC-XXX", "kind: test-plan", "---", "",
        "## Acceptance coverage", "",
        "| AC | Type | Test location |",
        "| --- | --- | --- |",
    ]
    for ac, loc in rows:
        lines.append(f"| {ac} | unit | {loc} |")
    lines += ["", "## Edge cases", "- malformed input is rejected"]
    return "\n".join(lines)


def _write(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# step-1 — build_map: AC → implemented test, covered/drift/miss
# ---------------------------------------------------------------------------

def test_map_matches_ac_in_function_name(tmp_path):
    """AC-2: an AC-id token in the test FUNCTION NAME (ac1) marks the AC covered."""
    root = tmp_path / "tests"
    _write(root, "test_holder.py", "def test_ac1_acquire_when_absent():\n    assert True\n")
    m = acov.build_map(_spec("AC-1"),
                       _test_plan(("AC-1", "tests/test_holder.py::test_ac1_acquire_when_absent")), root)
    assert m["AC-1"] == "covered", m


def test_map_matches_ac_in_docstring(tmp_path):
    """AC-2: the canonical AC-<n> in a test DOCSTRING marks the AC covered."""
    root = tmp_path / "tests"
    _write(root, "test_verify.py",
           'def test_verify_step_ordered():\n    """AC-2: failing test precedes impl."""\n    assert True\n')
    m = acov.build_map(_spec("AC-2"),
                       _test_plan(("AC-2", "tests/test_verify.py::test_verify_step_ordered")), root)
    assert m["AC-2"] == "covered", m


def test_map_ac_token_boundary_ac1_not_in_ac10(tmp_path):
    """The name token is bounded: `ac1` must NOT satisfy AC-10 (and vice versa)."""
    root = tmp_path / "tests"
    _write(root, "test_x.py", "def test_ac1_only():\n    assert True\n")
    m = acov.build_map(_spec("AC-1", "AC-10"),
                       _test_plan(("AC-1", "tests/test_x.py::test_ac1_only")), root)
    assert m["AC-1"] == "covered", m
    assert m["AC-10"] == "miss", m  # ac1 must not leak into AC-10


def test_scan_scoped_to_ticket_files_not_repo_wide(tmp_path):
    """FIX-1 (Codex MEDIUM): AC ids are NOT globally unique — every ticket restarts
    at AC-1. The scan must be scoped to THIS ticket's own test files, so another
    ticket's AC-1 test does not falsely mark this ticket's AC-1 covered."""
    root = tmp_path / "tests"
    _write(root, "test_ticket_a.py", "def test_ac1_a():\n    assert True\n")  # ANOTHER ticket
    _write(root, "test_ticket_b.py", "def test_ac2_b():\n    assert True\n")  # THIS ticket, no AC-1
    # Scoped to ticket B's own files → AC-1 is a MISS even though ticket A covers AC-1.
    m = acov.build_map(_spec("AC-1"), _test_plan(), root,
                       candidate_files={"tests/test_ticket_b.py"})
    assert m["AC-1"] == "miss", m
    # Sanity: a repo-wide candidate set would have (wrongly) found ticket A's AC-1.
    m2 = acov.build_map(_spec("AC-1"), _test_plan(), root,
                        candidate_files={"tests/test_ticket_a.py", "tests/test_ticket_b.py"})
    assert m2["AC-1"] == "covered", m2


def test_nested_tests_dir_candidate_is_scanned(tmp_path):
    """FIX-A (Codex P2, false-block): a monorepo candidate under a NESTED tests dir
    (`pkg/tests/test_ac1.py`) is admitted to the candidate set, so it must actually
    be SCANNED at its real path — else the AC is a false MISS→BLOCK on M/L."""
    tests_root = tmp_path / "tests"
    tests_root.mkdir()  # the conventional root; the real test lives elsewhere
    _write(tmp_path / "pkg" / "tests", "test_ac1.py",
           "def test_ac1_nested():\n    assert True\n")
    tp = _test_plan(("AC-1", "pkg/tests/test_ac1.py::test_ac1_nested"))
    m = acov.build_map(_spec("AC-1"), tp, tests_root)  # candidate derived from the plan
    assert m["AC-1"] == "covered", m


def test_ac_token_right_boundary_rejects_trailing_letters(tmp_path):
    """FIX-B (Codex P3): the AC token's right boundary must reject LETTERS too —
    `test_ac1beta` and body `AC-1a` are NOT AC-1 (an uncovered AC must stay uncovered)."""
    root = tmp_path / "tests"
    # name form: test_ac1beta must NOT cover AC-1
    _write(root, "test_a.py", "def test_ac1beta():\n    assert True\n")
    m = acov.build_map(_spec("AC-1"),
                       _test_plan(("AC-1", "tests/test_a.py::test_ac1beta")), root)
    assert m["AC-1"] != "covered", m
    # body form: AC-1a must NOT cover AC-1
    _write(root, "test_b.py", 'def test_thing():\n    """see AC-1a for details"""\n    assert True\n')
    m2 = acov.build_map(_spec("AC-1"),
                        _test_plan(("AC-1", "tests/test_b.py::test_thing")), root)
    assert m2["AC-1"] != "covered", m2


def test_ac_token_boundary_accepts_valid_separators(tmp_path):
    """FIX-B counterpart: `ac1_foo` and body `AC-1.` / `AC-1 ` still DO cover AC-1."""
    root = tmp_path / "tests"
    _write(root, "test_c.py", "def test_ac1_something():\n    assert True\n")
    assert acov.build_map(_spec("AC-1"),
                          _test_plan(("AC-1", "tests/test_c.py::test_ac1_something")),
                          root)["AC-1"] == "covered"
    _write(root, "test_d.py", 'def test_d():\n    """closes AC-1."""\n    assert True\n')
    assert acov.build_map(_spec("AC-1"),
                          _test_plan(("AC-1", "tests/test_d.py::test_d")),
                          root)["AC-1"] == "covered"
    _write(root, "test_e.py", 'def test_e():\n    """closes AC-1 fully"""\n    assert True\n')
    assert acov.build_map(_spec("AC-1"),
                          _test_plan(("AC-1", "tests/test_e.py::test_e")),
                          root)["AC-1"] == "covered"


def test_plan_cell_with_multiple_files_scans_all(tmp_path):
    """FIX-A (Codex P2): a coverage-table cell may name MULTIPLE test files; the AC's
    real test may live in the SECOND. Every `.py` in the cell must join the candidate
    set — else the passing test is never scanned and the AC is falsely drift/weak."""
    root = tmp_path / "tests"
    _write(root, "test_a.py", "def test_other():\n    assert True\n")          # no AC-1
    _write(root, "test_b.py", "def test_ac1_real():\n    assert True\n")        # AC-1 lives here
    tp = _test_plan(("AC-1", "tests/test_a.py::test_other tests/test_b.py::test_ac1_real"))
    m = acov.build_map(_spec("AC-1"), tp, root)  # candidate_files derived from the plan cell
    assert m["AC-1"] == "covered", m


def test_map_uses_parse_acs_and_coverage_map_single_source(tmp_path, monkeypatch):
    """AC-1: the skill reads ACs via spec_saoc.parse_acs and plan locations via
    testplan_review.coverage_map — it re-implements neither (single source)."""
    calls = {"parse_acs": 0, "coverage_map": 0}
    real_parse = acov._saoc.parse_acs
    real_cov = acov._tpr.coverage_map

    def spy_parse(text):
        calls["parse_acs"] += 1
        return real_parse(text)

    def spy_cov(spec_text, tp_text):
        calls["coverage_map"] += 1
        return real_cov(spec_text, tp_text)

    monkeypatch.setattr(acov._saoc, "parse_acs", spy_parse)
    monkeypatch.setattr(acov._tpr, "coverage_map", spy_cov)
    root = tmp_path / "tests"
    root.mkdir()
    acov.build_map(_spec("AC-1"), _test_plan(), root)
    assert calls["parse_acs"] >= 1, "build_map must anchor on spec_saoc.parse_acs"
    assert calls["coverage_map"] >= 1, "build_map must anchor on testplan_review.coverage_map"


def test_reconcile_plan_declared_but_absent_is_drift(tmp_path):
    """AC-3: the plan declared a real test location but no implemented test
    references the AC → drift, not covered and not a bare miss."""
    root = tmp_path / "tests"
    root.mkdir()  # empty: nothing references AC-3
    m = acov.build_map(_spec("AC-3"),
                       _test_plan(("AC-3", "tests/test_gone.py::test_ac3_x")), root)
    assert m["AC-3"] == "drift", m


def test_ac_with_no_implemented_test_is_miss(tmp_path):
    """A SAOC AC with neither a plan-declared location nor an implemented test → miss."""
    root = tmp_path / "tests"
    root.mkdir()
    m = acov.build_map(_spec("AC-4"), _test_plan(), root)
    assert m["AC-4"] == "miss", m


# ---------------------------------------------------------------------------
# step-2 — check(): severity + track scaling + override + degrade
# ---------------------------------------------------------------------------

def _setup_check(monkeypatch, tmp_path, spec, tp, files=None, passing=True, meta=None):
    """Wire acov.check's seams to hermetic in-memory inputs.

    files: {filename: source} written under a tmp tests/ root.
    passing: bool | dict[node_id, bool] returned by the injected _verify_passing.
    meta: the meta dict _read_meta_ro yields (for the deferral override).
    """
    root = tmp_path / "tests"
    root.mkdir(parents=True, exist_ok=True)
    for name, src in (files or {}).items():
        _write(root, name, src)
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_load_texts", lambda ticket: (spec, tp))
    monkeypatch.setattr(acov, "_read_meta_ro", lambda ticket: dict(meta or {}))
    # Pin the git-derived changed-file source so candidates are deterministic and
    # AVAILABLE (empty set, not None): candidates then come purely from the plan.
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())

    def fake_verify(node_ids, repo=None, tests_root=None):
        if isinstance(passing, dict):
            return {n: passing.get(n, False) for n in node_ids}
        return {n: bool(passing) for n in node_ids}

    monkeypatch.setattr(acov, "_verify_passing", fake_verify)
    return root


def _locatable_miss_args():
    """A PLAN-SUBSTANTIATED miss: AC-1's plan-declared location is a REAL, scanned
    file (test_x.py) that turns out to contain no AC-1 test — a git-independent,
    confident miss. AC-2 is genuinely covered in the same file."""
    return (_spec("AC-1", "AC-2"),
            _test_plan(("AC-1", "tests/test_x.py::test_ac1_x"),
                       ("AC-2", "tests/test_x.py::test_ac2_x")),
            {"test_x.py": "def test_ac2_x():\n    assert True\n"})


def test_miss_blocks_on_ml(monkeypatch, tmp_path):
    """AC-4/AC-7: a locatable miss (the ticket has tests, AC-1 has none) BLOCKS on M/L."""
    spec, tp, files = _locatable_miss_args()
    _setup_check(monkeypatch, tmp_path, spec, tp, files=files)
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason, "an objective miss must block on M"
    assert "AC-1" in rep.block_reason, rep.block_reason


def test_miss_surfaces_only_on_s(monkeypatch, tmp_path):
    """AC-7: on S a miss surfaces but never blocks (KLC-095 itself is S)."""
    spec, tp, files = _locatable_miss_args()
    _setup_check(monkeypatch, tmp_path, spec, tp, files=files)
    rep = acov.check("KLC-XXX", "S")
    assert rep.block_reason is None, "S must not block"
    assert any(f.severity == acov.SURFACE for f in rep.findings), rep.findings


def test_scan_error_on_candidate_surfaces_not_blocks(monkeypatch, tmp_path):
    """HARDENING: BLOCK fires ONLY on a CONFIDENT miss (non-empty candidates AND the
    scan completed without error). A candidate file that fails to parse means the
    scan is incomplete → an apparently-uncovered AC is undetermined → SURFACE, never
    BLOCK, even on M — capping the false-block risk of this blocking gate."""
    _setup_check(monkeypatch, tmp_path, _spec("AC-1", "AC-2"),
                 _test_plan(("AC-2", "tests/test_broken.py::test_ac2_x")),
                 files={"test_broken.py": "def test_ac2_x(  # SYNTAX ERROR, unbalanced\n"})
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason is None, "a scan/parse error must degrade to surface, never block"
    assert any(f.severity == acov.SURFACE for f in rep.findings), rep.findings


def test_malformed_ac_does_not_block(monkeypatch, tmp_path):
    """FIX-A (Codex P2, false-block): a malformed SAOC AC (no `·` segments) still
    parses as an AC, but it must NOT drive an AC-coverage block — that is a spec-
    quality problem the spec self-check owns. It surfaces/skips; well-formed ACs
    still gate."""
    spec = "\n".join([
        "---", "ticket: KLC-XXX", "kind: feature", "---", "",
        "## Acceptance Criteria",
        "- [ ] AC-1: subject · acts · object · when a thing happens",  # well-formed
        "- [ ] AC-2: this AC is malformed with no middle dots at all",  # malformed
        "", "## Estimate", "- total: 1",
    ])
    tp = _test_plan(("AC-1", "tests/test_x.py::test_ac1_x"),
                    ("AC-2", "tests/test_x.py::test_ac2_x"))
    _setup_check(monkeypatch, tmp_path, spec, tp,
                 files={"test_x.py": "def test_ac1_x():\n    assert True\n"})
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason is None, "a malformed AC must not drive a block"
    ids = {f.ac_id for f in rep.findings}
    assert "AC-1" not in ids, "well-formed AC-1 is covered → no finding"
    assert any(f.ac_id == "AC-2" and f.severity == acov.SURFACE for f in rep.findings), rep.findings


def test_partial_multifile_plan_scan_does_not_substantiate_block(monkeypatch, tmp_path):
    """FIX-B (Codex P2, false-block): when an AC's plan cell names MULTIPLE files and
    only SOME scanned, a miss is NOT substantiated — the AC's real test could live in
    the UNscanned planned file. Block only when ALL of the AC's plan files scanned."""
    # One planned file scans OK (no AC-1); the other has a syntax error (unscannable).
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"),
                 _test_plan(("AC-1", "tests/test_ok.py::test_other tests/test_bad.py::test_ac1_x")),
                 files={"test_ok.py": "def test_other():\n    assert True\n",
                        "test_bad.py": "def test_ac1_x(  # SYNTAX ERROR, unbalanced\n"})
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason is None, "a partially-scanned multi-file plan cell must not block"
    assert any(f.ac_id == "AC-1" and f.severity == acov.SURFACE for f in rep.findings), rep.findings

    # Normal case still holds: ALL planned files scanned, none reference AC-1 → block.
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"),
                 _test_plan(("AC-1", "tests/test_ok.py::test_other tests/test_ok2.py::test_more")),
                 files={"test_ok.py": "def test_other():\n    assert True\n",
                        "test_ok2.py": "def test_more():\n    assert True\n"})
    rep2 = acov.check("KLC-XXX", "M")
    assert rep2.block_reason, "all plan files scanned, none reference AC-1 → confident block"
    assert "AC-1" in rep2.block_reason, rep2.block_reason


def test_changed_test_files_uses_project_repo_not_process_cwd(tmp_path, monkeypatch):
    """FIX (Codex P2, false-block): git must run in the PROJECT repo (PROJECT_ROOT),
    NOT the process CWD — else a multi-project / launched-elsewhere invocation misses
    THIS ticket's changed tests and a plan-unlisted-but-implemented AC false-blocks."""
    import subprocess as _sp

    def _run(*args):
        return _sp.run(["git", *args], cwd=proj, capture_output=True, text=True)

    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    _run("init")
    _run("config", "user.email", "t@t")
    _run("config", "user.name", "t")
    (proj / "tests" / "test_ac1.py").write_text("def test_ac1_x():\n    assert True\n")
    _run("add", "-A")
    _run("commit", "-m", "base")
    # A tracked modification → shows in `git diff --name-only HEAD`.
    (proj / "tests" / "test_ac1.py").write_text("def test_ac1_x():\n    assert True  # changed\n")

    _run("branch", "-M", "main")              # a real diff base exists (origin/main/main)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)              # process CWD is NOT the project repo
    monkeypatch.setenv("PROJECT_ROOT", str(proj))
    files = acov._changed_test_files(None)    # repo=None → must resolve to PROJECT_ROOT
    assert files is not None, "git is available with a diff base → not None"
    assert any("tests/test_ac1.py" in f for f in files), files


def test_no_merge_base_returns_none_not_empty_set(tmp_path, monkeypatch):
    """FIX (Codex P2, final git false-block): git is available but NO merge-base can
    be established against origin/main or main (shallow feature-branch clone). The
    changed-file supplement is then UNCERTAIN — it must return None (unavailable),
    NOT an empty set that would be treated as 'complete, no changes' and let an M/L
    ticket false-block a plan-unlisted AC whose committed test references it."""
    import subprocess as _sp

    def _run(*args):
        return _sp.run(["git", *args], cwd=proj, capture_output=True, text=True)

    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    _run("init")
    _run("config", "user.email", "t@t")
    _run("config", "user.name", "t")
    (proj / "tests" / "test_ac1.py").write_text("def test_ac1_x():\n    assert True\n")
    _run("add", "-A")
    _run("commit", "-m", "base")
    _run("branch", "-M", "feature")           # the ONLY branch; no main / origin/main
    monkeypatch.setenv("PROJECT_ROOT", str(proj))
    assert acov._changed_test_files(None) is None, \
        "no positively-established diff base → unavailable (None), never an empty set"


def test_untracked_new_test_file_is_discovered(tmp_path):
    """FIX-B (Codex P2): a brand-new UNTRACKED test file is omitted by every
    `git diff`, so it must be discovered via `git ls-files --others` — otherwise a
    just-added test can never CLEAR a miss."""
    import subprocess as _sp

    def _run(*args):
        return _sp.run(["git", *args], cwd=proj, capture_output=True, text=True)

    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    _run("init")
    _run("config", "user.email", "t@t")
    _run("config", "user.name", "t")
    (proj / "tests" / "test_base.py").write_text("def test_base():\n    assert True\n")
    _run("add", "-A")
    _run("commit", "-m", "base")
    _run("branch", "-M", "main")
    # A brand-new, never-added test file (untracked).
    (proj / "tests" / "test_ac2.py").write_text("def test_ac2_new():\n    assert True\n")
    files = acov._changed_test_files(proj)
    assert files is not None
    assert any("tests/test_ac2.py" in f for f in files), files


def test_check_honors_repo_override_end_to_end(tmp_path, monkeypatch):
    """FIX-A (Codex P2, false-block): check(repo=...) must scan candidate files in
    THAT repo, not PROJECT_ROOT's tests dir — else a real test in the override tree
    is never scanned and its AC false-misses/blocks."""
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)                 # PROJECT_ROOT tree: empty
    other = tmp_path / "other"
    (other / "tests").mkdir(parents=True)
    _write(other / "tests", "test_ac1.py", "def test_ac1_x():\n    assert True\n")
    monkeypatch.setattr(acov, "_tests_root", lambda: proj / "tests")
    monkeypatch.setattr(acov, "_load_texts",
                        lambda t: (_spec("AC-1"),
                                   _test_plan(("AC-1", "tests/test_ac1.py::test_ac1_x"))))
    monkeypatch.setattr(acov, "_read_meta_ro", lambda t: {})
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())
    rep = acov.check("KLC-XXX", "M", repo=other)  # honor repo end-to-end
    states = {f.ac_id: f.state for f in rep.findings}
    assert rep.block_reason is None, f"AC-1 is covered in the override repo: {states}"
    assert "AC-1" not in states, f"AC-1 covered in the override repo → no finding: {states}"


def test_git_unavailable_never_forces_a_miss_block(tmp_path, monkeypatch):
    """FIX counterpart: if the changed-files supplement is UNAVAILABLE (git missing /
    not a repo → None), a plan-covered AC stays COVERED and a plan-unlisted AC is
    undetermined (SURFACE), never a false MISS→block — the miss is not confident."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_x.py", "def test_ac1_x():\n    assert True\n")
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_load_texts",
                        lambda t: (_spec("AC-1", "AC-2"),
                                   _test_plan(("AC-1", "tests/test_x.py::test_ac1_x"))))
    monkeypatch.setattr(acov, "_read_meta_ro", lambda t: {})
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: None)  # git unavailable
    rep = acov.check("KLC-XXX", "M")  # real _verify_passing
    assert rep.degraded is False, "a git-unavailable supplement must not degrade the whole check"
    assert rep.block_reason is None, "git unavailable must never force a miss→block"
    states = {f.ac_id: f.state for f in rep.findings}
    assert "AC-1" not in states, f"AC-1 is plan-covered → covered, no finding: {states}"
    assert states.get("AC-2") == acov.MISS, states  # located-nothing but undetermined
    assert all(f.severity == acov.SURFACE for f in rep.findings), rep.findings


def test_empty_candidate_set_surfaces_not_blocks(monkeypatch, tmp_path):
    """No-false-block invariant: when the gate cannot LOCATE the ticket's tests
    (empty coverage table AND no changed test files), an AC that appears uncovered
    is UNDETERMINED, not an objective miss — SURFACE, never BLOCK, even on M."""
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"), _test_plan())  # empty plan, no files
    rep = acov.check("KLC-XXX", "M")  # _setup_check pins _changed_test_files → empty
    assert rep.block_reason is None, "an undetermined AC must not block (no-false-block)"
    assert rep.degraded is True, "empty candidate set must degrade"
    assert any(f.severity == acov.SURFACE for f in rep.findings), rep.findings


def test_off_on_xs(monkeypatch, tmp_path):
    """AC-7: on XS the coverage check is OFF — no findings, no block."""
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"), _test_plan())
    rep = acov.check("KLC-XXX", "XS")
    assert rep.block_reason is None
    assert rep.findings == [], rep.findings


def test_drift_and_weak_signal_always_surface(monkeypatch, tmp_path):
    """AC-3/AC-6: drift (plan-declared, unimplemented) and a weak signal
    (referenced but failing) SURFACE and never block, even on M."""
    # drift: plan declares AC-1, nothing implements it.
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"),
                 _test_plan(("AC-1", "tests/test_gone.py::test_ac1_x")))
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason is None, "drift must not block"
    assert any(f.severity == acov.SURFACE for f in rep.findings), rep.findings

    # weak: a test references AC-2 but does not pass — not covered, surfaced, no block.
    _setup_check(monkeypatch, tmp_path, _spec("AC-2"),
                 _test_plan(("AC-2", "tests/test_x.py::test_ac2_thing")),
                 files={"test_x.py": "def test_ac2_thing():\n    assert False\n"},
                 passing=False)
    rep2 = acov.check("KLC-XXX", "M")
    assert rep2.block_reason is None, "a referencing-but-failing test is weak, not a miss"
    assert any(f.severity == acov.SURFACE for f in rep2.findings), rep2.findings


def test_operator_override_deferred_ac_coverage_downgrades_block_to_surface(monkeypatch, tmp_path):
    """AC-5: meta.deferred_ac_coverage downgrades an M/L miss block to a SURFACE
    advisory tagged deferred — surfaced, not silenced."""
    spec, tp, files = _locatable_miss_args()
    _setup_check(monkeypatch, tmp_path, spec, tp, files=files,
                 meta={"deferred_ac_coverage": True})
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason is None, "the override must lift the block"
    lines = acov.warn_lines(rep)
    assert any("deferred" in ln.lower() for ln in lines), lines


def test_degrades_on_missing_spec_or_testplan(monkeypatch, tmp_path):
    """AC-8: a missing/malformed spec.md or test-plan.md degrades to a SINGLE
    surfaced note, never blocks, never raises."""
    # No ACs in spec → degrade.
    _setup_check(monkeypatch, tmp_path, "", _test_plan())
    rep = acov.check("KLC-XXX", "M")
    assert rep.degraded is True
    assert rep.block_reason is None
    assert len(rep.findings) == 1 and rep.findings[0].severity == acov.SURFACE, rep.findings

    # ACs present but test-plan absent → degrade.
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"), "")
    rep2 = acov.check("KLC-XXX", "M")
    assert rep2.degraded is True
    assert rep2.block_reason is None
    assert len(rep2.findings) == 1, rep2.findings


def test_referenced_but_failing_test_not_counted_covered(monkeypatch, tmp_path):
    """AC-2: a test that references the AC but does not PASS is not counted as
    covering it (the invariant is collected + passing)."""
    _setup_check(monkeypatch, tmp_path, _spec("AC-1"),
                 _test_plan(("AC-1", "tests/test_x.py::test_ac1_thing")),
                 files={"test_x.py": "def test_ac1_thing():\n    assert False\n"},
                 passing=False)
    rep = acov.check("KLC-XXX", "M")
    states = {f.ac_id: f.state for f in rep.findings}
    assert states.get("AC-1") != acov.COVERED, states
    assert "AC-1" in states, states


def test_verify_passing_is_scoped_not_whole_suite(monkeypatch, tmp_path):
    """C-005: the passing check runs pytest scoped to the AC node-ids only — it
    never targets the whole suite."""
    calls = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(acov.subprocess, "run", fake_run)
    node = "tests/test_x.py::test_ac1_thing"
    acov._verify_passing([node], tests_root=tmp_path / "tests")
    assert calls, "pytest must be invoked"
    node_file = node.split("::", 1)[0]
    for cmd in calls:
        # Every invocation is scoped to the AC's own file/node — never a bare
        # whole-suite target.
        assert node_file in cmd or node in cmd, f"target must be scoped, got {cmd}"
        assert "tests" not in cmd and "tests/" not in cmd and "." not in cmd, \
            f"must not target the whole suite: {cmd}"


def test_verify_passing_isolates_unresolvable_node(tmp_path):
    """Codex MEDIUM regression: one unresolvable node-id in the batch must NOT
    drag a genuinely passing test down to not-passing (per-file isolation)."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_iso.py", "def test_ac1_pass():\n    assert True\n")
    real = "tests/test_iso.py::test_ac1_pass"
    absent = "tests/test_iso.py::test_ac9_absent"  # never resolvable
    res = acov._verify_passing([real, absent], tests_root=root)
    assert res.get(real) is True, f"the resolvable passing node must stay True: {res}"
    assert res.get(absent) is False, f"the unresolvable node is not passing: {res}"


def test_verify_passing_skip_is_not_passing(tmp_path):
    """FIX-3 (Codex P2): a @pytest.mark.skip test is collected and gives rc 0, but
    it did NOT pass — it must NOT count as passing (else a skip evades the gate)."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_skip.py",
           "import pytest\n\n@pytest.mark.skip(reason='x')\ndef test_ac1_skipped():\n    assert True\n")
    node = "tests/test_skip.py::test_ac1_skipped"
    res = acov._verify_passing([node], tests_root=root)
    assert res.get(node) is False, f"a skipped test is not passing: {res}"


def test_verify_passing_failed_substring_not_misattributed(tmp_path):
    """FIX-5 (fresh LOW): a FAILED line for `::test_ac1_extra` must not mark the
    passing `::test_ac1` failed via substring — match on exact node-id tokens."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_sub.py",
           "def test_ac1():\n    assert True\n\ndef test_ac1_extra():\n    assert False\n")
    passing_node = "tests/test_sub.py::test_ac1"
    failing_node = "tests/test_sub.py::test_ac1_extra"
    res = acov._verify_passing([passing_node, failing_node], tests_root=root)
    assert res.get(passing_node) is True, f"the passing node must stay True: {res}"
    assert res.get(failing_node) is False, f"the failing node must be False: {res}"


_PARAM_PARTIAL = (
    "import pytest\n\n"
    "@pytest.mark.parametrize('x', [1, 2])\n"
    "def test_ac1_param(x):\n"
    "    assert x == 1  # case x=1 PASSES, case x=2 FAILS\n"
)
_PARAM_ALL_PASS = (
    "import pytest\n\n"
    "@pytest.mark.parametrize('x', [1, 2])\n"
    "def test_ac1_param(x):\n"
    "    assert x in (1, 2)  # both cases PASS\n"
)


def test_verify_passing_parametrized_partial_fail_not_passing(tmp_path):
    """Codex P2: a parametrized test with ONE passing and ONE failing case must NOT
    count as passing — aggregate per base node (≥1 PASSED AND zero FAILED/ERROR)."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_p.py", _PARAM_PARTIAL)
    node = "tests/test_p.py::test_ac1_param"
    res = acov._verify_passing([node], tests_root=root)
    assert res.get(node) is False, f"a partially-failing param test is not passing: {res}"


def test_verify_passing_parametrized_all_pass_is_passing(tmp_path):
    """Counterpart: a parametrized test whose cases ALL pass IS passing."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_p.py", _PARAM_ALL_PASS)
    node = "tests/test_p.py::test_ac1_param"
    res = acov._verify_passing([node], tests_root=root)
    assert res.get(node) is True, f"an all-pass param test is passing: {res}"


def test_verify_passing_parametrized_id_with_space_passed(tmp_path):
    """FIX-B (Codex P2): a parametrized id can contain SPACES (`test_ac1[case one]`),
    which a naive split() mis-tokenises. A PASSING such node must be counted passing."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_sp.py",
           "import pytest\n\n@pytest.mark.parametrize('label', ['case one'])\n"
           "def test_ac1(label):\n    assert True\n")
    node = "tests/test_sp.py::test_ac1"
    res = acov._verify_passing([node], tests_root=root)
    assert res.get(node) is True, f"a passing space-in-id param node must be passing: {res}"


def test_verify_passing_parametrized_id_with_space_failed(tmp_path):
    """FIX-B counterpart: a FAILING node whose id contains a space is not passing."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_sp.py",
           "import pytest\n\n@pytest.mark.parametrize('label', ['case one'])\n"
           "def test_ac1(label):\n    assert False\n")
    node = "tests/test_sp.py::test_ac1"
    res = acov._verify_passing([node], tests_root=root)
    assert res.get(node) is False, f"a failing space-in-id param node is not passing: {res}"


def test_check_parametrized_partial_fail_is_weak_not_covered(tmp_path, monkeypatch):
    """Codex P2 end-to-end: on M, an AC whose only test is a partially-failing
    parametrized test is WEAK (surfaced), NOT covered — the real failing case is
    not hidden by its passing sibling."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_p.py", _PARAM_PARTIAL)
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_load_texts",
                        lambda t: (_spec("AC-1"),
                                   _test_plan(("AC-1", "tests/test_p.py::test_ac1_param"))))
    monkeypatch.setattr(acov, "_read_meta_ro", lambda t: {})
    rep = acov.check("KLC-XXX", "M")  # real _verify_passing
    states = {f.ac_id: f.state for f in rep.findings}
    assert states.get("AC-1") == acov.WEAK, states
    assert rep.block_reason is None, "a partially-failing param test is weak, not a hard miss"


def test_check_skip_only_ac_is_weak_not_covered(tmp_path, monkeypatch):
    """FIX-3 end-to-end: an AC whose only test is @pytest.mark.skip is WEAK (surfaced),
    NOT covered — and on M it therefore does not silently pass the gate."""
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_skip.py",
           "import pytest\n\n@pytest.mark.skip(reason='x')\ndef test_ac1_skipped():\n    assert True\n")
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_load_texts",
                        lambda t: (_spec("AC-1"),
                                   _test_plan(("AC-1", "tests/test_skip.py::test_ac1_skipped"))))
    monkeypatch.setattr(acov, "_read_meta_ro", lambda t: {})
    rep = acov.check("KLC-XXX", "M")  # real _verify_passing (runs the one skip test)
    states = {f.ac_id: f.state for f in rep.findings}
    assert states.get("AC-1") == acov.WEAK, states
    assert rep.block_reason is None, "a skip is weak/surface, not a hard miss block"


# ---------------------------------------------------------------------------
# step-3 — the can_complete_build integration (block path + surface path)
# ---------------------------------------------------------------------------

_BUILD_LOG = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Evidence

```
$ python3 -m pytest tests/ -q
5 passed in 0.04s
```
"""


def _make_full_build_ticket(tmp_path, ticket, track, spec, test_plan, meta_extra=None):
    """A build ticket satisfying the Evidence gate, with spec/test-plan for AC coverage."""
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": track,
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    meta.update(meta_extra or {})
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(_BUILD_LOG.format(ticket=ticket), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(spec, encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(test_plan, encoding="utf-8")
    return ticket_dir


def _no_tests_root(monkeypatch, tmp_path):
    """Point the AC-coverage scan at an empty dir so it never touches the real suite,
    and pin the changed-files supplement to an AVAILABLE empty set (the tmp
    PROJECT_ROOT is not a git repo) so candidates come deterministically from the plan
    and a confident miss can still block."""
    root = tmp_path / "empty_tests"
    root.mkdir()
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())


def test_can_complete_build_blocks_on_ml_miss(tmp_path, monkeypatch):
    """AC-4/AC-9: an M ticket with a PLAN-SUBSTANTIATED uncovered AC blocks the build
    ack (AC-1's declared file exists and is scanned but has no AC-1 test)."""
    from core.skills.phase_completion import can_complete_build
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_x.py", "def test_ac2_x():\n    assert True\n")  # AC-2 only, no AC-1
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())
    _make_full_build_ticket(tmp_path, "KLC-CB1", "M", _spec("AC-1", "AC-2"),
                            _test_plan(("AC-1", "tests/test_x.py::test_ac1_x"),
                                       ("AC-2", "tests/test_x.py::test_ac2_x")))
    ok, msg = can_complete_build("KLC-CB1")
    assert not ok, "a plan-substantiated coverage miss must block the build ack"
    assert "AC coverage" in msg, msg


def test_can_complete_build_surfaces_s_miss_and_drift(tmp_path, monkeypatch):
    """AC-7/AC-9: on S a miss/drift surfaces as an advisory but does not block."""
    from core.skills.phase_completion import can_complete_build
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _no_tests_root(monkeypatch, tmp_path)
    _make_full_build_ticket(
        tmp_path, "KLC-CB2", "S", _spec("AC-1", "AC-2"),
        _test_plan(("AC-2", "tests/test_gone.py::test_ac2_x")))
    ok, msg = can_complete_build("KLC-CB2")
    assert ok, f"S must not block, got {msg!r}"
    assert "ac-coverage" in msg, msg


def test_can_complete_build_override_unblocks_ml_miss(tmp_path, monkeypatch):
    """AC-5/AC-9: meta.deferred_ac_coverage lifts the M/L block and the deferred
    miss is surfaced in the message."""
    from core.skills.phase_completion import can_complete_build
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_x.py", "def test_ac2_x():\n    assert True\n")
    monkeypatch.setattr(acov, "_tests_root", lambda: root)
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())
    _make_full_build_ticket(tmp_path, "KLC-CB3", "M", _spec("AC-1", "AC-2"),
                            _test_plan(("AC-1", "tests/test_x.py::test_ac1_x"),
                                       ("AC-2", "tests/test_x.py::test_ac2_x")),
                            meta_extra={"deferred_ac_coverage": True})
    ok, msg = can_complete_build("KLC-CB3")
    assert ok, f"the override must lift the block, got {msg!r}"
    assert "deferred" in msg.lower(), msg


def test_can_complete_build_degrades_when_skill_raises(tmp_path, monkeypatch):
    """AC-8/degrade-not-fail: if the coverage skill raises, can_complete_build does
    not crash or block — the other checks still decide the ack."""
    from core.skills.phase_completion import can_complete_build
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    def boom(*a, **k):
        raise RuntimeError("coverage exploded")

    monkeypatch.setattr(acov, "check", boom)
    _make_full_build_ticket(tmp_path, "KLC-CB4", "M", _spec("AC-1"), _test_plan())
    ok, msg = can_complete_build("KLC-CB4")
    assert ok, f"a coverage-skill crash must not block the ack, got {msg!r}"


def test_probe_persist_false_runs_no_pytest(tmp_path, monkeypatch):
    """FIX-2 (Codex MEDIUM): the read-only probe path (persist=False — remind /
    gate_policy on every prompt) must NOT spawn pytest / execute the ticket's tests;
    only the static AC→file classification runs. The real ack (persist=True) runs it."""
    from core.skills.phase_completion import can_complete
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    root = tmp_path / "tests"
    root.mkdir()
    _write(root, "test_x.py", "def test_ac1_thing():\n    assert True\n")
    monkeypatch.setattr(acov, "_tests_root", lambda: root)

    calls = []

    def rec(node_ids, repo=None, tests_root=None):
        calls.append(list(node_ids))
        return {n: True for n in node_ids}

    monkeypatch.setattr(acov, "_verify_passing", rec)
    _make_full_build_ticket(tmp_path, "KLC-CB5", "M", _spec("AC-1"),
                            _test_plan(("AC-1", "tests/test_x.py::test_ac1_thing")))

    ok_probe, _ = can_complete("KLC-CB5", "build", persist=False)
    assert calls == [], "the probe path must not spawn pytest"
    assert ok_probe, "static classification finds the referencing test → no block on probe"

    ok_ack, _ = can_complete("KLC-CB5", "build", persist=True)
    assert calls, "the real ack path must run the scoped pytest verification"


def test_ac_covered_only_by_own_plan_or_changed_file(monkeypatch, tmp_path):
    """FIX (Codex P2, false-COVERED): AC ids restart per ticket, so a `test_ac1` in a
    file declared for a DIFFERENT AC must NOT cover AC-1. AC-1's own planned file has
    no test_ac1; AC-2's file has an unrelated test_ac1 → AC-1 is NOT covered → the
    M/L gate blocks the genuinely-missing AC-1 acceptance test."""
    _setup_check(
        monkeypatch, tmp_path, _spec("AC-1", "AC-2"),
        _test_plan(("AC-1", "tests/test_one.py::test_ac1_x"),
                   ("AC-2", "tests/test_two.py::test_ac2_y")),
        files={
            "test_one.py": "def test_other():\n    assert True\n",       # AC-1's file: no test_ac1
            "test_two.py": ("def test_ac1_stray():\n    assert True\n\n"  # AC-2's file: stray test_ac1
                            "def test_ac2_y():\n    assert True\n"),
        })
    rep = acov.check("KLC-XXX", "M")
    assert rep.block_reason and "AC-1" in rep.block_reason, (
        "a test_ac1 in AC-2's file must not cover AC-1", [f.__dict__ for f in rep.findings])
    # AC-2 is genuinely covered by its own file's test_ac2_y.
    assert not any(f.ac_id == "AC-2" for f in rep.findings), rep.findings


def test_path_allows_distinguishes_monorepo_same_basename():
    """FIX (Codex P2, false-COVERED): full-path (suffix-tolerant) matching distinguishes
    nested monorepo files that share a basename — a stray test in another package's
    same-named file must not cross-cover."""
    assert acov._path_allows("pkg_a/tests/test_api.py", {"pkg_a/tests/test_api.py"})
    assert not acov._path_allows("pkg_b/tests/test_api.py", {"pkg_a/tests/test_api.py"})
    assert acov._path_allows("tests/test_x.py", {"tests/test_x.py"})  # exact flat
    # Two DIFFERENT multi-segment paths sharing only a tail must NOT cross-match
    # (a stray test in pkg_a must not cover a root-planned tests/test_api.py):
    assert not acov._path_allows("pkg_a/tests/test_api.py", {"tests/test_api.py"})
    # Basename tolerance applies ONLY when the plan/ node side is a BARE filename:
    assert acov._path_allows("pkg_a/tests/test_api.py", {"test_api.py"})
    assert acov._path_allows("tests/test_api.py", {"test_api.py"})


def test_can_complete_build_surfaces_when_coverage_check_raises(tmp_path, monkeypatch):
    """FIX (Codex P2, observability): if the AC-coverage check raises, can_complete_build
    must NOT silently skip — it surfaces a degraded advisory so operators know coverage
    was unverified (and still never blocks: degrade-not-fail)."""
    from core.skills.phase_completion import can_complete_build
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_full_build_ticket(tmp_path, "KLC-CBX", "M", _spec("AC-1"),
                            _test_plan(("AC-1", "tests/test_x.py::test_ac1_x")))
    def _boom(*a, **k):
        raise RuntimeError("import/plugin surprise")
    monkeypatch.setattr(acov, "check", _boom)
    ok, msg = can_complete_build("KLC-CBX")
    assert ok, "a coverage-check crash must NOT block the build ack (degrade-not-fail)"
    assert "ac-coverage" in msg and "did not run" in msg, (
        "a silently-skipped coverage gate must surface a degraded advisory", msg)


def test_check_honors_repo_override_for_bare_test_path(tmp_path, monkeypatch):
    """FIX (Codex P2): with repo= given AND a tests-root-relative BARE plan location
    (`test_x.py`, no `tests/` prefix), the scanner must resolve it under <repo>/tests,
    not PROJECT_ROOT's tests dir — else the real test there is never scanned."""
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)                 # PROJECT_ROOT tree: empty
    other = tmp_path / "other"
    (other / "tests").mkdir(parents=True)
    _write(other / "tests", "test_ac1.py", "def test_ac1_x():\n    assert True\n")
    monkeypatch.setattr(acov, "_tests_root", lambda: proj / "tests")
    monkeypatch.setattr(acov, "_load_texts",
                        lambda t: (_spec("AC-1"),
                                   _test_plan(("AC-1", "test_ac1.py::test_ac1_x"))))  # BARE
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())
    monkeypatch.setattr(acov, "_read_meta_ro", lambda t: {"track": "M"})
    rep = acov.check("KLC-XXX", "M", repo=other)
    assert rep.block_reason is None, (
        "the bare plan location under the override repo/tests must be scanned → covered",
        [f.__dict__ for f in rep.findings])
    assert not any(f.ac_id == "AC-1" for f in rep.findings), rep.findings
