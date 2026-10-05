"""KLC-101 — docs consolidation to three top-level docs.

The ~19 pure-prose docs under `docs/` (roles, glossary, process-artifacts,
process-metrics, epics, planning-eval, callgraph-backends, dual-remote, the
happy-path guide, and all of `docs/phases/*`) are ABSORBED into three navigable
docs — root `README.md`, `docs/process.md` (process & detailed usage), and the
new `docs/architecture.md` (key decisions + cross-cutting invariants) — then
DELETED. The machine-coupled docs (constitution / coverage-taxonomy / tracks /
severity-rubric), `docs/adr/`, and the dated epic plans are KEPT.

These assertions are the safety net: they pin the three docs' load-bearing
content and — the load-bearing part — enforce that NO reference to a deleted doc
survives anywhere an agent prompt, the plugin, the README, scripts, or config can
still cite it. The dead-doc matcher is deliberately TWO-CLASS (see
`_deleted_doc_hits`): distinctive prose basenames are matched both as
`docs/<name>` and bare `<name>.md`; the phase docs are matched ONLY by their
`docs/phases/<name>` path form, because their bare basenames
(design.md / discovery.md / review.md / …) collide with KEPT `core/agents/`
filenames and reviewer artifacts and would make the net un-green-able.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

# Stable GitHub-slug anchors the rewired agent links target. The per-phase
# anchors (#intake … #learn) plus the absorbed-section anchors
# (#tracks #roles #glossary #artifacts #metrics #epics).
PROCESS_ANCHORS = [
    "intake", "discovery", "design", "acceptance-test-plan",
    "build", "review",
    "manual", "integrate", "observe", "learn",
    "tracks", "roles", "glossary", "artifacts", "metrics", "epics",
]


def _heading_slugs(md: str) -> set[str]:
    """GitHub-style slug of every ATX heading line."""
    return {
        line.strip("# ").strip().lower().replace(" ", "-")
        for line in md.splitlines() if line.startswith("#")
    }


# --- the TWO-CLASS dead-doc matcher (design/options.md) -------------------
#
# DISTINCTIVE prose basenames are safe to match both as `docs/<name>` AND bare
# `<name>.md`: the bare form is what catches discovery.md's `process-artifacts.md`
# reference (no `docs/` prefix). None of these basenames collide with a KEPT file.
_DISTINCTIVE = [
    "process-artifacts", "process-metrics", "roles", "glossary", "planning-eval",
    "dual-remote-mr-pr-workflow", "callgraph-backends", "happy-path", "epics",
]
# PHASE docs are matched ONLY by their `docs/phases/<name>` PATH form. Their bare
# basenames (design.md / discovery.md / review.md / review-lite.md / …) collide
# with KEPT core/agents/ filenames and reviewer artifacts (spec-review.md,
# test-plan-review.md), so a bare match would be un-green-able.
_PHASE = [
    "intake", "discovery", "design", "acceptance-test-plan", "detailed-test-plan",
    "xs-build", "build", "review", "review-lite", "manual", "integrate",
    "observe", "learn",
]


def _deleted_doc_hits(text: str) -> list[str]:
    """Every reference to a DELETED doc in `text`, using the two-class scheme."""
    hits = [d for d in _DISTINCTIVE
            if f"docs/{d}" in text or f"{d}.md" in text]
    hits += [f"docs/phases/{p}" for p in _PHASE if f"docs/phases/{p}" in text]
    return hits


# ---------------------------------------------------------------------------
# step-1 — docs/architecture.md (decisions + cross-cutting invariants)
# ---------------------------------------------------------------------------

def test_architecture_doc_has_invariants():
    """AC-3: architecture.md names each cross-cutting invariant + maps over
    docs/adr/ and links the kept machine-coupled docs."""
    t = (DOCS / "architecture.md").read_text("utf-8")
    for k in ("C-001", "ReviewKind", "klc-state", "dual-remote", "plugin-gen",
              "degrade-not-fail", "no-fork", "fail-open", "surface-only",
              "docs/adr/"):
        assert k in t, k
    # Links the kept machine-coupled docs (doc #3 maps to them, not re-authors).
    for kept in ("constitution.md", "coverage-taxonomy.md", "tracks.md",
                 "severity-rubric.md"):
        assert kept in t, f"architecture.md must link the kept doc {kept}"


# ---------------------------------------------------------------------------
# step-2 — consolidated docs/process.md (absorb the prose; stable anchors)
# ---------------------------------------------------------------------------

def test_process_doc_has_phase_anchors():
    """AC-2: process.md carries every stable anchor the rewire mapping targets —
    the 13 per-phase slugs plus tracks/roles/glossary/artifacts/metrics/epics."""
    slugs = _heading_slugs((DOCS / "process.md").read_text("utf-8"))
    for anchor in PROCESS_ANCHORS:
        assert any(anchor == s or anchor in s for s in slugs), anchor


def test_process_doc_absorbed_markers():
    """AC-2: process.md absorbed the substance of the prose docs — the marker
    content each source carried is now present in the single doc."""
    t = (DOCS / "process.md").read_text("utf-8")
    for marker in (
        "Product Manager",          # roles.md
        "Framework operator",       # roles.md
        "TDD loop",                 # glossary.md / build
        "build/steps.json",         # process-artifacts.md (options-lite.md retired, KLC-176)
        "cheap_escape_rate",        # process-metrics.md
        "meta.blocked_by",          # epics.md
        "public mirror",            # dual-remote workflow
    ):
        assert marker in t, f"process.md must absorb the marker {marker!r}"
    # The RETAINED "Independent … review" section the reviewers link to (§).
    assert "Independent spec" in t, "process.md must retain the Independent review section"


def test_process_doc_retains_doc_honesty_strings():
    """AC-2 / AC-9: the two doc-honesty tests (klc093/094) keep passing — the
    consolidated process.md still names the findings files + build/assess wiring."""
    t = (DOCS / "process.md").read_text("utf-8")
    for s in ("findings.json", "test-plan-review",
              "impl-plan-review",
              "spec-review", "impl.md"):
        assert s in t, s


# ---------------------------------------------------------------------------
# step-3 — root README.md (one install section; links the docs; no dead links)
# ---------------------------------------------------------------------------

def test_readme_has_install_and_links():
    """AC-1: README has ONE install section and links the other two docs plus an
    end-to-end usage scenario."""
    t = (REPO / "README.md").read_text("utf-8")
    low = t.lower()
    assert "## install" in low, "README must carry a single Install section"
    assert "docs/process.md" in t, "README must link docs/process.md"
    assert "docs/architecture.md" in t, "README must link docs/architecture.md"
    # A concrete end-to-end scenario: the intake→go walk.
    assert "klc intake" in t and "klc go" in t, (
        "README must show an end-to-end usage scenario"
    )


def test_readme_no_deleted_links():
    """AC-5: README keeps no link to a deleted prose doc."""
    t = (REPO / "README.md").read_text("utf-8")
    for d in ("process-artifacts.md", "process-metrics.md", "epics.md",
              "roles.md", "glossary.md"):
        assert d not in t, d


# ---------------------------------------------------------------------------
# step-4 — rewire the 13 agent refs → process.md anchors (+ regen plugin)
# ---------------------------------------------------------------------------

# The 12 distinct anchors the 13 rewired refs target (two refs both point at
# #acceptance-test-plan). Each must resolve to a real heading slug in process.md.
_REWIRED_ANCHORS = [
    "discovery", "artifacts", "design", "build", "intake", "learn", "metrics",
    "review", "acceptance-test-plan",
]


def test_no_agent_ref_to_deleted_docs():
    """AC-4: no core/agents/* prompt keeps a reference to a to-be-deleted doc —
    incl. discovery.md's BARE `process-artifacts.md` ref."""
    for f in (REPO / "core" / "agents").rglob("*.md"):
        hits = _deleted_doc_hits(f.read_text("utf-8"))
        assert hits == [], f"{f.relative_to(REPO)} still references {hits}"


def test_kept_agent_files_not_flagged():
    """AC-10 (positive guard): the two-class matcher must NOT flag kept
    core/agents filenames or reviewer artifacts whose basenames collide with the
    phase-doc names — otherwise the safety net is un-green-able."""
    for benign in (
        "see core/agents/design.md and core/agents/discovery.md",
        "core/agents/review.md and core/agents/review-lite.md and intake.md",
        "records spec-review.md, drift-review.md, test-plan-review.md",
        "reads spec-review-findings.json / test-plan-review-findings.json",
        "the reviewer writes impl-plan-review.md and adds happy-path findings",
        "no happy-path-only plan; the manual.md checklist stays verbatim",
    ):
        assert _deleted_doc_hits(benign) == [], benign


def test_rewired_targets_resolve():
    """AC-4: every anchor the rewired links point at is a real heading in
    process.md."""
    slugs = _heading_slugs((DOCS / "process.md").read_text("utf-8"))
    for anchor in _REWIRED_ANCHORS:
        assert anchor in slugs, f"process.md has no #{anchor} heading"


# ---------------------------------------------------------------------------
# step-5 — delete the prose docs + kept guards + repo-wide dead-link net
# ---------------------------------------------------------------------------

# The ~19 pure-prose docs absorbed into the three docs, then deleted.
_DELETED_DOCS = [
    "process-artifacts.md", "process-metrics.md", "roles.md", "glossary.md",
    "planning-eval.md", "dual-remote-mr-pr-workflow.md", "callgraph-backends.md",
    "happy-path.md", "epics.md",
] + [f"phases/{p}.md" for p in _PHASE]

# The machine-coupled + operational docs that STAY (spec-review D-1, C-002).
_KEPT_DOCS = [
    "process.md", "architecture.md", "constitution.md", "coverage-taxonomy.md",
    "tracks.md",  # severity-rubric.md moved to config/ (KLC-172)
]

# Dirs the repo-wide dead-link net must return zero hits over (AC-10 scope).
_SCAN_SUFFIXES = {".md", ".py", ".yml", ".yaml", ".txt", ".json", ".j2", ".sh"}


def test_prose_docs_deleted():
    """AC-7: every absorbed prose doc (incl. all of docs/phases/) is gone."""
    for rel in _DELETED_DOCS:
        assert not (DOCS / rel).exists(), f"docs/{rel} must be deleted"
    assert not (DOCS / "phases").exists(), "docs/phases/ must be removed entirely"


def test_kept_docs_present():
    """AC-8: the machine-coupled + operational docs are KEPT."""
    for name in _KEPT_DOCS:
        assert (DOCS / name).exists(), f"docs/{name} must be kept"
    assert (DOCS / "adr").is_dir(), "docs/adr/ must be kept"
    # At least one dated epic plan stays (the one test_epics_doc links).
    assert (DOCS / "20260724_epic_feature_impl_plan.md").exists()


def _scan_files():
    yield REPO / "README.md"
    for root in ("core", "klc-plugin", "scripts", "config"):
        base = REPO / root
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if f.is_file() and f.suffix in _SCAN_SUFFIXES:
                yield f


def test_no_dead_doc_reference_repo_wide():
    """AC-10: no reference to a deleted doc survives anywhere an agent prompt, the
    plugin, the README, scripts, or config can still cite it — the two-class net."""
    offenders = {}
    for f in _scan_files():
        try:
            hits = _deleted_doc_hits(f.read_text("utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
        if hits:
            offenders[str(f.relative_to(REPO))] = hits
    assert offenders == {}, f"dead doc references remain: {offenders}"


def test_severity_rubric_linked_not_inlined():
    """impl-plan-review F-1: process.md LINKS severity-rubric.md but does NOT paste
    its body — the rubric stays the single source (AC-8)."""
    t = (DOCS / "process.md").read_text("utf-8")
    assert "severity-rubric.md" in t, "process.md must reference severity-rubric.md"
    body_marker = "This document defines the four severity levels used by all review agents."
    assert body_marker not in t, (
        "process.md must LINK severity-rubric.md, not inline its body"
    )
