"""KLC-172 step-1 (AC-1, AC-2): real token usage from Claude Code subagent
transcripts, imported into the per-ticket telemetry as `source: transcript`.

Hermetic: every test builds its own fake `~/.claude/projects/<slug>/` tree
and its own PROJECT_ROOT; nothing reads the operator's real transcripts.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))


# --- fixtures ---------------------------------------------------------------

def _usage(inp, cache_read, cache_create, out):
    return {"input_tokens": inp, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_create, "output_tokens": out}


def _assistant(msg_id, usage, model="claude-sonnet-5", ts="2026-10-02T10:00:01Z"):
    return {"type": "assistant", "timestamp": ts, "isSidechain": True,
            "message": {"id": msg_id, "role": "assistant", "model": model,
                        "usage": usage, "content": [{"type": "text", "text": "ok"}]}}


def _user(text, ts="2026-10-02T10:00:00Z"):
    return {"type": "user", "timestamp": ts, "isSidechain": True,
            "message": {"role": "user", "content": text}}


def _write_agent(session_dir: Path, agent_id: str, lines: list, *, agent_type: str,
                 description: str = "work", live: bool = False) -> Path:
    sub = session_dir / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"agent-{agent_id}.jsonl"
    path.write_text("".join(json.dumps(l) + "\n" if not isinstance(l, str) else l
                            for l in lines), encoding="utf-8")
    (sub / f"agent-{agent_id}.meta.json").write_text(
        json.dumps({"agentType": agent_type, "description": description}),
        encoding="utf-8")
    if not live:                       # settled run: older than the live window
        old = time.time() - 3600
        os.utime(path, (old, old))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / ".klc" / "tickets").mkdir(parents=True)
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    return root


def _seed_ticket(root: Path, key: str) -> Path:
    tdir = root / ".klc" / "tickets" / key
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "meta.json").write_text(json.dumps({
        "ticket": key, "kind": "tech", "phase": "build:work", "track": "S",
        "phase_history": [], "affected_modules": [], "metrics": {}}) + "\n",
        encoding="utf-8")
    return tdir


def _attempts(key: str) -> list[tuple[str, dict]]:
    import metrics
    meta = json.loads((Path(metrics._read_meta.__globals__["klc_ticket_meta_file"](key))).read_text())
    return metrics.iter_attempts(meta, key)


# --- AC-1 -------------------------------------------------------------------

def test_import_sums_subagent_usage_and_is_idempotent(project, tmp_path):
    import token_import

    _seed_ticket(project, "KLC-900")
    pdir = tmp_path / "claude-projects" / "-home-x-project"
    session = pdir / "11111111-aaaa"
    _write_agent(session, "a1", [
        _user("Implement step 2 of KLC-900."),
        _assistant("m1", _usage(10, 1000, 500, 40)),
        _assistant("m1", _usage(10, 1000, 500, 40)),     # streamed duplicate of m1
        "{not json\n",                                     # torn line: skipped
        _assistant("m2", _usage(5, 2000, 0, 60), ts="2026-10-02T10:05:00Z"),
    ], agent_type="klc-impl")

    recs = token_import.import_transcripts(pdir, ticket="KLC-900")
    assert len(recs) == 1
    rec = recs[0]
    assert rec["source"] == "transcript"
    assert rec["in"] == 15 and rec["out"] == 100
    assert rec["cache_hit"] == 3000 and rec["cache_write"] == 500
    assert rec["model"] == "claude-sonnet-5"
    assert rec["agent_id"] == "a1"
    assert rec["ts"] == "2026-10-02T10:00:00Z"          # first message time

    # phase derived from the agent type: klc-impl is the build prompt
    attempts = _attempts("KLC-900")
    assert [(p, r["id"]) for p, r in attempts] == [("build", rec["id"])]

    # idempotent: a second import adds nothing
    assert token_import.import_transcripts(pdir, ticket="KLC-900") == []
    assert len(_attempts("KLC-900")) == 1


def test_ticket_inferred_from_first_message_and_unknown_agent_type(project, tmp_path):
    import token_import

    _seed_ticket(project, "KLC-901")
    pdir = tmp_path / "claude-projects" / "-home-x-project"
    _write_agent(pdir / "s1", "b2", [
        _user("Review the changes on branch feature/klc-901 for ticket KLC-901."),
        _assistant("m1", _usage(1, 2, 3, 4)),
    ], agent_type="code-reviewer")
    # an agent whose text names no ticket is skipped, not fatal
    _write_agent(pdir / "s1", "c3", [
        _user("General exploration with no key."),
        _assistant("m9", _usage(1, 1, 1, 1)),
    ], agent_type="Explore")

    recs = token_import.import_transcripts(pdir)
    assert [r["agent_id"] for r in recs] == ["b2"]
    attempts = _attempts("KLC-901")
    assert len(attempts) == 1
    phase, rec = attempts[0]
    assert phase == "review"                 # code-reviewer maps to the review phase
    assert rec["agent_type"] == "code-reviewer"


def test_cli_reports_imported_count(project, tmp_path):
    _seed_ticket(project, "KLC-902")
    pdir = tmp_path / "claude-projects" / "-home-x-project"
    _write_agent(pdir / "s1", "d4", [
        _user("KLC-902 step 1"), _assistant("m1", _usage(1, 0, 0, 1)),
    ], agent_type="klc-impl")
    res = subprocess.run(
        [sys.executable, str(FW / "core" / "skills" / "token_import.py"),
         "--project-dir", str(pdir), "--ticket", "KLC-902"],
        capture_output=True, text=True, env={**__import__("os").environ})
    assert res.returncode == 0, res.stderr
    assert "imported 1" in res.stdout


def test_default_project_dir_is_the_claude_code_slug(tmp_path, monkeypatch):
    import token_import
    monkeypatch.setenv("HOME", str(tmp_path))
    got = token_import.default_project_dir(Path("/home/ek/projects/klc"))
    assert got == tmp_path / ".claude" / "projects" / "-home-ek-projects-klc"


def test_default_project_dir_uses_project_root_and_every_non_alnum(tmp_path, monkeypatch):
    import token_import
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "my.proj_x"
    root.mkdir()
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.chdir(tmp_path)
    got = token_import.default_project_dir()
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))
    assert got == tmp_path / ".claude" / "projects" / slug
    assert "." not in got.name and "_" not in got.name


# --- AC-2 -------------------------------------------------------------------

def test_attempt_record_keeps_measured_fields_for_transcript_source():
    import budget_guard
    rec = budget_guard.attempt_record(10, 2, 7, "transcript", None,
                                      cache_write=5, num_turns=3)
    assert rec["cache_hit"] == 7
    assert rec["cache_write"] == 5 and rec["num_turns"] == 3
    est = budget_guard.attempt_record(10, 2, 7, "estimated", 100, cache_write=5)
    assert est["cache_hit"] == 0 and "cache_write" not in est


def test_rollup_counts_transcript_as_measured_source(project, monkeypatch):
    import metrics
    tdir = _seed_ticket(project, "KLC-903")
    meta = json.loads((tdir / "meta.json").read_text())
    meta["phase"] = "build:ack"
    meta["metrics"] = {"tokens": {"build": {"attempts": [
        {"id": "t1", "ts": "2026-10-02T10:00:00Z", "in": 10, "out": 5,
         "cache_hit": 100, "cache_write": 20, "source": "transcript",
         "model": "claude-sonnet-5", "agent_id": "a1", "agent_type": "klc-impl"},
        {"id": "e1", "ts": "2026-10-02T10:00:00Z", "in": 30, "out": 3,
         "cache_hit": 0, "source": "estimated", "card_bytes": 120},
    ]}}}
    (tdir / "meta.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    assert metrics.cmd_rollup(None) == 0
    out = project / ".klc" / "knowledge" / "process-metrics.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    bucket = payload["per_track"]["S"]["tokens_by_phase"]["build"]
    assert bucket["source_counts"]["transcript"] == 1
    assert bucket["source_counts"]["estimated"] == 1
    assert bucket["by_source"]["transcript"]["samples"] == 1
    assert "avg_cache_write" in bucket["by_source"]["transcript"]


def test_token_backfill_is_gone():
    assert not (FW / "core" / "skills" / "token_backfill.py").exists()
    assert not (FW / "tests" / "integration" / "test_klc119_backfill.py").exists()


# --- KLC-172 review round 1 --------------------------------------------------

def test_inference_beats_ticket_flag_and_each_run_lands_once(project, tmp_path):
    """F-003: the key named in the first message wins; --ticket is only the
    fallback, so a run is never recorded against two tickets."""
    import token_import
    _seed_ticket(project, "KLC-910")
    _seed_ticket(project, "KLC-911")
    pdir = tmp_path / "cp" / "-x"
    _write_agent(pdir / "s1", "p1", [_user("work on KLC-910"),
                                     _assistant("m1", _usage(1, 0, 0, 1))],
                 agent_type="klc-impl")
    _write_agent(pdir / "s1", "p2", [_user("work on KLC-911"),
                                     _assistant("m1", _usage(2, 0, 0, 2))],
                 agent_type="klc-impl")
    token_import.import_transcripts(pdir, ticket="KLC-910")
    token_import.import_transcripts(pdir, ticket="KLC-911")
    ids = lambda k: sorted(r["agent_id"] for _, r in _attempts(k))  # noqa: E731
    assert ids("KLC-910") == ["p1"] and ids("KLC-911") == ["p2"]
    # a run naming no key falls back to --ticket
    _write_agent(pdir / "s1", "p3", [_user("no key at all"),
                                     _assistant("m1", _usage(3, 0, 0, 3))],
                 agent_type="klc-impl")
    token_import.import_transcripts(pdir, ticket="KLC-911")
    assert ids("KLC-911") == ["p2", "p3"] and ids("KLC-910") == ["p1"]


def test_inference_skips_non_ticket_key_shaped_tokens(project, tmp_path):
    """F-004: `AC-2` / `UTF-8` come first but have no meta.json."""
    import token_import
    _seed_ticket(project, "KLC-900")
    pdir = tmp_path / "cp" / "-x"
    _write_agent(pdir / "s1", "q1", [_user("Fix AC-2 (UTF-8) in KLC-900"),
                                     _assistant("m1", _usage(1, 0, 0, 1))],
                 agent_type="klc-impl")
    recs = token_import.import_transcripts(pdir)
    assert [r["agent_id"] for r in recs] == ["q1"]


def test_live_transcript_skipped_unless_include_live(project, tmp_path):
    """F-005: a transcript touched in the last 10 minutes may still be running."""
    import token_import
    _seed_ticket(project, "KLC-920")
    pdir = tmp_path / "cp" / "-x"
    path = _write_agent(pdir / "s1", "r1", [_user("KLC-920"),
                                            _assistant("m1", _usage(1, 0, 0, 1))],
                        agent_type="klc-impl", live=True)
    assert token_import.import_transcripts(pdir) == []          # just written: live
    old = time.time() - 3600
    os.utime(path, (old, old))                                  # now settled
    assert [r["agent_id"] for r in token_import.import_transcripts(pdir)] == ["r1"]
    _write_agent(pdir / "s1", "r2", [_user("KLC-920"),
                                     _assistant("m1", _usage(1, 0, 0, 1))],
                 agent_type="klc-impl", live=True)
    assert token_import.import_transcripts(pdir) == []
    recs = token_import.import_transcripts(pdir, include_live=True)
    assert [r["agent_id"] for r in recs] == ["r2"]


def test_malformed_meta_skips_that_ticket_only(project, tmp_path, capsys):
    """F-013: one corrupt meta.json never aborts the import."""
    import token_import
    bad = _seed_ticket(project, "KLC-930")
    (bad / "meta.json").write_text("{corrupt")
    _seed_ticket(project, "KLC-931")
    pdir = tmp_path / "cp" / "-x"
    _write_agent(pdir / "s1", "t1", [_user("KLC-930"), _assistant("m1", _usage(1, 0, 0, 1))],
                 agent_type="klc-impl")
    _write_agent(pdir / "s1", "t2", [_user("KLC-931"), _assistant("m1", _usage(1, 0, 0, 1))],
                 agent_type="klc-impl")
    recs = token_import.import_transcripts(pdir)
    assert [r["agent_id"] for r in recs] == ["t2"]
    assert "KLC-930" in capsys.readouterr().err


def test_journal_drain_keeps_transcript_fields(project, monkeypatch):
    """F-002: model / agent_id / agent_type survive the journal drain."""
    import state_feature
    import state_tx
    import token_journal
    monkeypatch.setattr(state_feature, "enabled", lambda: False)
    tdir = _seed_ticket(project, "KLC-940")
    token_journal.append("KLC-940", {
        "id": "tr1", "ts": "2026-10-02T10:00:00Z", "in": 1, "out": 2, "cache_hit": 3,
        "source": "transcript", "phase": "build", "cache_write": 4,
        "model": "claude-x", "agent_id": "a1", "agent_type": "klc-impl"})
    with state_tx.state_tx("KLC-940", "drain"):
        pass
    meta = json.loads((tdir / "meta.json").read_text())
    rec = meta["metrics"]["tokens"]["build"]["attempts"][0]
    assert (rec["model"], rec["agent_id"], rec["agent_type"]) == ("claude-x", "a1", "klc-impl")


def test_ticket_id_loader_project_then_framework_then_default(project):
    """F-012: one loader, project override first."""
    import ticket_id
    pat = ticket_id.key_pattern()
    assert pat.match("KLC-12") and not pat.match("klc-12")
    assert ticket_id.find_keys("Fix AC-2 in KLC-900, not XUTF-8x") == ["AC-2", "KLC-900"]
    cfg = project / ".klc" / "config"
    cfg.mkdir(parents=True)
    (cfg / "ticket-id.yml").write_text("pattern: '^PRJ-\\d+$'\n")
    assert ticket_id.find_keys("AC-2 PRJ-7 KLC-1") == ["PRJ-7"]
    (cfg / "ticket-id.yml").write_text("pattern: '^(unclosed$'\n")
    assert ticket_id.key_pattern().match("KLC-1")        # malformed -> default
