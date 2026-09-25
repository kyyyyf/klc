#!/usr/bin/env python3
"""tests/test_klc112_prompt_honesty.py — KLC-112 prompts name only real inputs.

The discovery and design prompts promised a `discovery-context` / `design-context`
bundle that no code produces. This file pins the rewritten text (Option B,
prompts-only honesty, operator 2026-09-25) and, from step-4, adds a mechanical
whole-tree scan so the defect class cannot silently return.
"""
from __future__ import annotations

import ast
import difflib
import os
import re
import subprocess
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parent.parent
DISCOVERY = FW / "core" / "agents" / "discovery.md"
DESIGN = FW / "core" / "agents" / "design.md"
GOLDEN = FW / "tests" / "fixtures" / "klc118" / "golden" / "design_prompt.md"
GOLDEN_REL = "tests/fixtures/klc118/golden/design_prompt.md"
BASE_SHA = "065fdfc"  # main before this ticket (D-203)
PROCESS = FW / "docs" / "process.md"
README = FW / "README.md"

# --------------------------------------------------------------------------- #
# step-4 — whole-tree honesty scan, byte ceiling, hermeticity, framework-only
# --------------------------------------------------------------------------- #

BUNDLE_RE = re.compile(r"\b\d{2}-[A-Za-z][\w.-]*\.md\b")   # letter after NN- (spec D-101)
BUNDLE_LITERALS = ("discovery-context", "design-context", "tickets/archive",
                   "pending KLC-112", ".klc/config/discovery.yml")
SCANNED = [*(FW / "core/agents").glob("*.md"), *(FW / "core/agents/review").glob("*.md"),
          *(FW / "klc-plugin/agents").glob("*.md"), FW / "docs/process.md", FW / "README.md"]

LANG_RE = re.compile(r"\b(python|typescript|javascript|java|kotlin|golang|rust|ruby|"
                     r"php|swift|scala|csharp)\b", re.I)           # no bare "go" (D-207)
FRAMEWORK_PREFIXES = (".klc/tickets/", ".klc/index/", "core/", "docs/adr/", "design/")
FRAMEWORK_FILES = {"raw.md", "CLAUDE.md", "spec.md", "test-plan.md", "meta.json",
                   "retrieval_trace.json", "modules.json", "module_edges.json",
                   "retrospective.md", "models.yml"}
BUILD_LOG_REL = ".klc/tickets/KLC-112/build-log.md"   # the one AC-14 exception (D-204)


def _read_build_log() -> str:
    root = Path(os.environ.get("PROJECT_ROOT") or FW)
    path = root / BUILD_LOG_REL
    if not path.is_file():
        pytest.skip("build-log.md is gitignored ticket state; absent in a clean checkout")
    return path.read_text(encoding="utf-8")


def _bundle_hits(text: str) -> list[str]:
    return [m.group(0) for m in BUNDLE_RE.finditer(text)] + [s for s in BUNDLE_LITERALS if s in text]


def _non_framework_refs(text: str) -> list[str]:
    hits = [m.group(0) for m in LANG_RE.finditer(text)]
    for tok in re.findall(r"`([^`\n]+)`", text):
        pathish = "/" in tok or re.search(r"\.(md|json|py|ya?ml)$", tok)
        if pathish and not (tok.startswith(FRAMEWORK_PREFIXES) or tok in FRAMEWORK_FILES):
            hits.append(tok)
    return hits


def test_klc112_honesty_scan_clean_on_shipped_tree():
    """AC-8: the mechanical scan finds no bundle name or archive path in the
    real prompts, plugin copies or docs."""
    offenders = []
    for path in SCANNED:
        hits = _bundle_hits(_read(path))
        if hits:
            offenders.append(f"{path.relative_to(FW)}: {hits}")
    assert not offenders, offenders


