#!/usr/bin/env python3
"""Integration tests for KLC-020: Jira core read-only + enrich.

All tests use FakeJiraClient — zero network required.
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

os.environ.setdefault("PROJECT_ROOT", str(tempfile.mkdtemp(prefix="klc-jira-test-")))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jira_config_dir(tmp: Path, extra: dict | None = None) -> Path:
    """Write minimal valid jira.yml to tmp/config/jira.yml (YAML format)."""
    cfg_dir = tmp / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # Write as explicit YAML text (no yaml.dump needed)
    content = """\
enabled: true
mode: mirror
site:
  base_url: "https://jira.example.com"
  project_key: "KLC"
  auth_env: "JIRA_API_TOKEN"
  auth_user_env: ""
gitlab:
  base_url: "https://gitlab.example.com/group/repo"
  branch: "main"
  blob_url: "{base_url}/-/blob/{branch}/{path}"
status_mapping:
  klc_to_jira:
    review: "In Review"
    build: "In Progress"
  jira_to_klc:
    "In Review": [review]
    "In Progress": [build]
artifacts:
  comment_links: true
  paths:
    spec: "spec.md"
    build_log: "build-log.md"
"""
    (cfg_dir / "jira.yml").write_text(content, encoding="utf-8")
    return cfg_dir


def _make_ticket(tmp: Path, key: str, phase: str = "review:work") -> Path:
    tdir = tmp / ".klc" / "tickets" / key
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": key, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [],
        "track": "S", "estimate": None, "layer": "code",
        "affected_modules": [], "created": "2026-06-05T00:00:00Z",
        "owner": "test", "jira_url": None, "links": [],
        "rework_count": {}, "metrics": {},
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (tdir / "raw.md").write_text(f"---\nticket: {key}\n---\nTest ticket.\n")
    return tdir


# ---------------------------------------------------------------------------
# AC-2: jira_config.py
# ---------------------------------------------------------------------------

def test_jira_config_loads_valid() -> None:
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = _make_jira_config_dir(Path(tmp))
        cfg = jc.load(cfg_dir)
        assert cfg.enabled
        assert cfg.base_url == "https://jira.example.com"
        assert cfg.project_key == "KLC"
        assert "review" in cfg.klc_to_jira
    print("PASS: jira_config loads valid config")


def test_jira_config_missing_base_url() -> None:
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "jira.yml").write_text(
            "enabled: true\n"
            "site:\n  project_key: KLC\n  auth_env: TOKEN\n"
            "gitlab:\n  base_url: x\n  blob_url: '{base_url}/-/blob/{branch}/{path}'\n"
            "status_mapping:\n  klc_to_jira:\n    x: y\n  jira_to_klc:\n    y: [x]\n"
        )
        try:
            jc.load(cfg_dir)
            assert False, "should have raised"
        except jc.JiraConfigError as exc:
            assert "base_url" in str(exc)
    print("PASS: jira_config rejects missing base_url")


def test_jira_config_missing_auth_env() -> None:
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "jira.yml").write_text(
            "enabled: true\n"
            "site:\n  base_url: 'https://x.com'\n  project_key: K\n"
            "gitlab:\n  base_url: x\n  blob_url: '{base_url}/-/blob/{branch}/{path}'\n"
            "status_mapping:\n  klc_to_jira:\n    x: y\n  jira_to_klc:\n    y: [x]\n"
        )
        try:
            jc.load(cfg_dir)
            assert False, "should have raised"
        except jc.JiraConfigError as exc:
            assert "auth_env" in str(exc)
    print("PASS: jira_config rejects missing auth_env")


def test_jira_config_malformed_blob_url() -> None:
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "jira.yml").write_text(
            "enabled: true\n"
            "site:\n  base_url: 'https://x.com'\n  project_key: K\n  auth_env: T\n"
            "gitlab:\n  base_url: x\n  blob_url: '{base_url}/-/blob/{branch}'\n"
            "status_mapping:\n  klc_to_jira:\n    x: y\n  jira_to_klc:\n    y: [x]\n"
        )
        try:
            jc.load(cfg_dir)
            assert False, "should have raised"
        except jc.JiraConfigError as exc:
            assert "{path}" in str(exc)
    print("PASS: jira_config rejects malformed blob_url template")


# ---------------------------------------------------------------------------
# AC-3: jira_client.py FakeJiraClient
# ---------------------------------------------------------------------------

def test_fake_client_get_issue() -> None:
    from jira_client import FakeJiraClient
    c = FakeJiraClient(issues={"KLC-1": {"key": "KLC-1", "fields": {"status": {"name": "In Review"}}}})
    issue = c.get_issue("KLC-1")
    assert issue["key"] == "KLC-1"
    assert c.recorded_calls("get_issue")
    print("PASS: FakeJiraClient.get_issue returns canned data, records call")


def test_fake_client_get_issue_not_found() -> None:
    from jira_client import FakeJiraClient
    c = FakeJiraClient()
    try:
        c.get_issue("MISSING-1")
        assert False, "should raise"
    except RuntimeError as exc:
        assert "404" in str(exc)
    print("PASS: FakeJiraClient.get_issue raises 404 for unknown key")


def test_fake_client_add_and_update_comment() -> None:
    from jira_client import FakeJiraClient
    c = FakeJiraClient(issues={"K-1": {}})
    result = c.add_comment("K-1", "first comment")
    cid = result["id"]
    assert c.comments_map["K-1"][0]["body"] == "first comment"
    c.update_comment("K-1", cid, "updated comment")
    assert c.comments_map["K-1"][0]["body"] == "updated comment"
    assert len(c.recorded_calls("add_comment")) == 1
    assert len(c.recorded_calls("update_comment")) == 1
    print("PASS: FakeJiraClient add_comment + update_comment work correctly")


def test_rest_client_missing_auth_env() -> None:
    from jira_client import RestJiraClient
    client = RestJiraClient("https://x.com", auth_env="NONEXISTENT_ENV_VAR_12345")
    try:
        client._token()
        assert False, "should raise"
    except RuntimeError as exc:
        assert "NONEXISTENT_ENV_VAR_12345" in str(exc)
    print("PASS: RestJiraClient raises RuntimeError for missing auth env var")


# ---------------------------------------------------------------------------
# AC-4: jira_artifacts.py
# ---------------------------------------------------------------------------

def test_artifact_links_existing_files() -> None:
    from jira_artifacts import build_artifact_links, ARTIFACT_LINK_MARKER
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_jira_config_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)

        ticket_dir = _make_ticket(Path(tmp), "T-ART-001")
        (ticket_dir / "spec.md").write_text("# spec\n")
        # build-log.md is absent

        body = build_artifact_links("T-ART-001", cfg)
        assert "spec" in body.lower() or "spec.md" in body
        assert "build-log" not in body.lower()  # absent file omitted
        assert ARTIFACT_LINK_MARKER.format(key="T-ART-001") in body
    print("PASS: build_artifact_links includes existing files, omits missing")


def test_artifact_links_no_files() -> None:
    from jira_artifacts import build_artifact_links
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_jira_config_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "T-EMPTY-001")
        body = build_artifact_links("T-EMPTY-001", cfg)
        assert "no artefacts" in body.lower() or len(body) > 0  # no crash
    print("PASS: build_artifact_links handles empty ticket without error")


def test_artifact_links_idempotent() -> None:
    from jira_artifacts import upsert_artifact_links, ARTIFACT_LINK_MARKER
    from jira_client import FakeJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_jira_config_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "T-IDEM-001")

        marker = ARTIFACT_LINK_MARKER.format(key="T-IDEM-001")
        client = FakeJiraClient(issues={"T-IDEM-001": {}})

        # First call: should add_comment
        upsert_artifact_links(client, "T-IDEM-001", "T-IDEM-001", cfg)
        assert len(client.recorded_calls("add_comment")) == 1
        assert len(client.recorded_calls("update_comment")) == 0

        # Second call: should update_comment, NOT add again
        upsert_artifact_links(client, "T-IDEM-001", "T-IDEM-001", cfg)
        assert len(client.recorded_calls("add_comment")) == 1  # still 1
        assert len(client.recorded_calls("update_comment")) == 1
    print("PASS: upsert_artifact_links is idempotent (update, not duplicate)")


# ---------------------------------------------------------------------------
# AC-8 + AC-5: klc jira status via subprocess
# ---------------------------------------------------------------------------

def test_jira_status_disabled() -> None:
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".klc" / "config").mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PROJECT_ROOT"] = tmp
        r = subprocess.run(
            [sys.executable, str(FW_ROOT / "scripts" / "klc"), "jira", "status", "KLC-X"],
            env=env, capture_output=True, text=True, timeout=10,
        )
        assert r.returncode != 0
        assert "not enabled" in r.stderr
    print("PASS: klc jira status exits non-zero when integration disabled")


# ---------------------------------------------------------------------------
# Additional tests for review-report findings
# ---------------------------------------------------------------------------

def test_jira_config_https_required() -> None:
    """site.base_url with http:// must be rejected (security)."""
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "jira.yml").write_text(
            "enabled: true\n"
            "site:\n  base_url: 'http://jira.example.com'\n  project_key: K\n  auth_env: T\n"
            "gitlab:\n  base_url: x\n  blob_url: '{base_url}/-/blob/{branch}/{path}'\n"
            "status_mapping:\n  klc_to_jira:\n    x: y\n  jira_to_klc:\n    y: [x]\n"
        )
        try:
            jc.load(cfg_dir)
            assert False, "should have raised"
        except jc.JiraConfigError as exc:
            assert "https" in str(exc).lower()
    print("PASS: jira_config rejects http:// base_url (requires https)")


