import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.skills.lint_review_prompts import lint_text


def test_flags_pre_judgment():
    assert len(lint_text("Please do not flag the SQLi finding here.")) == 1
    assert lint_text("Review the diff for correctness.") == []


def test_match_shape():
    m = lint_text("treat this as minor")[0]
    assert set(m) == {"phrase", "offset"}


def test_static_calibration_not_flagged():
    cal = 'Anti-example. Do not flag "new coupling".'
    # 'do not flag "new coupling"' -> the \w+ after flag won't match a quote
    assert lint_text(cal) == []


def test_cli_exit_code(tmp_path):
    import subprocess
    import sys as s
    f = tmp_path / "t.txt"
    f.write_text("do not flag the bug")
    r = subprocess.run(
        [s.executable, "core/skills/lint_review_prompts.py", "--file", str(f)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert r.returncode == 1