def test_klc112_honesty_scan_flags_fixture_prompt_naming_bare_bundle_tokens(tmp_path):
    """AC-9: the scanner sees bare names that prompt_honesty.scan cannot."""
    fixture = tmp_path / "fake.md"
    fixture.write_text("Read `40-related.md` from `design-context/` first.\n", encoding="utf-8")
    assert set(_bundle_hits(_read(fixture))) == {"40-related.md", "design-context"}


def test_discovery_and_design_combined_bytes_at_or_below_41286_baseline():
    """AC-11: discovery.md + design.md combined bytes stay at or below the
    41 286-byte baseline measured at main 065fdfc (regression pin, already
    true after steps 1-3, D-207)."""
    total = DISCOVERY.stat().st_size + DESIGN.stat().st_size
    assert total <= 41_286, (
        f"discovery.md + design.md is {total} bytes, over the 41 286-byte "
        f"baseline measured at main 065fdfc (KLC-112 AC-11); shrink the "
        f"Inputs/fallback text — do not raise this baseline without an "
        f"operator decision"
    )


def test_discovery_names_the_modules_json_path_exactly_once_not_duplicated_under_reachable_on_demand():
    """AC-1 (review round 1, MEDIUM — code + external reviewers): the
    `.klc/index/modules.json` path is named exactly once in discovery.md,
    inside ## Inputs, not duplicated under the 'Reachable on demand but
    expensive' bullet list with opposite framing."""
    text = _read(DISCOVERY)
    assert text.count(".klc/index/modules.json") == 1, text.count(".klc/index/modules.json")
    inputs_section = _heading_section(text, "## Inputs")
    assert ".klc/index/modules.json" in inputs_section
    reachable = _paragraph(text, "Reachable on demand but expensive:")
    assert ".klc/index/modules.json" not in reachable


