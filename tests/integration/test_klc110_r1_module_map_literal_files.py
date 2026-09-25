"""tests/integration/test_klc110_r1_module_map_literal_files.py — KLC-110
review round 2, step-12 (MEDIUM, AC-4): step-10's directory-PREFIX residency
check reintroduced the exact name-signal false positive
`test_conventions.py`'s own docstring built `exists=` to prevent.

Reproduced against the LIVE `modules.json` shape: a directory-boundary
module (`path` ending in `/`, e.g. `core/skills/`) resolves ANY same-
directory path non-orphan via `module_membership.file_to_module`, whether or
not that file is literally listed. `evaluate({'status':'ok',
'tests_to_read_or_run':[]}, set(), {'core/skills/test_conventions.py'},
modules_data=<live>)` therefore put the PRODUCTION file
`core/skills/test_conventions.py` into the test ground truth — its derived
"sibling" `core/skills/conventions.py` does not exist and is not listed.

Fix: confirm a sibling only by LITERAL membership in the module map's
per-file listings (the union of every module's own `files` array), unioned
with the diff — never by directory-prefix residency (D-110-14, supersedes
D-110-11)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402

# The LIVE-shaped repro: a `core/skills/` directory module whose `files`
# LISTS `core/skills/test_conventions.py` but NOT `core/skills/conventions.py`
# — exactly today's real `.klc/index/modules.json` shape (verified by
# reading it directly: `core/skills/test_conventions.py` is listed,
# `core/skills/conventions.py` is not).
_LIVE_SHAPED_MODULES_DATA = {
    "modules": [{"name": "core/skills", "path": "core/skills/",
                "files": ["core/skills/test_conventions.py"]}],
    "files": {},
}

_MODULES_DATA_WITH_LISTED_SIBLING = {
    "modules": [{"name": "core/skills", "path": "core/skills/",
                "files": ["core/skills/widget_test.py", "core/skills/widget.py"]}],
    "files": {},
}


def test_ac4_directory_residency_no_longer_false_positives_the_self_collision():
    """The live-shaped repro: `core/skills/test_conventions.py`, changed
    alone with no test candidates in its own trace, must NOT be pulled into
    the test-recall ground truth just because it sits under a
    directory-boundary module — its fictional derived sibling
    `core/skills/conventions.py` is not literally listed anywhere."""
    changed = "core/skills/test_conventions.py"
    trace = {"status": "ok", "confidence": "medium", "tests_to_read_or_run": []}
    rec = _reval.evaluate(trace, set(), {changed}, modules_data=_LIVE_SHAPED_MODULES_DATA)
    arrow = rec["tests_to_read_or_run"]
    assert arrow.get("status") == "unavailable", (
        f"a production file was misclassified as a test via directory residency: {arrow}")


def test_ac4_colocated_sibling_literally_listed_still_confirms_as_test():
    """The positive case is unaffected: a colocated `foo_test.py` whose
    `.py` sibling IS literally listed in the module's own `files` array
    still confirms as ground truth for the tests-recall arrow."""
    changed = "core/skills/widget_test.py"
    trace = {"status": "ok", "confidence": "medium",
             "tests_to_read_or_run": [changed]}
    rec = _reval.evaluate(trace, set(), {changed},
                          modules_data=_MODULES_DATA_WITH_LISTED_SIBLING)
    arrow = rec["tests_to_read_or_run"]
    assert arrow.get("status") != "unavailable"
    assert arrow["recall"] == 1.0
    assert arrow["precision"] == 1.0


def test_ac4_files_override_map_entries_also_count_as_literally_listed():
    """The top-level `files` override dict (per-file exceptions, distinct
    from a module's own `files` array) also counts as literal membership —
    it is still a real per-file listing in the module map, just keyed at
    the top level instead of nested under a module."""
    changed = "pkg/widget_test.py"
    modules_data = {"modules": [], "files": {"pkg/widget.py": {"primary_module": "pkg"}}}
    trace = {"status": "ok", "confidence": "medium",
             "tests_to_read_or_run": [changed]}
    rec = _reval.evaluate(trace, set(), {changed}, modules_data=modules_data)
    arrow = rec["tests_to_read_or_run"]
    assert arrow.get("status") != "unavailable"
