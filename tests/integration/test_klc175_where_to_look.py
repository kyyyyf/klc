"""KLC-175 step-5 (AC-8, AC-9, AC-10): the review report carries a deterministic
`## Where to look` (critical / important / optional), the PR summary comment
copies it, and the report records the cost figures (`n/a` when not measured).

`review_map.build` is pure: a diff text, a ticket dir, the reviewers.yml block
and classify_tier's path -> tier map in; three lists of `{file, reason}` out.
Git history comes from a real temp repo, never a mock."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import models as models_mod  # noqa: E402
import publish_github as pg  # noqa: E402
import review as rv  # noqa: E402
import review_map  # noqa: E402
from test_klc120_review_plan import _seed_project, _stub_claude_on_path, _write_diff  # noqa: E402


def _file_diff(path: str, added: list[str]) -> str:
    body = "".join(f"+{ln}\n" for ln in added)
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(added)} @@\n{body}")


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _repo_with_history(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for i in range(3):                          # src/hot.py: 3 commits
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "hot.py").write_text(f"x = {i}\n", encoding="utf-8")
        _git(repo, "add", "src/hot.py")
        _git(repo, "commit", "-q", "-m", f"c{i}")
    (repo / "src" / "cold.py").write_text("y = 1\n", encoding="utf-8")
    _git(repo, "add", "src/cold.py")
    _git(repo, "commit", "-q", "-m", "cold")   # 1 commit: below the minimum
    return repo


IMPL_PLAN = """\
## step-1 — risky
**Addresses:** AC-1
**Affected files:** `src/risky.py`

## step-2 — decided in plan
> [!DECISION D-002] owner=ek
> keep it flat
**Affected files:** `src/stepdec.py`
"""


def _ticket(tmp_path: Path, *, risk_tags: bool = True) -> Path:
    t = tmp_path / "KLC-990"
    (t / "review").mkdir(parents=True)
    tags = "[user-facing]" if risk_tags else "[]"
    (t / "spec.md").write_text(
        f"---\nticket: KLC-990\nrisk_tags: {tags}\n---\n\n## Goals\ng\n\n"
        "> [!DECISION D-001] owner=ek refs=src/decided.py\n> choice made\n",
        encoding="utf-8")
    (t / "impl-plan.md").write_text(IMPL_PLAN, encoding="utf-8")
    return t


ASSESSMENTS = [
    {"file": "src/med.py", "line": 7, "severity": "MEDIUM", "disposition": "wont-fix"},
    {"file": "src/low.py", "line": 2, "severity": "LOW", "disposition": "wont-fix"},
]


FILES = {
    "src/auth/login.py": ["a = 1"],
    "db/migrations/0002_add.sql": ["ALTER TABLE t ADD c int;"],
    "src/decided.py": ["z = 1"],
    "src/api.py": ["x = 1", "def public_fn():", "    pass"],
    "src/risky.py": ["r = 1"],
    "src/hot.py": ["h = 1"],
    "src/cold.py": ["c = 1"],
    "core/agents/foo.md": ["prompt"],
    "src/stepdec.py": ["s = 1"],
    "src/med.py": ["m = 1"],
    "src/low.py": ["l = 1"],
    "klc-plugin/agents/foo.md": ["gen"],
    "tests/golden/out.golden": ["g"],
    ".klc/tickets/KLC-990/note.md": ["n"],
    "src/plain.py": ["p = 1"],
    "docs/notes.md": ["def not_api():"],     # prose that looks like code is not public API
}


def _by_file(tier: list[dict]) -> dict[str, str]:
    return {e["file"].split(":")[0]: e["reason"] for e in tier}


def test_tiers_on_fixture_diff(tmp_path):
    repo = _repo_with_history(tmp_path)
    ticket = _ticket(tmp_path)
    diff = "".join(_file_diff(p, a) for p, a in FILES.items())
    cfg = {"where_to_look": {"hotspot_min_commits": 2}, "repo_root": str(repo)}
    tiers = review_map.build(diff, ticket, cfg, {"src/auth/login.py": "critical"},
                             assessments=ASSESSMENTS)

    assert set(tiers) == {"critical", "important", "optional"}
    crit, imp, opt = (_by_file(tiers[k]) for k in ("critical", "important", "optional"))
    assert crit["src/auth/login.py"] == "tier"
    assert crit["db/migrations/0002_add.sql"] == "migration"
    assert crit["src/decided.py"] == "decision"
    assert crit["src/api.py"] == "public-api"
    assert crit["src/risky.py"] == "risk-tag"
    assert imp["src/hot.py"] == "hotspot"
    assert imp["core/agents/foo.md"] == "agent-prompt"
    assert imp["src/stepdec.py"] == "plan-decision"
    assert imp["src/med.py"] == "wont-fix"
    assert opt["klc-plugin/agents/foo.md"] == "generated"
    assert opt["tests/golden/out.golden"] == "generated"
    assert opt[".klc/tickets/KLC-990/note.md"] == "service"
    listed = set(crit) | set(imp) | set(opt)
    assert "src/cold.py" not in listed            # 1 commit < hotspot_min_commits
    assert "src/low.py" not in listed             # LOW won't-fix is not listed
    assert "src/plain.py" not in listed
    assert "docs/notes.md" not in listed
    assert len(listed) == len(tiers["critical"]) + len(tiers["important"]) + len(tiers["optional"])
    # file:line when known: the added public def is line 2, the assessment says 7
    assert {e["file"] for e in tiers["critical"]} >= {"src/api.py:2"}
    assert {e["file"] for e in tiers["important"]} >= {"src/med.py:7"}
    text = review_map.render(tiers)
    assert text.index("### Critical") < text.index("### Important") < text.index("### Optional")
    assert "`src/auth/login.py` — tier" in text


def test_no_risk_tags_means_no_risk_tag_entries(tmp_path):
    ticket = _ticket(tmp_path, risk_tags=False)
    tiers = review_map.build(_file_diff("src/risky.py", ["r = 1"]), ticket,
                             {"repo_root": str(tmp_path)}, {})
    assert "src/risky.py" not in _by_file(tiers["critical"])


def test_missing_inputs_degrade_to_empty_tiers(tmp_path):
    cfg = {"repo_root": str(tmp_path / "no-such-dir")}     # no git history either
    tiers = review_map.build(_file_diff("src/plain.py", ["p = 1"]),
                             tmp_path / "missing-ticket", cfg, {})
    assert tiers == {"critical": [], "important": [], "optional": []}
    assert review_map.build("", tmp_path / "x", {}, {}) == tiers
    assert review_map.build(_file_diff("a.py", ["x"]), tmp_path / "x", None, None) == tiers
    text = review_map.render(tiers)
    assert text.startswith("## Where to look") and "_None._" in text


REPORT = """\
# Code Review Report

