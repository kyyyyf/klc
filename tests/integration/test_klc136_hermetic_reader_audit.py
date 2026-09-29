"""KLC-136 step-6 — AC-3: a read-audit re-run of the F-009 probe against a
repository copy, scoped to the 11 group (b) implicit readers plus the 6
group (a) files other than `tests/test_callgraph_cpp_lsp.py` (too slow for
this audit's own timeout — the build log carries its own read-audited full
run instead, step-5), plus a canary. Zero index reads from the in-scope
readers; the canary's own read IS in the log (fail-closed: the probe
mechanism itself is proven to work, not merely silent).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GUARD_DIR = REPO_ROOT / "tests" / "shared" / "live_guard"
TESTS_SHARED = REPO_ROOT / "tests" / "shared"
for _p in (str(GUARD_DIR), str(TESTS_SHARED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc_live_guard  # noqa: E402
import fresh_index as fresh_index_mod  # noqa: E402

_GROUP_B_FILES = [
    "tests/integration/test_deterministic_inventory.py",
    "tests/integration/test_klc103_schema_canonical.py",
    "tests/integration/test_klc103_shared_accessor.py",
    "tests/integration/test_klc105_builder_universe.py",
    "tests/integration/test_klc105_non_python_backends.py",
    "tests/integration/test_klc105_walk_fallback.py",
    "tests/integration/test_planning_validation.py",
    "tests/integration/test_planning_validation_crossartifact.py",
    "tests/test_intake_routing.py",
    "tests/test_drift_review.py",
    "tests/test_phase_completion_drift.py",
]

_GROUP_A_FILES_EXCEPT_CALLGRAPH = [
    "tests/integration/test_klc108_inventory_scope_assertion.py",
    "tests/integration/test_klc108_keywords_salience.py",
    "tests/integration/test_klc108_probe_traces.py",
    "tests/integration/test_klc123_live_repo_dogfood.py",
    "tests/integration/test_klc124_dogfood_no_c_language.py",
    "tests/integration/test_klc110_r1_backfill_requires_out_md.py",
]

_IN_SCOPE_FILES = _GROUP_B_FILES + _GROUP_A_FILES_EXCEPT_CALLGRAPH

_KEPT_LIVE_CHECK_DESELECT = (
    "tests/integration/test_klc124_dogfood_no_c_language.py"
    "::test_live_index_sanity_no_stale_c_verdict_or_skip"
)

_CANARY_SRC = '''
import json
import os
from pathlib import Path

def test_canary_reads_live_index():
    idx = Path(os.environ["PROJECT_ROOT"]) / ".klc" / "index" / "modules.json"
    data = json.loads(idx.read_text(encoding="utf-8"))
    assert "modules" in data
'''


def _stand_in_with(fresh_index_dir: Path, tmp_path: Path) -> Path:
    stand_in = tmp_path / "audit-stand-in"
    fresh_index_mod.make_live_index_state(stand_in, "current", fresh_index_dir)
    return stand_in


def _write_canary(tmp_path: Path) -> Path:
    canary_dir = tmp_path / "canary"
    canary_dir.mkdir()
    canary = canary_dir / "test_canary.py"
    canary.write_text(_CANARY_SRC, encoding="utf-8")
    return canary


def test_group_b_files_record_zero_index_reads_under_probe(tmp_path, fresh_index):
    """AC-3: the F-009 probe, re-run in an inner pytest session, records
    zero index reads from the in-scope readers, and DOES record the
    canary's read (fail-closed: proves the probe itself works)."""
    stand_in = _stand_in_with(fresh_index, tmp_path)
    canary = _write_canary(tmp_path)
    log = tmp_path / "reads.jsonl"

    env = {
        **os.environ,
        "PROJECT_ROOT": str(stand_in),
        "KLC_LIVE_GUARD_READ_ROOTS": os.pathsep.join([
            str(stand_in / ".klc" / "index"),
            str(REPO_ROOT / ".klc" / "index"),
        ]),
        "KLC_LIVE_GUARD_READ_LOG": str(log),
    }
    existing_pp = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join([str(GUARD_DIR)] + existing_pp)

    # --rootdir pinned to the repo (impl-plan-review F-6): without it, the
    # canary living under tmp_path drags pytest's computed rootdir up to
    # the common ancestor of the repo and /tmp (i.e. "/"), which makes
    # every in-repo nodeid path-shaped in a way that a naive basename
    # compare gets wrong. Pinned, the canary's own nodeid becomes the
    # degenerate case instead (no repo-relative path segment at all) — so
    # the assertion below matches on the CANARY'S OWN TEST NAME appearing
    # in the recorded test id, which is robust to either shape.
    cmd = [sys.executable, "-m", "pytest", f"--rootdir={REPO_ROOT}",
           *_IN_SCOPE_FILES, str(canary),
           "-q", "-p", "no:cacheprovider",
           "--deselect", _KEPT_LIVE_CHECK_DESELECT]
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                       capture_output=True, text=True, timeout=100)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]

    # A record from any phase (setup, call, teardown) counts as a read by
    # that file. The probe must have recorded AT LEAST the canary's own
    # read (fail-closed: proves the mechanism works, not merely silent),
    # and every recorded read must be attributable to the canary — none to
    # any of the 17 in-scope files.
    records = klc_live_guard.read_records(log)
    assert records, "the canary's own read was not recorded — the probe is not working"
    non_canary = [rec for rec in records if "test_canary_reads_live_index" not in rec["test"]]
    assert non_canary == [], non_canary
