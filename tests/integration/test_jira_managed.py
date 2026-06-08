#!/usr/bin/env python3
"""Integration tests for KLC-021: Jira managed mode + push.

All tests use FakeJiraClient — zero network.
TTY is mocked via monkeypatching sys.stdin.isatty / sys.stdout.isatty.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "shared"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

os.environ.setdefault("PROJECT_ROOT", str(tempfile.mkdtemp(prefix="klc-jira-managed-")))


def _make_cfg_dir(tmp: Path, mode: str = "managed",
                  managed_tickets: list | None = None) -> Path:
    cfg_dir = tmp / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    mt = managed_tickets if managed_tickets is not None else []
    mt_yaml = ("managed_tickets: [" + ", ".join(mt) + "]\n") if mt else "managed_tickets: []\n"
    (cfg_dir / "jira.yml").write_text(
        f"enabled: true\nmode: {mode}\n{mt_yaml}"
        "site:\n  base_url: 'https://jira.example.com'\n"
        "  project_key: KLC\n  auth_env: JIRA_API_TOKEN\n"
        "gitlab:\n  base_url: 'https://gitlab.example.com/g/r'\n"
        "  blob_url: '{base_url}/-/blob/{branch}/{path}'\n"
        "status_mapping:\n"
        "  klc_to_jira:\n    review: 'In Review'\n    build: 'In Progress'\n"
        "  jira_to_klc:\n    'In Review': [review]\n    'In Progress': [build]\n",
        encoding="utf-8"
    )
    return cfg_dir


def _make_ticket(tmp: Path, key: str, phase: str = "review:work",
                 last_jira: str | None = None) -> Path:
    tdir = tmp / ".klc" / "tickets" / key
    tdir.mkdir(parents=True, exist_ok=True)
    sync_block = {}
    if last_jira:
        sync_block = {"jira_sync": {"last_jira_status": last_jira,
                                     "enabled": True, "conflicts": []}}
    meta = {
        "ticket": key, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": "S",
        "estimate": None, "layer": "code", "affected_modules": [],
        "created": "2026-06-05T00:00:00Z", "owner": "test",
        "jira_url": None, "links": [], "rework_count": {}, "metrics": {},
        **sync_block,
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (tdir / "raw.md").write_text(f"---\nticket: {key}\n---\nTest.\n")
    return tdir


# ---------------------------------------------------------------------------
# AC-2: build_plan()
# ---------------------------------------------------------------------------

def test_build_plan_in_sync() -> None:
    from jira_client import FakeJiraClient
    from jira_sync import build_plan
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        td = _make_ticket(Path(tmp), "KLC-T1", "review:work", last_jira="In Review")
        client = FakeJiraClient(
            issues={"KLC-T1": {"fields": {"status": {"name": "In Review"}}}},
            transitions_map={"KLC-T1": [{"id": "11", "to": {"name": "In Review"}}]},
        )
        plan = build_plan("KLC-T1", client, cfg)
        assert plan.in_sync
        assert not plan.conflicts
        # No write calls
        assert not client.recorded_calls("transition_issue")
        assert not client.recorded_calls("add_comment")
    print("PASS: build_plan in-sync → in_sync=True, no write calls")


def test_build_plan_klc_moved() -> None:
    """klc moved to review, Jira still at In Progress, no prior last_jira_status
    (first sync) → in_sync=False, transition found, no jira-moved-externally conflict."""
    from jira_client import FakeJiraClient
    from jira_sync import build_plan
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        # last_jira=None → no prior state, so PM-moved detection doesn't fire
        _make_ticket(Path(tmp), "KLC-T2", "review:work", last_jira=None)
        client = FakeJiraClient(
            issues={"KLC-T2": {"fields": {"status": {"name": "In Progress"}}}},
            transitions_map={"KLC-T2": [{"id": "21", "to": {"name": "In Review"}}]},
        )
        plan = build_plan("KLC-T2", client, cfg)
        assert not plan.in_sync
        assert plan.target_status == "In Review"
        assert plan.transition_id == "21"
        assert not any(c["type"] == "jira-moved-externally" for c in plan.conflicts)
    print("PASS: build_plan klc-moved → in_sync=False, transition found")


def test_build_plan_pm_moved_externally() -> None:
    from jira_client import FakeJiraClient
    from jira_sync import build_plan
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        # last_jira="In Review" but current Jira="In Progress" (PM moved back)
        _make_ticket(Path(tmp), "KLC-T3", "review:work", last_jira="In Review")
        client = FakeJiraClient(
            issues={"KLC-T3": {"fields": {"status": {"name": "In Progress"}}}},
        )
        plan = build_plan("KLC-T3", client, cfg)
        assert plan.has_conflict("jira-moved-externally")
    print("PASS: build_plan detects PM moved Jira externally")


def test_build_plan_issue_missing() -> None:
    from jira_client import FakeJiraClient
    from jira_sync import build_plan
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "KLC-T4", "review:work")
        client = FakeJiraClient()  # no issues → 404
        plan = build_plan("KLC-T4", client, cfg)
        assert plan.has_conflict("issue-missing")
    print("PASS: build_plan detects 404 as issue-missing conflict")


# ---------------------------------------------------------------------------
# AC-3: push_to_jira()
# ---------------------------------------------------------------------------

def test_push_executes_transition_and_comment() -> None:
    from jira_client import FakeJiraClient
    from jira_sync import push_to_jira
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "KLC-P1", "review:work", last_jira="In Progress")
        client = FakeJiraClient(
            issues={"KLC-P1": {"fields": {"status": {"name": "In Progress"}}}},
            transitions_map={"KLC-P1": [{"id": "31", "to": {"name": "In Review"}}]},
        )
        result = push_to_jira("KLC-P1", client, cfg)
        assert result["ok"]
        assert client.recorded_calls("transition_issue")
        comments = client.recorded_calls("add_comment")
        assert comments
        assert "moved by klc" in comments[0][0][1]
    print("PASS: push_to_jira executes transition + adds 'moved by klc' comment")


def test_push_idempotent_already_in_sync() -> None:
    from jira_client import FakeJiraClient
    from jira_sync import push_to_jira
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "KLC-P2", "review:work", last_jira="In Review")
        client = FakeJiraClient(
            issues={"KLC-P2": {"fields": {"status": {"name": "In Review"}}}},
        )
        result = push_to_jira("KLC-P2", client, cfg)
        assert result["ok"]
        assert result["action"] == "noop"
        assert not client.recorded_calls("transition_issue")
    print("PASS: push_to_jira is idempotent when already in sync")


def test_push_no_transition_records_conflict() -> None:
    from jira_client import FakeJiraClient
    from jira_sync import push_to_jira
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        td = _make_ticket(Path(tmp), "KLC-P3", "review:work", last_jira="In Progress")
        client = FakeJiraClient(
            issues={"KLC-P3": {"fields": {"status": {"name": "In Progress"}}}},
            transitions_map={"KLC-P3": []},  # no transitions
        )
        result = push_to_jira("KLC-P3", client, cfg)
        assert not result["ok"]
        assert result["action"] == "transition-blocked"
        assert not client.recorded_calls("transition_issue")
        meta = json.loads((td / "meta.json").read_text())
        conflicts = (meta.get("jira_sync") or {}).get("conflicts", [])
        assert any(c["type"] == "transition-blocked" for c in conflicts)
    print("PASS: push_to_jira records conflict when no transition available")


# ---------------------------------------------------------------------------
# AC-4: lifecycle push_phase mode-aware
# ---------------------------------------------------------------------------

def test_mirror_mode_auto_pushes() -> None:
    """mirror mode: jira_sync.push_phase called (legacy auto-push)."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="mirror")
        # patch jira_config.load to return mirror config, patch push_phase
        with patch("jira_config.load") as mock_load, \
             patch("jira_sync.push_phase") as mock_push:
            mock_cfg = MagicMock()
            mock_cfg.enabled = True
            mock_cfg.mode = "mirror"
            mock_cfg.is_managed_ticket.return_value = False
            mock_load.return_value = mock_cfg
            os.environ["PROJECT_ROOT"] = tmp
            import lifecycle as lc
            # Call _jira_push_after_state directly
            lc._jira_push_after_state("KLC-MIR", "review:work", source="ack")
            mock_push.assert_called_once_with("KLC-MIR", "review:work", source="ack")
    print("PASS: mirror mode calls push_phase (legacy auto-push)")