def test_jira_config_missing_klc_to_jira() -> None:
    """Missing klc_to_jira mapping raises JiraConfigError."""
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "jira.yml").write_text(
            "enabled: true\n"
            "site:\n  base_url: 'https://jira.example.com'\n  project_key: K\n  auth_env: T\n"
            "gitlab:\n  base_url: x\n  blob_url: '{base_url}/-/blob/{branch}/{path}'\n"
            "status_mapping:\n  jira_to_klc:\n    y: [x]\n"  # missing klc_to_jira
        )
        try:
            jc.load(cfg_dir)
            assert False, "should have raised"
        except jc.JiraConfigError as exc:
            assert "klc_to_jira" in str(exc)
    print("PASS: jira_config rejects missing klc_to_jira mapping")


def test_jira_config_managed_tickets_non_list() -> None:
    """managed_tickets as non-list raises JiraConfigError."""
    import jira_config as jc
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = _make_jira_config_dir(Path(tmp))
        # Overwrite with invalid managed_tickets type
        content = (cfg_dir / "jira.yml").read_text()
        (cfg_dir / "jira.yml").write_text(content + "managed_tickets: KLC-001\n")
        try:
            jc.load(cfg_dir)
            assert False, "should have raised"
        except jc.JiraConfigError as exc:
            assert "list" in str(exc).lower()
    print("PASS: jira_config rejects non-list managed_tickets")


