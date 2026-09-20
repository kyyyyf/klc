"""KLC-122 — remove the Unreal Engine profile.

Grep-guard tests proving the deletion actually happened (and that the guards
themselves bite on a reintroduced token, not just vacuously pass on an
already-clean tree).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CPP_UNREAL_RE = re.compile(r"cpp-unreal")


def test_no_profiles_ue_path_reference_outside_historical_docs():
    # Exclude this guard file itself: its own source text necessarily
    # contains the literal string "profiles/ue" (the pattern it greps for),
    # which is not a leftover reference to the deleted profile.
    self_path = str(Path(__file__).resolve().relative_to(REPO_ROOT))
    out = subprocess.run(
        ["git", "grep", "-l", "profiles/ue", "--", ".", f":!{self_path}"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    hits = [h for h in out.stdout.splitlines() if h]
    allowed = {
        "docs/20260804_framework-hygiene-epic-plan.md",
        # KLC-109 D-OP-1: the UE profile was deleted by THIS ticket (KLC-122,
        # integrated 2026-09-19) after KLC-109's design already picked
        # profiles/ue/manifest.yml as its AC-5 end-to-end proof. D-OP-1
        # documents the substitution — a SYNTHETIC engine-style fixture
        # (tests/fixtures/klc109-engine-profile/manifest.yml) stands in for
        # the now-nonexistent path — and these four files explain that
        # substitution in prose; none of them reads from profiles/ue/ at
        # runtime (verified: only the synthetic fixture's own manifest.yml is
        # ever parsed).
        "tests/fixtures/klc109-engine-profile/manifest.yml",
        "tests/integration/test_klc109_tdd_order.py",
        "tests/integration/test_klc109_test_map.py",
        "tests/test_test_conventions.py",
    }
    assert set(hits) <= allowed, f"unexpected profiles/ue reference(s): {hits}"


def _grep_cpp_unreal(dirs, root=REPO_ROOT):
    hits = []
    for d in dirs:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            # Only source/config text under version control matters here —
            # compiled bytecode caches (__pycache__/*.pyc) are build-local
            # artifacts, not source, and can lag a source edit until the
            # next import recompiles them.
            if "__pycache__" in p.parts:
                continue
            if p.is_file() and p.suffix != ".pyc":
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if CPP_UNREAL_RE.search(text):
                    hits.append(str(p.relative_to(root)))
    return hits


def test_no_cpp_unreal_token_in_core_config_or_plugin():
    assert _grep_cpp_unreal(["core", "config", "klc-plugin"]) == []


def test_no_cpp_unreal_token_survives_fail_closed_on_stray_hit(tmp_path):
    """Review round-1 MEDIUM #2 (drift F-2/DC-2): call the REAL guard
    function against a stray reintroduced token, so this negative twin
    actually proves `_grep_cpp_unreal` itself bites — not an independent
    inline copy of its search logic that could hide a real bug in the
    deployed guard."""
    stray = tmp_path / "core"
    stray.mkdir()
    (stray / "leftover.py").write_text('LANG = "cpp-unreal"\n', encoding="utf-8")
    hits = _grep_cpp_unreal(["core"], root=tmp_path)
    assert hits, "guard must actually bite on a reintroduced token"


def test_reviewers_yml_per_language_key_stays_but_is_empty():
    """AC-4: config/reviewers.yml's per_language.cpp-unreal sub-block is gone,
    but the per_language: key itself stays (empty) so a future profile can
    still add an override there."""
    import yaml

    data = yaml.safe_load(
        (REPO_ROOT / "config" / "reviewers.yml").read_text(encoding="utf-8")
    )
    per_language = data["test"]["per_language"]
    assert per_language == {}, f"expected empty per_language, got {per_language!r}"


def test_dep_graph_build_has_no_dead_discovery_mode_resolution():
    """Review round-1 MEDIUM #3: dep_graph.build() resolved `module_discovery`
    and computed `discovery_mode` for the sole purpose of feeding the deleted
    `_ue_import_graph`/`build-cs` call site (step-2). Nothing reads it any
    more -- this is dead code AC-4's "remove every cpp-unreal special case
    from core" intent should have caught.

    Review round-2 MEDIUM: the identical defect class recurred one line
    above the fix for the case above -- `profile_excl`/`excl` (fed by
    `_combined_excl`/`BASELINE_EXCL`) was `_ue_import_graph`'s OTHER
    argument, orphaned by the very same step-2 deletion, but under
    different names this test's original single-token assertion did not
    catch. Both siblings are asserted here so the guard covers the whole
    dead-code class, not one token."""
    text = (REPO_ROOT / "core" / "skills" / "dep_graph.py").read_text(
        encoding="utf-8")
    assert "discovery_mode" not in text, (
        "dead discovery_mode resolution still present in dep_graph.py")
    assert "profile_excl" not in text, (
        "dead profile_excl resolution still present in dep_graph.py")
    assert "_combined_excl" not in text, (
        "dead _combined_excl helper/call still present in dep_graph.py")


def test_review_prompts_no_longer_defer_to_ue_profile():
    """Review round-1 MEDIUM #4: architecture/performance/security review
    prompts are actively wired into every review run via
    profiles/generic/manifest.yml's reviewers.always -- the sole shipped
    profile after this ticket -- but each still routed engine-specific
    concerns to "the UE profile," which no longer exists on disk."""
    review_dir = REPO_ROOT / "core" / "agents" / "review"
    for name in ("architecture.md", "performance.md", "security.md"):
        text = (review_dir / name).read_text(encoding="utf-8")
        assert "UE profile" not in text, (
            f"{name} still routes UE-specific concerns to 'the UE profile'"
        )


def test_config_readme_profile_row_names_generic_default():
    """LOW (drift F-4): config/README.md's profile.yml row still said
    '(default: ue)' after AC-1 flipped the real default to generic."""
    text = (REPO_ROOT / "config" / "README.md").read_text(encoding="utf-8")
    assert "(default: ue)" not in text


def test_deterministic_inventory_docstring_drops_stale_ue_claim():
    """Drift F-4: _run_astgrep's docstring claimed the profile's
    languageGlobs exist 'so UE .h files scan as cpp' -- per F-3/step-7, no
    shipped profile is UE-specific any more; the mapping is generic's own
    (profiles/generic/sgconfig.yml)."""
    text = (REPO_ROOT / "core" / "skills" / "deterministic_inventory.py").read_text(
        encoding="utf-8")
    assert "UE ``.h`` files scan as cpp" not in text


def test_klc106_fixtures_e2e_no_longer_claims_own_profile_is_ue():
    """Drift F-4: this module's docstring and a helper comment asserted, as
    present-tense fact, that 'this repo's OWN active profile is ue' -- false
    after AC-1 (config/profile.yml -> generic)."""
    text = (REPO_ROOT / "tests" / "integration" / "test_klc106_fixtures_e2e.py").read_text(
        encoding="utf-8")
    assert "own active profile is" not in text


def test_klc106_dep_graph_degrade_docstring_drops_ue_build_cs_walk():
    """Drift F-4 (INFO, folded into this bookkeeping step): the module
    docstring still listed 'the UE *.Build.cs walk' as a not-applicable-metric
    producer example; that producer (_ue_import_graph) was deleted in
    step-2."""
    text = (REPO_ROOT / "tests" / "integration" / "test_klc106_dep_graph_degrade.py").read_text(
        encoding="utf-8")
    assert "UE *.Build.cs walk" not in text


def test_readme_profiles_section_names_only_generic():
    """AC-8: README's ## Profiles example and layout diagram name only the
    shipped `generic` profile; `ue` is gone from both, though a second
    profile stays possible by contract (proven by manifest.yml + the
    profile-resolve machinery staying generic, not by this string check)."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "profile: ue" not in text, (
        "README's profile example still names the deleted ue profile"
    )
    assert "profiles/generic/ ue/" not in text, (
        "README's layout diagram still lists ue as a shipped profile"
    )