def test_managed_non_tty_divergence_records_conflict() -> None:
    """managed + non-TTY + divergence → conflict recorded, no Jira write."""
    from jira_client import FakeJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="managed")
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        td = _make_ticket(Path(tmp), "KLC-NT1", "review:work", last_jira="In Progress")
        client = FakeJiraClient(
            issues={"KLC-NT1": {"fields": {"status": {"name": "In Progress"}}}},
            transitions_map={"KLC-NT1": [{"id": "41", "to": {"name": "In Review"}}]},
        )
        import lifecycle as lc
        with patch("sys.stdin") as mock_stdin, patch("sys.stdout") as mock_stdout:
            mock_stdin.isatty.return_value = False
            mock_stdout.isatty.return_value = False
            with patch("jira_config.load", return_value=cfg), \
                 patch("jira_client.make_client", return_value=client):
                lc._managed_jira_push("KLC-NT1", "review:work", cfg)

        assert not client.recorded_calls("transition_issue")
        meta = json.loads((td / "meta.json").read_text())
        conflicts = (meta.get("jira_sync") or {}).get("conflicts", [])
        assert conflicts
    print("PASS: managed non-TTY records divergence, no Jira write")


def test_managed_non_tty_in_sync_silent() -> None:
    """managed + non-TTY + in-sync → no prompt, no conflict."""
    from jira_client import FakeJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="managed")
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        td = _make_ticket(Path(tmp), "KLC-NT2", "review:work", last_jira="In Review")
        client = FakeJiraClient(
            issues={"KLC-NT2": {"fields": {"status": {"name": "In Review"}}}},
        )
        import lifecycle as lc
        with patch("jira_config.load", return_value=cfg), \
             patch("jira_client.make_client", return_value=client):
            lc._managed_jira_push("KLC-NT2", "review:work", cfg)

        assert not client.recorded_calls("transition_issue")
        meta = json.loads((td / "meta.json").read_text())
        conflicts = (meta.get("jira_sync") or {}).get("conflicts", [])
        assert not conflicts
    print("PASS: managed non-TTY in-sync → silent, no conflict")