def test_fake_client_get_transitions() -> None:
    """FakeJiraClient.get_transitions returns canned transitions."""
    from jira_client import FakeJiraClient
    c = FakeJiraClient(
        issues={"KLC-1": {}},
        transitions_map={"KLC-1": [{"id": "10", "to": {"name": "In Review"}}]},
    )
    transitions = c.get_transitions("KLC-1")
    assert len(transitions) == 1
    assert transitions[0]["id"] == "10"
    assert c.recorded_calls("get_transitions")
    print("PASS: FakeJiraClient.get_transitions returns canned list")


def test_fake_client_transition_issue() -> None:
    """FakeJiraClient.transition_issue records the call."""
    from jira_client import FakeJiraClient
    c = FakeJiraClient(issues={"KLC-1": {}})
    c.transition_issue("KLC-1", "10")
    calls = c.recorded_calls("transition_issue")
    assert calls
    assert calls[0][0][0] == "KLC-1"
    assert calls[0][0][1] == "10"
    print("PASS: FakeJiraClient.transition_issue records call")


def test_fake_client_get_current_user() -> None:
    """FakeJiraClient.get_current_user returns canned user dict."""
    from jira_client import FakeJiraClient
    c = FakeJiraClient()
    user = c.get_current_user()
    assert "name" in user or "emailAddress" in user
    assert c.recorded_calls("get_current_user")
    print("PASS: FakeJiraClient.get_current_user returns canned user")


def test_make_client_returns_rest_client() -> None:
    """make_client() with a JiraConfig returns a RestJiraClient instance."""
    from jira_client import make_client, RestJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = _make_jira_config_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        client = make_client(cfg)
        assert isinstance(client, RestJiraClient)
    print("PASS: make_client() returns RestJiraClient")


def test_artifact_link_url_format() -> None:
    """Artefact link URLs match blob_url template exactly."""
    from jira_artifacts import build_artifact_links, ARTIFACT_LINK_MARKER
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_jira_config_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)

        td = _make_ticket(Path(tmp), "T-URL-001")
        (td / "spec.md").write_text("# spec\n")

        body = build_artifact_links("T-URL-001", cfg)
        assert "https://gitlab.example.com/group/repo" in body
        assert "main" in body
        assert "spec.md" in body
    print("PASS: artefact links contain correct gitlab base_url, branch, and path")


