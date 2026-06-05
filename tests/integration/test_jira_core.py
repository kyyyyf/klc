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


if __name__ == "__main__":
    test_jira_config_loads_valid()
    test_jira_config_missing_base_url()
    test_jira_config_missing_auth_env()
    test_jira_config_malformed_blob_url()
    test_fake_client_get_issue()
    test_fake_client_get_issue_not_found()
    test_fake_client_add_and_update_comment()
    test_rest_client_missing_auth_env()
    test_artifact_links_existing_files()
    test_artifact_links_no_files()
    test_artifact_links_idempotent()
    test_jira_status_disabled()
    print("ALL JIRA CORE TESTS PASSED")
