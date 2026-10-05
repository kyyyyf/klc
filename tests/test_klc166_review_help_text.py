"""KLC-166 step-4 — AC-10: `scripts/review.py --help`'s `--diff` text stops
advertising a range example (`main...feat`/`main...HEAD`) and instead says
it takes a unified-diff file or one git ref diffed against the working
tree. `_resolve_diff`'s own behaviour (AC-11) is unchanged — proved by the
unmodified KLC-120 suites run alongside this one in the step's VERIFY, not
by this test."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent


def test_diff_help_text_no_longer_advertises_a_range_example():
    """AC-10: run `review.py --help` as a subprocess, normalise whitespace
    (argparse wraps lines), and assert the range examples are gone while the
    file-or-single-ref wording is present."""
    result = subprocess.run(
        [sys.executable, str(FW_ROOT / "scripts" / "review.py"), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    text = re.sub(r"\s+", " ", result.stdout)
    assert "main...feat" not in text
    assert "main...HEAD" not in text
    assert "unified-diff file" in text.lower()
    # KLC-175 AC-1 superseded the "working tree" wording: ranges and `recorded` are accepted.
    assert "recorded" in text.lower()
