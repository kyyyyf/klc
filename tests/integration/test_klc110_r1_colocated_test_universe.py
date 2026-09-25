"""tests/integration/test_klc110_r1_colocated_test_universe.py — KLC-110
review round 1, step-10 (MEDIUM, AC-4): a colocated name-signal test file
changed ALONE (its production sibling untouched, no dedicated `tests/`
directory) must still be confirmed as a test. The pre-fix `exists=`
predicate confirmed a sibling only via membership in the SAME committed
diff, so a lone `foo_test.py` commit — the ordinary shape of a colocated
Go/Python test change that doesn't also touch its untouched sibling — was
silently dropped from the tests-recall arrow's ground truth."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402

# KLC-110 review round 2, step-12 (D-110-14, supersedes D-110-11): the
# module entry now carries a REAL `files` listing including the derived
# sibling `core/skills/widget.py` — step-10's original fixture used an empty
# `"files": {}` at the top level and relied on DIRECTORY-PREFIX residency
# (any path under `core/skills/` resolving non-orphan), which step-12
# replaces with LITERAL per-file membership. Without a real listing here,
# this fixture's own sibling would no longer confirm under the new rule —
# see `test_klc110_r1_module_map_literal_files.py` for the round-2 repro
# this fixture change is a direct consequence of.
_MODULES_DATA = {"modules": [{"name": "core-skills", "path": "core/skills/",
                             "files": ["core/skills/widget_test.py",
                                       "core/skills/widget.py"]}],
                 "files": {}}


def test_ac4_colocated_name_signal_test_confirmed_via_module_map_when_sibling_untouched():
    """A `*_test.py` file changed alone (its `.py` sibling untouched, no
    `tests/` directory ancestor) still counts as ground truth for the
    tests-recall arrow when the sibling resolves to a real, non-orphan
    module in the module map already loaded this ack."""
    changed_test = "core/skills/widget_test.py"
    trace = {"status": "ok", "confidence": "medium",
             "tests_to_read_or_run": [changed_test]}
    rec = _reval.evaluate(trace, set(), {changed_test}, modules_data=_MODULES_DATA)
    arrow = rec["tests_to_read_or_run"]
    assert arrow.get("status") != "unavailable", (
        f"colocated test file was dropped from ground truth: {arrow}")
    assert arrow["recall"] == 1.0
    assert arrow["precision"] == 1.0


def test_ac4_no_modules_data_falls_back_to_diff_only_membership():
    """Without `modules_data` (the pre-fix call shape, still supported), the
    sibling-confirmation predicate falls back to diff-only membership —
    unchanged behaviour for every existing caller that doesn't pass it."""
    changed_test = "core/skills/widget_test.py"
    trace = {"status": "ok", "confidence": "medium",
             "tests_to_read_or_run": [changed_test]}
    rec = _reval.evaluate(trace, set(), {changed_test})
    arrow = rec["tests_to_read_or_run"]
    assert arrow.get("status") == "unavailable"


def test_ac4_orphan_sibling_not_in_any_module_stays_unconfirmed():
    """A same-directory sibling that resolves to NO module (orphan) is
    correctly NOT confirmed — the widened predicate is additive, not a
    blanket trust of any basename match."""
    changed_test = "nowhere/mystery_test.py"
    trace = {"status": "ok", "confidence": "medium",
             "tests_to_read_or_run": [changed_test]}
    rec = _reval.evaluate(trace, set(), {changed_test}, modules_data=_MODULES_DATA)
    arrow = rec["tests_to_read_or_run"]
    assert arrow.get("status") == "unavailable"
