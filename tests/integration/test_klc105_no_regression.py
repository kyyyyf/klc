"""KLC-105 step-6 — the existing deterministic-index test suite passes unchanged
(AC-12).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
_baseline_file = _repo_root / "tests" / "fixtures" / "klc105_baseline_test_ids.txt"

# Q-101: the sentinel guards against this test recursively re-launching itself
# inside the child `pytest tests/` run it spawns.
_SENTINEL = "KLC105_INNER_SUITE"


def test_full_suite_passes_unchanged():
    """AC-12: the full tests/ + tests/integration/ suite passes after the change,
    with no test deleted or weakened to accommodate the new universe.

    Gated behind KLC_RUN_NESTED_FULL_SUITE=1 (skipped otherwise): this test spawns
    the ENTIRE tests/ suite as a child process, roughly doubling the runtime of any
    default `pytest tests/` invocation that collects it. Run it explicitly (e.g. as
    a separate CI step) with KLC_RUN_NESTED_FULL_SUITE=1 set."""
    if not os.environ.get("KLC_RUN_NESTED_FULL_SUITE") == "1":
        pytest.skip(
            "set KLC_RUN_NESTED_FULL_SUITE=1 to run the nested full-suite check "
            "(it spawns the whole tests/ suite as a child process and roughly "
            "doubles default runtime)")
    if os.environ.get(_SENTINEL):
        pytest.skip("inner suite run — the outer process already owns this assertion")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--ignore=tests/fixtures", "-q"],
        cwd=str(_repo_root),
        env={**os.environ, "PROJECT_ROOT": str(_repo_root), _SENTINEL: "1"},
        capture_output=True, text=True, timeout=1800,
    )
    assert r.returncode == 0, (
        f"full suite failed (rc={r.returncode}):\n"
        f"{r.stdout[-4000:]}\n{r.stderr[-2000:]}")


def test_no_existing_test_deleted_or_weakened():
    """AC-12 mechanical proxy: pytest --collect-only -q test-id set computed now
    must be a SUPERSET of the pre-change baseline captured at step-1 (Q-102) — no
    collected test id from before disappears after."""
    if os.environ.get(_SENTINEL):
        pytest.skip("inner suite run — the outer process already owns this assertion")
    assert _baseline_file.exists(), (
        f"baseline file missing: {_baseline_file} (should have been captured at "
        f"step-1)")
    baseline_ids = {
        ln.strip() for ln in _baseline_file.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--ignore=tests/fixtures",
         "--collect-only", "-q"],
        cwd=str(_repo_root),
        env={**os.environ, "PROJECT_ROOT": str(_repo_root), _SENTINEL: "1"},
        capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, f"collect-only failed:\n{r.stdout}\n{r.stderr}"
    current_ids = {ln for ln in r.stdout.splitlines() if "::" in ln}

    missing = baseline_ids - current_ids
    assert missing == set(), (
        f"{len(missing)} pre-change test id(s) disappeared: {sorted(missing)[:10]}")