def test_new_honesty_tests_read_only_real_prompts_or_tmp_path_fixtures():
    """AC-14: every file read goes through _read or _read_build_log; _read
    refuses .klc/ (regression pin, already true after step 1, D-207)."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    readers = {"read_text", "read_bytes", "open"}
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        if fn.name in {"_read", "_read_build_log",
                       "test_new_honesty_tests_read_only_real_prompts_or_tmp_path_fixtures"}:
            continue
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            name = getattr(call.func, "attr", getattr(call.func, "id", ""))
            assert name not in readers, f"AC-14: {fn.name} reads a file directly"
    with pytest.raises(AssertionError):
        _read(FW / ".klc" / "index" / "modules.json")       # fail-closed arm


def test_rewritten_sections_name_only_framework_artefacts_no_language_or_profile_path():
    """AC-15: the rewritten Inputs/fallback sections name only framework
    artefacts — no language, profile or project-specific path. Scans the
    UNION of discovery.md's ## Inputs and ## Planning slice sections
    (review round 1, MEDIUM — drift reviewer: the Degraded-trace paragraph
    and the retrospective bullet live under Planning slice, not Inputs, so
    a scan of Inputs alone never sees them); design.md is unchanged (its
    fallback text lives under ## Inputs already)."""
    disc_text = _read(DISCOVERY)
    disc_sections = (_heading_section(disc_text, "## Inputs")
                     + _heading_section(disc_text, "## Planning slice (read first, KLC-073)"))
    design_section = _heading_section(_read(DESIGN), "## Inputs")
    offenders = _non_framework_refs(disc_sections) + _non_framework_refs(design_section)
    assert not offenders, offenders


def test_framework_artefact_scan_flags_a_language_name_and_a_non_framework_path_in_a_fixture():
    """AC-15 negative twin: the same scan helper flags a language name and a
    non-framework path in a fixture, proving AC-15's positive row is not
    vacuous (test-plan-review F-1)."""
    fixture_text = "Read `Python` sources under `src/app/main.py` first.\n"
    hits = _non_framework_refs(fixture_text)
    assert "Python" in hits
    assert "src/app/main.py" in hits


def test_framework_artefact_scan_flags_a_language_name_in_the_planning_slice_section_of_a_fixture():
    """AC-15 negative twin (review round 1, MEDIUM — drift reviewer): a
    language name planted in a fixture's Planning-slice section (not
    Inputs) must still be flagged, proving the widened AC-15 guard actually
    covers discovery.md's Planning-slice section rather than passing
    vacuously because nothing in it is ever scanned."""
    fixture = ("## Inputs\n\n- `raw.md`\n\n"
              "## Planning slice (read first, KLC-073)\n\n"
              "Read `Python` sources under `src/app/main.py` first.\n\n"
              "## Steps\n")
    section = _heading_section(fixture, "## Planning slice (read first, KLC-073)")
    hits = _non_framework_refs(section)
    assert "Python" in hits
    assert "src/app/main.py" in hits


def test_build_log_records_before_after_bytes_and_totals():
    """AC-16: build-log.md records prompt before/after bytes, plugin, paste
    and dispatch totals."""
    text = _read_build_log()          # pytest.skip when absent (clean checkout, D-204)
    after_disc = DISCOVERY.stat().st_size      # stat, not a file read (AC-14 guard)
    after_design = DESIGN.stat().st_size
    plugin_total = sum(f.stat().st_size for f in (FW / "klc-plugin" / "agents").glob("*.md"))
    assert re.search(rf"discovery\.md: 21836 -> {after_disc}\b", text)
    assert re.search(rf"design\.md: 19450 -> {after_design}\b", text)
    assert re.search(rf"klc-plugin/agents total: {plugin_total}\b", text)
    paste_match = re.search(r"paste_total: (\d+)", text)
    assert paste_match, "paste_total not recorded"
    assert 70_628.7 <= int(paste_match.group(1)) <= 78_063.3
    dispatch_match = re.search(r"dispatch_total: (\d+)", text)
    assert dispatch_match, "dispatch_total not recorded"
    assert int(dispatch_match.group(1)) <= 6500


def _read(path: Path) -> str:
    """The only file reader (AC-14): repo files outside .klc/, or tmp_path fixtures."""
    p = path.resolve()
    assert not p.is_relative_to(FW / ".klc"), f"AC-14: refusing to read {p}"
    return p.read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _heading_section(text: str, heading: str) -> str:
    start = text.index(heading + "\n")
    end = text.find("\n## ", start + len(heading))
    return text[start:end if end > 0 else None]


def _paragraph(text: str, marker: str) -> str:
    start = text.index(marker)
    end = text.find("\n\n", start)
    return text[start:end if end > 0 else None]


# --------------------------------------------------------------------------- #
# step-1 — discovery.md names only real inputs and a bounded degraded fallback
# --------------------------------------------------------------------------- #

def test_discovery_inputs_section_names_only_real_files():
    """AC-1: discovery.md's Inputs section names only the four real files."""
    text = _read(DISCOVERY)
    section = _norm(_heading_section(text, "## Inputs"))
    for token in ("`raw.md`", "root `CLAUDE.md`",
                  "`.klc/tickets/<KEY>/retrieval_trace.json`",
                  "`.klc/index/modules.json`"):
        assert token in section, token
    for bundle_name in ("00-raw.md", "10-root-CLAUDE.md", "20-module-docs.md",
                        "40-related.md", "50-external-docs.md"):
        assert bundle_name not in section, bundle_name
    assert "pending KLC-112" not in text


def test_discovery_degraded_trace_rule_bounds_fallback_to_three_modules():
    """AC-2: every degraded trigger is named; the fallback is capped at 3 table modules."""
    text = _read(DISCOVERY)
    assert "fall back to the full context bundle below" not in text
    para = _norm(_paragraph(text, "**Degraded trace"))
    for token in ("absent", 'status:"unavailable"', 'confidence:"low"',
                  'mode:"name-match-only"', "degraded_inputs", "at most 3",
                  "modules.json", "open only files those entries list"):
        assert token in para, token


def test_discovery_degraded_trace_rule_instructs_quoting_trace_fields_in_spec_problem_context():
    """AC-3: the degraded-trace rule instructs quoting the trace fields and the
    fallback modules picked in spec.md's Problem / Context section."""
    text = _read(DISCOVERY)
    para = _norm(_paragraph(text, "**Degraded trace"))
    for token in ("status", "confidence", "mode", "degraded_inputs",
                  "spec.md", "Problem / Context", "modules you picked"):
        assert token in para, token


def test_discovery_related_ticket_rule_points_at_retrospective_capped_at_five():
    """AC-4: related-ticket lessons point at retrospective.md of archived
    tickets, capped at 5, sharing kind or an affected module."""
    text = _read(DISCOVERY)
    para = _norm(_paragraph(text, "`.klc/tickets/<KEY>/retrospective.md`"))
    for token in ("at most 5", 'phase:"archived"', "kind",
                  "affected module"):
        assert token in para, token


def test_discovery_degraded_trace_rule_forbids_repository_scan():
    """AC-2 edge twin: the degraded-trace block explicitly forbids a
    repository scan, and grants no open-ended read."""
    text = _read(DISCOVERY)
    para = _norm(_paragraph(text, "**Degraded trace"))
    assert "do not scan the repository" in para.lower()


def test_discovery_has_no_tickets_archive_path_or_40_related_reference():
    """AC-4 edge twin: no .klc/tickets/archive/ path and no 40-related.md
    reference survives in discovery.md."""
    text = _read(DISCOVERY)
    assert ".klc/tickets/archive" not in text
    assert "40-related.md" not in text


# --------------------------------------------------------------------------- #
# step-2 — design.md names spec, test plan and ADRs, and bounds its fallback
# --------------------------------------------------------------------------- #

def test_design_inputs_section_names_spec_test_plan_and_optional_adrs():
    """AC-5: design.md's Inputs section names spec.md, test-plan.md and
    optional related ADRs in place of design-context/ and its numbered names."""
    text = _read(DESIGN)
    section = _norm(_heading_section(text, "## Inputs"))
    for token in ("`spec.md`", "`test-plan.md`", "`docs/adr/*`",
                  "`design/adr.md`"):
        assert token in section, token
    for bundle_name in ("design-context/", "00-spec.md", "10-test-plan.md",
                        "20-related-adrs.md"):
        assert bundle_name not in section, bundle_name


def test_design_degraded_trace_fallback_bounds_to_affected_modules_and_depth_one_neighbours():
    """AC-6: the design fallback covers all trace triggers and bounds itself
    to meta.affected_modules and their depth-1 module_edges neighbours."""
    text = _read(DESIGN)
    assert "Skip it when absent or" not in text
    para = _norm(_paragraph(text, "When the trace is"))
    for token in ("absent", 'status:"unavailable"', 'confidence:"low"',
                  "degraded_inputs", "meta.affected_modules",
                  "depth-1", "module_edges"):
        assert token in para, token


def test_design_degraded_trace_fallback_forbids_repository_scan():
    """AC-6 edge twin: the design fallback explicitly forbids a repository scan."""
    text = _read(DESIGN)
    para = _norm(_paragraph(text, "When the trace is"))
    assert "do not scan the repository" in para.lower()


def test_discovery_and_design_contain_degraded_inputs_and_no_scan_clause_and_modules_json():
    """AC-10: both prompts contain degraded_inputs and a no-repository-scan
    sentence, and discovery.md names modules.json."""
    for path in (DISCOVERY, DESIGN):
        text = _read(path)
        assert "degraded_inputs" in text, path.name
        assert "do not scan the repository" in _norm(text).lower(), path.name
    assert "modules.json" in _read(DISCOVERY)


def test_discovery_and_design_degraded_rules_cover_an_absent_trace_not_only_degraded_fields():
    """Edge case (AC-2, AC-6): both degraded-trace rules trigger on an absent
    trace as its own condition, not only on a present-but-degraded one."""
    disc_para = _norm(_paragraph(_read(DISCOVERY), "**Degraded trace"))
    design_para = _norm(_paragraph(_read(DESIGN), "When the trace is"))
    assert "absent" in disc_para
    assert "absent" in design_para


def _golden_hunks(old: list[str], new: list[str]):
    sm = difflib.SequenceMatcher(None, old, new)
    return [op for op in sm.get_opcodes() if op[0] != "equal"]


def test_design_golden_diff_confined_to_inputs_and_fallback_hunks():
    """AC-12: the re-frozen golden differs from the base only inside the
    Inputs / degraded-fallback span."""
    res = subprocess.run(["git", "-C", str(FW), "show", f"{BASE_SHA}:{GOLDEN_REL}"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"base commit {BASE_SHA} unavailable (shallow clone?)")
    old = res.stdout.splitlines()
    new = _read(GOLDEN).splitlines()
    hunks = _golden_hunks(old, new)
    assert hunks, "AC-12: the golden was not re-frozen"
    lo_o = old.index("## Inputs (from `design-context/`)")
    hi_o = old.index("## Symbol verification")
    lo_n = new.index("## Inputs")
    hi_n = new.index("## Symbol verification")
    for _tag, i1, i2, j1, j2 in hunks:
        assert lo_o <= i1 and i2 <= hi_o and lo_n <= j1 and j2 <= hi_n


# --------------------------------------------------------------------------- #
# step-3 — process.md and README describe real inputs and where archived
# tickets live
# --------------------------------------------------------------------------- #

def test_docs_process_and_readme_describe_real_inputs_and_archived_ticket_location():
    """AC-7: docs/process.md describes the real discovery inputs and the
    bounded degraded fallback, and it plus README.md state that an archived
    ticket stays in .klc/tickets/<KEY>/ with meta.phase set to archived."""
    process_text = _norm(_read(PROCESS))
    for token in ("raw.md", "CLAUDE.md", "retrieval_trace.json",
                  "modules.json", "degraded", "at most 3",
                  "do not scan the repository", "retrospective.md",
                  "at most 5", ".klc/tickets/<KEY>/", "phase", "archived"):
        assert token in process_text, token
    # README's AC-7 scope is the directory tree only (D-208): it states the
    # ticket lives at tickets/<KEY>/ (archived too), not the discovery inputs.
    readme_text = _norm(_read(README))
    assert "tickets/<KEY>/" in readme_text
    assert "archived too" in readme_text


def test_docs_and_readme_no_longer_claim_write_prompt_card_loads_a_bundle():
    """AC-7 negative twin: no bundle-loading claim and no tickets/archive
    path survive in docs/process.md or README.md."""
    for path in (PROCESS, README):
        text = _read(path)
        assert "tickets/archive" not in text, path.name
        for para in text.split("\n\n"):
            assert not ("write_prompt_card" in para and "bundle" in para.lower()), para[:80]


# --------------------------------------------------------------------------- #
# build-time addendum (D-112-5) — AC-13 gate-visibility pin
# --------------------------------------------------------------------------- #

def test_prompt_honesty_scan_stays_clean_after_the_rewrite():
    """AC-13: prompt_honesty.scan() stays [] on the rewritten tree, without a
    new ALLOWLIST entry. This is a regression pin, not a duplicate of the
    real AC-13 assertions: tests/test_klc113_prompt_honesty.py and
    tests/test_intake_retrieval.py (re-run unmodified per test-plan.md)
    carry those; this test exists only so core/skills/ac_test_coverage.py's
    per-ticket AC-coverage gate has a KLC-112-tagged referencing node for
    AC-13, since the existing suites above predate this ticket and cannot
    themselves carry a KLC-112 AC token (D-112-5)."""
    import sys
    sys.path.insert(0, str(FW / "core" / "skills"))
    import prompt_honesty as ph
    assert ph.scan() == []
