"""KLC-177 step-6: review round 1 fixes.

Gate allow-list by verb and the hook tests live in test_plugin_hooks.py; this
file pins the clarify stop, dry-run with --until, the rework reason in the build
step card, one stop reason per --until line, the guard that no card or message
teaches a removed verb, --until target validation and the unified exit codes.
In-process with a tmp PROJECT_ROOT (feature-off).
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (_FW, _FW / "core" / "skills", _FW / "core" / "phases"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_CLEAN = {
    "advisory": {"records": [], "threshold": "medium"},
    "scope_expansion": False, "sentinels": False, "mutation": False,
    "budget_overrun": False, "verdict": "APPROVED", "route_confidence": "high",
}
REASON = "the acceptance criteria miss the offline case"


def _flush():
    import core.skills.phases as a
    a._CACHE = None
    import phases as b
    b._CACHE = None


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_AUTORUN_CAP", raising=False)
    _flush()
    import gate_policy
    import autorunner
    import runner

    def _boom(*a, **k):
        raise AssertionError("go --until must never dispatch an agent")

    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(_CLEAN))
    monkeypatch.setattr(autorunner, "_dispatch", _boom)
    monkeypatch.setattr(runner, "run_agent", _boom)
    return tmp_path


def _ticket(root: Path, key: str, phase: str, track: str = "S", **extra) -> Path:
    td = root / ".klc" / "tickets" / key
    td.mkdir(parents=True)
    meta = {"ticket": key, "kind": "feature", "phase": phase, "track": track,
            "route_confidence": "high", "affected_modules": [], "layer": "code",
            "budgets": {"mutation_fix_attempts": 0}, "risk_tags": [],
            "phase_history": [], "rework_count": {}}
    meta.update(extra)
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return td


def _go(argv):
    import go
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = int(go.run(list(argv)))
    return rc, out.getvalue(), err.getvalue()


def _back(argv):
    import back
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = int(back.run(list(argv)))
    return rc, out.getvalue(), err.getvalue()


def _meta(td: Path) -> dict:
    return json.loads((td / "meta.json").read_text(encoding="utf-8"))


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(root).parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


# --- F-002: the intake clarify stop -------------------------------------------

def test_clarify_required_intake_is_a_clarify_move_and_until_stops_naming_it(proj):
    td = _ticket(proj, "C-1", "intake:ack-needed", clarify_required=True,
                 route_confidence="low")
    import next_move
    move = next_move.compute("C-1")
    assert move.action == "clarify"
    assert "clarify needed" in next_move.render(move)

    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["C-1", "--until", "integrate"])
    assert rc == 2, err
    assert (td / "meta.json").read_bytes() == before
    line = out.strip()
    assert "\n" not in line
    assert "clarify needed" in line and "--pick" not in line

    # once the flag is cleared the ticket is an ordinary pick stop again
    m = _meta(td)
    m["clarify_required"] = False
    (td / "meta.json").write_text(json.dumps(m), encoding="utf-8")
    assert next_move.compute("C-1").action != "clarify"


def test_run_skill_clarify_triggers_on_the_clarify_stop_line():
    t = " ".join((_FW / "klc-plugin" / "skills" / "go" / "SKILL.md")
                 .read_text(encoding="utf-8").split())
    assert "clarify needed" in t
    assert "one reason" in t.lower()
    assert "merge" in t and "klc go <KEY> --pick 1" in t
    assert "run `klc go` again" in t


# --- F-004: dry-run with until -------------------------------------------------

def test_dry_run_with_until_prints_first_move_only_and_writes_nothing(proj):
    _ticket(proj, "DR-1", "review:ack")
    before = _tree_hash(proj)
    rc, out, err = _go(["DR-1", "--until", "integrate", "--dry-run"])
    assert rc == 0, err
    assert _tree_hash(proj) == before
    assert "dry-run shows the first move only" in out
    assert not list((proj / ".klc").rglob("run-log.md"))


# --- F-005: the rework reason reaches the build step card -----------------------

def test_step_card_and_phase_card_carry_the_rework_request(proj):
    import artefacts
    td = _ticket(proj, "RW-1", "build:work", impl_step=2, rework=[
        {"from": "review:work", "to": "build", "reason": REASON}])
    meta = _meta(td)
    step = artefacts.write_step_card("RW-1", 2, meta)
    assert "## Rework request" in step.read_text(encoding="utf-8")
    assert REASON in step.read_text(encoding="utf-8")
    phase_card = artefacts.render_card("RW-1", "build", meta).path
    assert REASON in phase_card.read_text(encoding="utf-8")


def test_back_to_build_renders_the_step_card_that_go_and_status_name(proj):
    td = _ticket(proj, "RW-2", "review:work", impl_step=2)
    (td / "impl-plan.md").write_text("# plan\n", encoding="utf-8")
    rc, out, err = _back(["RW-2", "build", "--reason", REASON])
    assert rc == 0, err
    import next_move
    card = Path(next_move.compute("RW-2").card)
    assert card.name.startswith("_prompt_step_")
    assert card.exists(), "back must render the card the status line points at"
    assert REASON in card.read_text(encoding="utf-8")


def test_go_at_build_work_renders_the_step_card_when_missing(proj):
    _ticket(proj, "RW-3", "build:work")
    import next_move
    card = Path(next_move.compute("RW-3").card)
    assert not card.exists()
    rc, out, err = _go(["RW-3"])
    assert rc == 2, err
    assert card.exists()


# --- F-006: one stop reason per --until line -------------------------------------

def test_cap_stop_at_unfinished_work_says_cap_and_not_the_agent(proj):
    _ticket(proj, "S-1", "build:ack-needed")
    rc, out, err = _go(["S-1", "--until", "integrate", "--cap", "1"])
    assert rc == 2, err
    line = out.strip()
    assert "cap" in line and "needs the agent" not in line
    assert "\n" not in line


def test_fresh_build_stop_names_build_not_green_once_and_not_the_agent(proj):
    _ticket(proj, "S-2", "build:work")
    rc, out, err = _go(["S-2", "--until", "review"])
    assert rc == 2, err
    line = out.strip()
    assert "build is not green" in line and "needs the agent" not in line
    assert "_prompt_step_" in line


def test_agent_card_stop_still_names_the_agent(proj):
    _ticket(proj, "S-3", "review:work")
    rc, out, err = _go(["S-3", "--until", "integrate"])
    assert rc == 2, err
    assert "needs the agent" in out


# --- F-007: no card or message teaches a removed verb ----------------------------

_OLD_CMD = re.compile(r"\bklc (?:ack|next|ship|jump|abort|work)(?![\w-])")
# the deprecated verbs' own modules talk about themselves
_EXEMPT = {"ack.py", "next.py", "jump.py", "abort.py", "ship.py", "run.py", "work.py"}


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant):
                doc_ids.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in doc_ids:
            yield node.lineno, node.value


def test_no_card_or_cli_message_teaches_a_removed_verb():
    bad = []
    for pattern in ("core/skills/*.py", "core/phases/*.py", "klc-plugin/hooks/*.py"):
        for f in sorted(_FW.glob(pattern)):
            if f.name in _EXEMPT:
                continue
            for lineno, s in _string_literals(f):
                for ln in s.splitlines():
                    if "deprecat" not in ln.lower() and _OLD_CMD.search(ln):
                        bad.append(f"{f.relative_to(_FW)}:{lineno}: {ln.strip()[:90]}")
    for f in sorted((_FW / "core" / "templates").glob("*.j2")):
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "deprecat" not in ln.lower() and _OLD_CMD.search(ln):
                bad.append(f"{f.relative_to(_FW)}:{i}: {ln.strip()[:90]}")
    assert not bad, "\n".join(bad)


def test_status_has_no_dead_work_card_helpers():
    import status
    assert not hasattr(status, "_work_card") and not hasattr(status, "_ack_command")


# --- F-012: --until validates its target; --pick with --until ---------------------

def test_until_rejects_off_track_and_behind_targets(proj):
    td = _ticket(proj, "V-1", "build:ack-needed", track="S")
    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["V-1", "--until", "discovery"])           # not on the S track
    assert rc == 2 and "discovery" in err
    td2 = _ticket(proj, "V-2", "review:work", track="S")
    rc, out, err = _go(["V-2", "--until", "build"])               # behind the ticket
    assert rc == 2 and "build" in err
    assert (td / "meta.json").read_bytes() == before


def test_pick_with_until_applies_to_the_first_pick_stop_else_is_refused(proj):
    td = _ticket(proj, "V-3", "discovery:ack-needed", track="M")
    rc, out, err = _go(["V-3", "--until", "build", "--pick", "1"])
    assert _meta(td)["phase"] != "discovery:ack-needed", (out, err)

    td2 = _ticket(proj, "V-4", "build:ack-needed")
    before = (td2 / "meta.json").read_bytes()
    rc, out, err = _go(["V-4", "--until", "integrate", "--pick", "1"])
    assert rc == 2 and "--pick" in err
    assert (td2 / "meta.json").read_bytes() == before


# --- F-011: refusals exit 2 in go and back ----------------------------------------

def test_validation_refusals_exit_2_in_go_and_back(proj):
    rc, _, err = _go(["NOPE-1"])
    assert rc == 2 and "NOPE-1" in err
    rc, _, err = _go(["NOPE-1", "--until", "nonsense"])
    assert rc == 2
    _ticket(proj, "X-1", "build:ack-needed")
    rc, _, err = _go(["X-1", "--until", "nonsense"])
    assert rc == 2 and "nonsense" in err
    rc, _, err = _back(["NOPE-1", "build", "--reason", "x"])
    assert rc == 2 and "NOPE-1" in err


# --- F-015: read-only guarantees ported to go --dry-run ---------------------------

def test_dry_run_legacy_phase_is_not_migrated(proj):
    td = _ticket(proj, "L-1", "build-pending")
    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["L-1", "--dry-run"])
    assert rc == 0, err
    assert (td / "meta.json").read_bytes() == before
    assert "build" in out


def test_dry_run_corrupt_phase_exits_nonzero_without_traceback(proj):
    td = _ticket(proj, "L-2", "garbage-no-colon")
    before = (td / "meta.json").read_bytes()
    for argv in (["L-2", "--dry-run"], ["L-2", "--dry-run", "--json"]):
        rc, out, err = _go(argv)
        assert rc != 0
        assert "traceback" not in (out + err).lower() and "L-2" in (out + err)
    assert (td / "meta.json").read_bytes() == before
    _ticket(proj, "L-3", "nope:work")
    rc, out, err = _go(["L-3", "--dry-run"])
    assert rc != 0 and "traceback" not in (out + err).lower()


def test_dry_run_unknown_ticket_creates_nothing(proj):
    rc, out, err = _go(["L-404", "--dry-run"])
    assert rc != 0 and "L-404" in err
    assert not (proj / ".klc" / "tickets" / "L-404").exists()


def test_dry_run_with_the_real_gate_signals_is_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"],
           "HOME": str(tmp_path)}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(cmd, cwd=tmp_path, env=env, check=True, capture_output=True)
    for key, phase in (("R-1", "build:ack-needed"), ("R-2", "review:work")):
        _ticket(tmp_path, key, phase)
        before = _tree_hash(tmp_path)
        rc, out, err = _go([key, "--dry-run"])
        assert rc == 0, err
        assert _tree_hash(tmp_path) == before
        assert out.strip() and "\n" not in out.strip()
