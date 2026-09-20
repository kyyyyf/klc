"""KLC-124 step-6/step-7 — AC-8: on klc's own live repository, no `c`
language remains and `planning-retriever._candidate_languages` classifies
this repo's own two real `.h` files as `cpp`, not `c` — the exact live
scenario raw.md reports fixed.

Review round-2 (MEDIUM #1, `code-review-findings.json`) found the original
version of this test non-hermetic: it read `.klc/index/inventory.json`
directly off disk, and that path is gitignored, shared, mutable build
state — whichever branch/session last rebuilt it wins, independent of git
state, so the test went RED whenever another branch rebuilt the shared
index with a pre-fix `file_scanner.py`. `[!DECISION D-3]` (build-log.md):
the PRIMARY assertion now builds its own answer, in-process, by running the
real `file_scanner.scan()` production path directly against this
checkout's own working tree (read-only — `scan()` never writes) under
THIS checkout's own code, so it always reflects the code actually checked
out and never depends on whatever `.klc/index/*.json` happens to hold. A
single soft sanity check against the real on-disk `.klc/index/` artifacts
is kept, but it degrades to a `pytest.skip` (not a failure) when the live
index can be shown to simply predate this fix, rather than reporting a
false regression.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
IDX = Path(os.environ.get("PROJECT_ROOT", FW_ROOT)) / ".klc" / "index"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, FW_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fresh_repo_scan(root: Path = FW_ROOT) -> dict:
    """Build `structural.json`'s `languages` dict fresh, in-process, via the
    real `file_scanner.scan()` production path against `root` — read-only,
    no `.klc/index/` write, no ast-grep dependency (language classification
    is pure `EXT_LANG` extension lookup). This is the hermetic substrate
    for AC-8: it always reflects the CURRENT checkout's `EXT_LANG`, not
    whatever a shared, gitignored, mutable index file happens to hold."""
    fs = _load("fs_klc124_hermetic_dogfood", "core/skills/file_scanner.py")
    return fs.scan(root)


def test_repo_scan_reports_no_c_language():
    """AC-8(a), hermetic: a fresh `file_scanner.scan()` of this repository's
    own working tree, run in-process under the current checkout's code,
    reports no `c` language at all — this repo's real `.h` files (`tests/
    fixtures/rules/coverage/sample.h`, `tests/fixtures/rules/cpp/scope.h`,
    confirmed tracked via `git ls-files`) classify as `cpp`, never `c`.
    Deterministic across branches: this never reads `.klc/index/*.json`."""
    structural = _fresh_repo_scan()
    assert "c" not in structural["languages"], structural["languages"]
    assert "cpp" in structural["languages"], structural["languages"]


def test_candidate_languages_of_live_h_fixtures_is_cpp_not_c():
    """AC-8(b): `planning-retriever._candidate_languages` called directly
    with this repo's own two real `.h` files (verified live via
    `git ls-files`) returns {"cpp"}, never {"c"}. Already hermetic — pure
    string/extension logic, no file or index I/O."""
    pr = _load("pr_klc124_dogfood", "core/skills/planning-retriever.py")
    matched = {"tests/fixtures/rules/coverage/sample.h": 1.0,
               "tests/fixtures/rules/cpp/scope.h": 1.0}
    assert pr._candidate_languages(matched) == {"cpp"}


# --- soft sanity check against the real, on-disk .klc/index/ -- D-3 -------

def _predates_fix(live_languages: dict, fresh_languages: dict) -> bool:
    """Pure decision: does a live index snapshot's language set disagree
    with a fresh scan of the SAME repo under the CURRENT code only by
    carrying a stale `c` entry the current code no longer produces? If so
    the live index was simply built before this fix landed — not a genuine
    regression — and the soft sanity check below should skip, not fail."""
    return bool((live_languages or {}).get("c")) and "c" not in (fresh_languages or {})


def _check_live_index_or_skip(structural_path: Path, inventory_path: Path,
                               fresh_languages: dict) -> None:
    """The soft sanity check's body, factored out so it can be exercised
    directly with synthetic tmp paths (see the two unit tests below) as
    well as from the real pytest test against the real live index. Skips
    when the live index is shown to merely predate this fix (`_predates_fix`);
    otherwise asserts the live `inventory.json` carries no `inventory:c`
    verdict."""
    if not structural_path.exists() or not inventory_path.exists():
        pytest.skip("no built .klc/index/ on this checkout")
    live_structural = json.loads(structural_path.read_text(encoding="utf-8"))
    live_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    live_languages = live_structural.get("languages", {})
    if _predates_fix(live_languages, fresh_languages):
        pytest.skip(
            "live .klc/index/structural.json predates the KLC-124 fix "
            "(still classifies a file as 'c'); this checkout's own "
            "file_scanner.scan() already agrees with the hermetic test "
            "above (no 'c') — rebuild the live index to clear this soft "
            "skip, see review round-2 MEDIUM #1 / D-3")
    assert not any(e.get("builder") == "inventory:c"
                   for e in live_inventory.get("errors", [])), \
        "inventory.json still carries a 'c' language verdict — rebuild the index"


def test_predates_fix_detects_stale_c_language_but_not_other_disagreements():
    """Unit test for the pure staleness decision: stale (live still has
    'c', fresh doesn't) is detected; a live index that agrees with fresh
    (both clean, or both still carrying a genuine 'c') is not flagged as
    stale."""
    assert _predates_fix({"c": {"files": 2}}, {"cpp": {"files": 2}}) is True
    assert _predates_fix({"c": {"files": 2}}, {"c": {"files": 2}}) is False
    assert _predates_fix({"python": {"files": 1}}, {"python": {"files": 1}}) is False
    assert _predates_fix({}, {}) is False


def test_check_live_index_skips_when_live_index_is_stale(tmp_path):
    """Reproduces the exact review round-2 MEDIUM #1 scenario under a
    controlled, deterministic tmp index (not the shared live one): a
    stale `.klc/index/{structural,inventory}.json` still carrying a `c`
    verdict, on a checkout whose CURRENT `file_scanner.py` no longer
    produces one. Before D-3's fix, this doomed the test to flake on
    whichever real index a concurrent branch had rebuilt; the soft check
    correctly SKIPS this case instead of failing."""
    structural_p = tmp_path / "structural.json"
    inventory_p = tmp_path / "inventory.json"
    structural_p.write_text(json.dumps({"languages": {
        "c": {"files": 12, "lines": 140}, "python": {"files": 10, "lines": 100}}}),
        encoding="utf-8")
    inventory_p.write_text(json.dumps({"errors": [
        {"builder": "inventory:c", "artifact": "inventory.json",
         "observed": 0, "universe": 2, "ratio": 0.0, "degraded": True}]}),
        encoding="utf-8")
    fresh_languages = {"cpp": {"files": 12, "lines": 140},
                        "python": {"files": 10, "lines": 100}}
    with pytest.raises(pytest.skip.Exception):
        _check_live_index_or_skip(structural_p, inventory_p, fresh_languages)


def test_check_live_index_fails_when_c_persists_and_is_not_stale(tmp_path):
    """A live index that still carries an `inventory:c` verdict AND agrees
    with a fresh scan under the current code (i.e. `c` genuinely still
    exists as a language on this repo) is a real regression, not staleness
    — the soft check must still fail, not silently skip."""
    structural_p = tmp_path / "structural.json"
    inventory_p = tmp_path / "inventory.json"
    structural_p.write_text(json.dumps({"languages": {
        "c": {"files": 3, "lines": 30}}}), encoding="utf-8")
    inventory_p.write_text(json.dumps({"errors": [
        {"builder": "inventory:c", "artifact": "inventory.json",
         "observed": 0, "universe": 3, "ratio": 0.0, "degraded": True}]}),
        encoding="utf-8")
    fresh_languages = {"c": {"files": 3, "lines": 30}}  # current code STILL says c
    with pytest.raises(AssertionError):
        _check_live_index_or_skip(structural_p, inventory_p, fresh_languages)


def test_live_index_sanity_no_stale_c_verdict_or_skip():
    """AC-8(a) soft sanity check against the real, on-disk `.klc/index/`
    artifacts of THIS checkout. Not the source of truth for this AC (see
    `test_repo_scan_reports_no_c_language` above, which is hermetic and
    always runs) — this only adds a read-only canary against the real
    live index, degrading to skip rather than false-failing when that
    shared, mutable file simply predates this fix."""
    fresh_languages = _fresh_repo_scan()["languages"]
    _check_live_index_or_skip(IDX / "structural.json", IDX / "inventory.json",
                               fresh_languages)