## Summary
| Reviewer | Issues |
|---|---|
| code-review | 1 |

## Where to look
### Critical
- `src/auth/login.py` — tier
### Important
- `src/hot.py` — hotspot
### Optional
_None._

## Blocking Issues (must fix before merge)
none

## Verdict: APPROVED
"""


def test_publish_summary_carries_where_to_look():
    out = pg.extract_summary(REPORT, verdict="APPROVED")
    assert "## Where to look" in out
    assert out.index("### Critical") < out.index("### Important") < out.index("### Optional")
    assert "`src/auth/login.py` — tier" in out and "| code-review | 1 |" in out
    assert "Blocking Issues" not in out and "Verdict" not in out
    plain = pg.extract_summary(REPORT.replace("## Where to look", "## Elsewhere"),
                               verdict="APPROVED")
    assert "Where to look" not in plain


def test_report_records_cost_figures(tmp_path, monkeypatch):
    project_root, spec = _seed_project(tmp_path, track="L")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    runner = tmp_path / "fake_runner.py"
    runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[2]).write_text('## PASS\\nno findings\\n\\nTOTAL=0 BLOCKING=0\\n',"
        " encoding='utf-8')\n", encoding="utf-8")
    monkeypatch.setenv("REVIEW_RUNNER", str(runner))
    diff = _write_diff(tmp_path, "d.patch", _file_diff("db/migrations/0001.sql", ["select 1;"]))
    assert rv.main(["--diff", str(diff), "--spec", str(spec), "--no-external"]) == 0

    report = next((project_root / ".klc" / "reports").glob("review-*.md"))
    text = report.read_text(encoding="utf-8")
    plan = json.loads(next((project_root / ".klc/tickets/KLC-990/review")
                           .glob("review-plan-r*.json")).read_text(encoding="utf-8"))
    assert re.search(r"^planned_passes: \d+$", text, re.M)
    assert re.search(r"^executed_passes: \d+$", text, re.M)
    assert "review_duplicate_rate: n/a" in text            # no pool, not measured
    in_client = re.search(r"^inlined_bytes_in_client: (\d+)$", text, re.M)
    headless = re.search(r"^inlined_bytes_headless: (\d+)$", text, re.M)
    assert in_client and headless
    assert int(in_client.group(1)) == plan["inlined_bytes_in_client"]
    assert int(headless.group(1)) == plan["inlined_bytes_headless"]
    assert int(headless.group(1)) > int(in_client.group(1))   # context repeats per card
    assert "## Where to look" in text and "### Critical" in text
    assert "`db/migrations/0001.sql` — migration" in text


def test_unmeasured_figures_render_na(tmp_path):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(FW_ROOT / "core" / "templates")),
                      keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True)
    out = env.get_template("review-report.md.j2").render(
        timestamp="t", spec_path="s", reviewers=[], external=None, adrs=[],
        tier_classification=None, sentinel_matches=None, blocking_issues="",
        non_blocking_issues="", out_of_scope_issues="", verdict="APPROVED")
    for line in ("planned_passes: n/a", "executed_passes: n/a",
                 "review_duplicate_rate: n/a", "inlined_bytes_in_client: n/a",
                 "inlined_bytes_headless: n/a"):
        assert line in out