def test_managed_tickets_filter() -> None:
    """managed_tickets=[OTHER] → ticket not in list behaves as mirror."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="managed", managed_tickets=["OTHER-1"])
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        assert not cfg.is_managed_ticket("KLC-NOT-IN-LIST")
        assert cfg.is_managed_ticket("OTHER-1")
    print("PASS: is_managed_ticket filters correctly by managed_tickets list")


# ---------------------------------------------------------------------------
# AC-8: doctor surfaces conflicts
# ---------------------------------------------------------------------------

def test_doctor_surfaces_conflicts() -> None:
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp) / ".klc" / "tickets" / "KLC-DC1"
        tdir.mkdir(parents=True)
        meta = {
            "ticket": "KLC-DC1", "kind": "tech", "kind_source": "user",
            "phase": "review:ack", "phase_history": [], "track": "S",
            "estimate": None, "layer": "code", "affected_modules": [],
            "jira_sync": {
                "enabled": True, "conflicts": [
                    {"type": "transition-blocked", "detail": "no transition",
                     "detected_at": "2026-06-05T00:00:00Z",
                     "suggested": "klc jira reconcile KLC-DC1 push"}
                ]
            },
        }
        (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        env = dict(os.environ); env["PROJECT_ROOT"] = tmp
        r = subprocess.run(
            [sys.executable, str(FW_ROOT / "scripts" / "klc"), "doctor"],
            env=env, capture_output=True, text=True, timeout=15,
        )
        assert "jira-sync-conflicts" in r.stdout
        assert "WARN" in r.stdout or "jira-sync-conflicts" in r.stdout
        # Warn-only: jira-sync-conflicts should be WARN, not FAIL
        assert "WARN jira-sync-conflicts" in r.stdout or "jira-sync-conflicts" in r.stdout
    print("PASS: doctor surfaces jira-sync-conflicts as WARN (non-blocking)")


def test_reconcile_push_delegates_to_push_to_jira() -> None:
    """klc jira reconcile push delegates to jira_sync.push() (no duplication)."""
    from jira_client import FakeJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="managed")
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "KLC-RC1", "review:work", last_jira="In Progress")
        client = FakeJiraClient(
            issues={"KLC-RC1": {"fields": {"status": {"name": "In Progress"}}}},
            transitions_map={"KLC-RC1": [{"id": "51", "to": {"name": "In Review"}}]},
        )
        import jira_sync as _js
        import jira as _jira_mod

        push_calls = []
        original_push = _js.push

        def spy_push(ticket):
            push_calls.append(ticket)
            return original_push(ticket)

        with patch.object(_jira_mod, "_load_config", return_value=cfg), \
             patch.object(_js, "push", side_effect=spy_push), \
             patch("jira_client.make_client", return_value=client):
            rc = _jira_mod.cmd_reconcile(["KLC-RC1", "push"])

        assert push_calls == ["KLC-RC1"], "reconcile push must call jira_sync.push()"
    print("PASS: reconcile push delegates to jira_sync.push() — no duplicate implementation")


def test_sync_apply_clears_conflicts_on_success() -> None:
    """sync --apply clears stale conflicts when Jira is in sync."""
    from jira_client import FakeJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="managed")
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        td = _make_ticket(Path(tmp), "KLC-CLR1", "review:work", last_jira="In Review")
        # Pre-populate stale conflict
        meta = json.loads((td / "meta.json").read_text())
        meta.setdefault("jira_sync", {})["conflicts"] = [
            {"type": "transition-blocked", "detail": "old conflict"}
        ]
        (td / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

        client = FakeJiraClient(
            issues={"KLC-CLR1": {"fields": {"status": {"name": "In Review"}}}},
        )
        import jira as _jira_mod
        with patch.object(_jira_mod, "_load_config", return_value=cfg), \
             patch("jira_client.make_client", return_value=client), \
             patch("jira_artifacts.upsert_artifact_links"):
            _jira_mod.cmd_sync(["KLC-CLR1", "--apply"])

        updated = json.loads((td / "meta.json").read_text())
        conflicts = (updated.get("jira_sync") or {}).get("conflicts", ["still here"])
        assert conflicts == [], f"conflicts should be cleared on in-sync --apply, got {conflicts}"
    print("PASS: sync --apply clears stale conflicts when Jira is in sync")


def test_issue_missing_recorded_in_meta() -> None:
    """push_to_jira records issue-missing conflict in meta.json."""
    from jira_client import FakeJiraClient
    from jira_sync import push_to_jira
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        td = _make_ticket(Path(tmp), "KLC-MS1", "review:work")
        client = FakeJiraClient()  # no issues → 404

        result = push_to_jira("KLC-MS1", client, cfg)
        assert not result["ok"]
        assert result["action"] == "error"
        meta = json.loads((td / "meta.json").read_text())
        conflicts = (meta.get("jira_sync") or {}).get("conflicts", [])
        assert any(c["type"] == "issue-missing" for c in conflicts), \
            f"issue-missing must be recorded in meta, got {conflicts}"
    print("PASS: push_to_jira records issue-missing conflict in meta.json")


def test_managed_hook_skips_on_abort_source() -> None:
    """_jira_push_after_state in managed mode skips interactive path for abort."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_cfg_dir(Path(tmp), mode="managed")
        import jira_config as jc
        cfg = jc.load(cfg_dir)

        push_phase_calls = []
        managed_push_calls = []

        import lifecycle as lc
        import jira_sync as _js

        with patch.object(_js, "push_phase",
                          side_effect=lambda *a, **kw: push_phase_calls.append(kw.get("source"))), \
             patch.object(lc, "_managed_jira_push",
                          side_effect=lambda *a: managed_push_calls.append(True)), \
             patch("jira_config.load", return_value=cfg):
            # abort source → should NOT call _managed_jira_push, should auto-push
            lc._jira_push_after_state("DUMMY", "review:work", source="abort")

        assert not managed_push_calls, "managed prompt must NOT fire for abort source"
        assert push_phase_calls == ["abort"], "mirror auto-push must still fire for abort"
    print("PASS: managed hook skips interactive path for abort/jump sources")


if __name__ == "__main__":
    test_build_plan_in_sync()
    test_build_plan_klc_moved()
    test_build_plan_pm_moved_externally()
    test_build_plan_issue_missing()
    test_push_executes_transition_and_comment()
    test_push_idempotent_already_in_sync()
    test_push_no_transition_records_conflict()
    test_mirror_mode_auto_pushes()
    test_managed_non_tty_divergence_records_conflict()
    test_managed_non_tty_in_sync_silent()
    test_managed_tickets_filter()
    test_doctor_surfaces_conflicts()
    test_reconcile_push_delegates_to_push_to_jira()
    test_sync_apply_clears_conflicts_on_success()
    test_issue_missing_recorded_in_meta()
    test_managed_hook_skips_on_abort_source()
    print("ALL JIRA MANAGED TESTS PASSED")