def test_upsert_skips_write_on_comment_read_failure() -> None:
    """upsert_artifact_links skips write when get_issue_comments fails (no duplicate)."""
    from jira_artifacts import upsert_artifact_links
    from jira_client import FakeJiraClient
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PROJECT_ROOT"] = tmp
        cfg_dir = _make_jira_config_dir(Path(tmp))
        import jira_config as jc
        cfg = jc.load(cfg_dir)
        _make_ticket(Path(tmp), "T-ERR-001")

        class FailingCommentsClient(FakeJiraClient):
            def get_issue_comments(self, key):
                raise RuntimeError("HTTP 503: Service Unavailable")

        client = FailingCommentsClient(issues={"T-ERR-001": {}})
        import io, sys as _sys
        stderr_capture = io.StringIO()
        _orig = _sys.stderr
        _sys.stderr = stderr_capture
        try:
            upsert_artifact_links(client, "T-ERR-001", "T-ERR-001", cfg)
        finally:
            _sys.stderr = _orig

        assert not client.recorded_calls("add_comment"), "must not add comment on read failure"
        assert "skipped" in stderr_capture.getvalue()
    print("PASS: upsert_artifact_links skips write on comment read failure (AC-8 safety)")


def test_jira_status_match_and_mismatch() -> None:
    """klc jira status: exit 0 on match, exit 1 on mismatch; always read-only."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        cfg_dir = _make_jira_config_dir(scratch)
        _make_ticket(scratch, "T-ST-001", "review:work")
        os.environ["PROJECT_ROOT"] = tmp

        import jira_config as jc
        cfg = jc.load(cfg_dir)

        from jira_client import FakeJiraClient
        # Import cmd_status — patch jira._load_config (the module-level helper)
        sys.path.insert(0, str(FW_ROOT / "core" / "phases"))
        import jira as _jira_mod

        def _cfg_match(*a, **kw):
            return cfg

        # Match case: Jira == "In Review", klc_to_jira[review] == "In Review"
        fake_match = FakeJiraClient(
            issues={"T-ST-001": {"fields": {"status": {"name": "In Review"}}}}
        )
        with patch.object(_jira_mod, "_load_config", return_value=cfg), \
             patch("jira_client.make_client", return_value=fake_match):
            rc = _jira_mod.cmd_status(["T-ST-001"])
        assert rc == 0, f"expected 0 for in-sync, got {rc}"

        # Mismatch case: Jira == "In Progress"
        fake_mismatch = FakeJiraClient(
            issues={"T-ST-001": {"fields": {"status": {"name": "In Progress"}}}}
        )
        import io
        buf = io.StringIO()
        with patch.object(_jira_mod, "_load_config", return_value=cfg), \
             patch("jira_client.make_client", return_value=fake_mismatch), \
             patch("builtins.print", side_effect=lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            rc = _jira_mod.cmd_status(["T-ST-001"])
        assert rc == 1, f"expected 1 for mismatch, got {rc}"
        assert "MISMATCH" in buf.getvalue()

        # Read-only: no writes in either case
        assert not fake_match.recorded_calls("transition_issue")
        assert not fake_match.recorded_calls("add_comment")
        assert not fake_mismatch.recorded_calls("transition_issue")
        assert not fake_mismatch.recorded_calls("add_comment")
    print("PASS: klc jira status exits 0 on match, 1 on mismatch; read-only verified")


if __name__ == "__main__":
    test_jira_config_loads_valid()
    test_jira_config_missing_base_url()
    test_jira_config_missing_auth_env()
    test_jira_config_malformed_blob_url()
    test_jira_config_https_required()
    test_jira_config_missing_klc_to_jira()
    test_jira_config_managed_tickets_non_list()
    test_fake_client_get_issue()
    test_fake_client_get_issue_not_found()
    test_fake_client_add_and_update_comment()
    test_fake_client_get_transitions()
    test_fake_client_transition_issue()
    test_fake_client_get_current_user()
    test_make_client_returns_rest_client()
    test_rest_client_missing_auth_env()
    test_artifact_links_existing_files()
    test_artifact_links_no_files()
    test_artifact_links_idempotent()
    test_artifact_link_url_format()
    test_upsert_skips_write_on_comment_read_failure()
    test_jira_status_disabled()
    test_jira_status_match_and_mismatch()
    print("ALL JIRA CORE TESTS PASSED")
