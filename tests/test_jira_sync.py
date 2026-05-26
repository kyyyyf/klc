#!/usr/bin/env python3
"""tests/test_jira_sync.py — unit + integration tests for jira_sync.py.

Run:  python tests/test_jira_sync.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_env(tmp: Path) -> dict[str, str]:
    env = {**os.environ, "PROJECT_ROOT": str(tmp)}
    # ensure no real Jira calls from env
    env.pop("JIRA_TOKEN", None)
    return env


def _write_meta(tmp: Path, ticket: str, phase: str) -> Path:
    tdir = tmp / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / "meta.json"
    p.write_text(json.dumps({"ticket": ticket, "phase": phase}), encoding="utf-8")
    return p


def _write_jira_yml(tmp: Path, content: str) -> None:
    d = tmp / ".klc" / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "jira.yml").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Mapping tests
# ---------------------------------------------------------------------------

class TestResolveStatus(unittest.TestCase):
    def setUp(self):
        import jira_sync
        self.rs = jira_sync._resolve_status
        self.mapping = {
            "build": "In Progress",
            "review": "In Review",
            "build:ack": "Code Review",
            "archived": "Done",
        }

    def test_phase_id_match(self):
        self.assertEqual(self.rs("build:work", {"phase_to_status": self.mapping}), "In Progress")

    def test_full_phase_overrides_id(self):
        self.assertEqual(self.rs("build:ack", {"phase_to_status": self.mapping}), "Code Review")

    def test_archived(self):
        self.assertEqual(self.rs("archived", {"phase_to_status": self.mapping}), "Done")

    def test_no_mapping(self):
        self.assertIsNone(self.rs("observe:work", {"phase_to_status": self.mapping}))

    def test_empty_mapping(self):
        self.assertIsNone(self.rs("build:work", {}))


# ---------------------------------------------------------------------------
# 2. Queue tests
# ---------------------------------------------------------------------------

class TestQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_env = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.tmp)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._orig_env
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reload(self):
        import importlib
        import jira_sync
        importlib.reload(jira_sync)
        return jira_sync

    def test_queue_size_empty(self):
        js = self._reload()
        self.assertEqual(js.queue_size(), 0)

    def test_enqueue_increments(self):
        js = self._reload()
        js._enqueue("PROJ-1", "build:work", "In Progress", "test")
        self.assertEqual(js.queue_size(), 1)
        js._enqueue("PROJ-1", "review:work", "In Review", "test")
        self.assertEqual(js.queue_size(), 2)

    def test_flush_deduplicates(self):
        """flush_queue sends only the last status per ticket."""
        js = self._reload()
        _write_jira_yml(self.tmp, "sync:\n  enabled: true\n  transport: rest\n  rest:\n    base_url: http://nowhere\n  phase_to_status:\n    build: In Progress\n")
        os.environ["JIRA_TOKEN"] = "fake"

        calls = []

        def fake_push(self_t, ticket, status):
            calls.append((ticket, status))

        with patch.object(js._RestTransport, "push", fake_push):
            js._enqueue("PROJ-1", "build:work", "In Progress", "t")
            js._enqueue("PROJ-1", "review:work", "In Review", "t")
            js._enqueue("PROJ-1", "learn:work", "Done", "t")
            result = js.flush_queue(quiet=True)

        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("PROJ-1", "Done"))

    def test_flush_rewrites_queue_on_partial_failure(self):
        js = self._reload()
        _write_jira_yml(self.tmp, "sync:\n  enabled: true\n  transport: rest\n  rest:\n    base_url: http://nowhere\n  phase_to_status:\n    build: In Progress\n")
        os.environ["JIRA_TOKEN"] = "fake"

        call_count = [0]

        def fail_push(self_t, ticket, status):
            call_count[0] += 1
            raise RuntimeError("network error")

        with patch.object(js._RestTransport, "push", fail_push):
            js._enqueue("PROJ-1", "build:work", "In Progress", "t")
            js._enqueue("PROJ-2", "build:work", "In Progress", "t")
            result = js.flush_queue(quiet=True)

        self.assertEqual(result["failed"], 2)
        self.assertEqual(js.queue_size(), 2)

    def test_flush_clears_queue_on_success(self):
        js = self._reload()
        _write_jira_yml(self.tmp, "sync:\n  enabled: true\n  transport: rest\n  rest:\n    base_url: http://nowhere\n  phase_to_status:\n    build: In Progress\n")
        os.environ["JIRA_TOKEN"] = "fake"
        _write_meta(self.tmp, "PROJ-1", "build:work")

        with patch.object(js._RestTransport, "push", lambda *a: None):
            js._enqueue("PROJ-1", "build:work", "In Progress", "t")
            result = js.flush_queue(quiet=True)

        self.assertEqual(result["sent"], 1)
        self.assertEqual(js.queue_size(), 0)


# ---------------------------------------------------------------------------
# 3. push_phase disabled by default
# ---------------------------------------------------------------------------

class TestPushPhaseDisabled(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_env = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.tmp)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._orig_env
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_disabled_by_default_no_network(self):
        """With sync.enabled=false (default), push_phase must not make any calls."""
        import importlib
        import jira_sync
        importlib.reload(jira_sync)

        enqueue_calls = []
        with patch.object(jira_sync, "_enqueue", lambda *a: enqueue_calls.append(a)):
            jira_sync.push_phase("PROJ-1", "build:work")

        self.assertEqual(enqueue_calls, [])

    def test_enabled_with_unmapped_phase_is_noop(self):
        """A phase not present in any phase_to_status mapping must not push or enqueue."""
        import importlib
        import jira_sync
        importlib.reload(jira_sync)

        _write_jira_yml(self.tmp, "sync:\n  enabled: true\n  transport: rest\n  rest:\n    base_url: http://nowhere\n  phase_to_status:\n    build: In Progress\n")

        enqueue_calls = []
        with patch.object(jira_sync, "_enqueue", lambda *a: enqueue_calls.append(a)):
            # "custom-nonexistent" is not in any mapping
            jira_sync.push_phase("PROJ-1", "custom-nonexistent:work")

        self.assertEqual(enqueue_calls, [])


# ---------------------------------------------------------------------------
# 4. Idempotency — skip if status unchanged
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_env = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.tmp)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._orig_env
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skip_if_last_sync_matches(self):
        import importlib
        import jira_sync
        importlib.reload(jira_sync)

        _write_jira_yml(self.tmp, "sync:\n  enabled: true\n  transport: rest\n  rest:\n    base_url: http://nowhere\n  phase_to_status:\n    build: In Progress\n")
        os.environ["JIRA_TOKEN"] = "fake"

        meta_path = _write_meta(self.tmp, "PROJ-1", "build:work")
        meta = json.loads(meta_path.read_text())
        meta["jira_last_sync"] = {"status": "In Progress", "phase": "build:work", "at": "2026-01-01T00:00:00Z"}
        meta_path.write_text(json.dumps(meta))

        push_calls = []
        with patch.object(jira_sync._RestTransport, "push",
                          lambda *a: push_calls.append(a)):
            jira_sync.push_phase("PROJ-1", "build:work")

        self.assertEqual(push_calls, [])


# ---------------------------------------------------------------------------
# 5. Integration test — mock HTTP server (REST transport)
# ---------------------------------------------------------------------------

class MockJiraHandler(BaseHTTPRequestHandler):
    """Minimal Jira API mock: GET transitions, GET issue status, POST transition."""
    transitions = [
        {"id": "10", "name": "To In Progress",
         "to": {"name": "In Progress"}},
        {"id": "20", "name": "To In Review",
         "to": {"name": "In Review"}},
    ]
    current_status = {"name": "To Do"}
    received_transitions: list = []

    def log_message(self, *args):
        pass

    def _send_json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if "transitions" in self.path:
            self._send_json(200, {"transitions": self.transitions})
        elif "fields=status" in self.path:
            self._send_json(200, {"fields": {"status": self.current_status}})
        else:
            self._send_json(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        MockJiraHandler.received_transitions.append(body)
        MockJiraHandler.current_status = {"name": "In Progress"}
        self._send_json(204, {})


class TestRestTransportIntegration(unittest.TestCase):
    server: HTTPServer
    thread: threading.Thread

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockJiraHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        MockJiraHandler.received_transitions.clear()
        MockJiraHandler.current_status = {"name": "To Do"}
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_env = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.tmp)
        os.environ["JIRA_TOKEN"] = "test-token"

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._orig_env
        os.environ.pop("JIRA_TOKEN", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rest(self):
        import importlib
        import jira_sync
        importlib.reload(jira_sync)
        cfg = {"base_url": f"http://127.0.0.1:{self.port}"}
        return jira_sync._RestTransport(cfg, timeout=5.0)

    def test_push_sends_correct_transition(self):
        t = self._rest()
        t.push("PROJ-1", "In Progress")
        self.assertEqual(len(MockJiraHandler.received_transitions), 1)
        self.assertEqual(
            MockJiraHandler.received_transitions[0]["transition"]["id"], "10"
        )

    def test_push_idempotent_when_already_at_status(self):
        MockJiraHandler.current_status = {"name": "In Progress"}
        t = self._rest()
        t.push("PROJ-1", "In Progress")
        self.assertEqual(len(MockJiraHandler.received_transitions), 0)

    def test_push_enqueues_on_network_error(self):
        import importlib
        import jira_sync
        importlib.reload(jira_sync)

        _write_meta(self.tmp, "PROJ-1", "build:work")
        _write_jira_yml(
            self.tmp,
            f"sync:\n  enabled: true\n  transport: rest\n"
            f"  rest:\n    base_url: http://127.0.0.1:19999\n"
            f"  phase_to_status:\n    build: In Progress\n",
        )
        jira_sync.push_phase("PROJ-1", "build:work")
        self.assertEqual(jira_sync.queue_size(), 1)


# ---------------------------------------------------------------------------
# 6. Smoke regression: sync disabled → no side effects
# ---------------------------------------------------------------------------

class TestSyncDisabledRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_env = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.tmp)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._orig_env
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_queue_file_created(self):
        import importlib
        import jira_sync
        importlib.reload(jira_sync)

        jira_sync.push_phase("PROJ-99", "build:work")
        queue_file = self.tmp / ".klc" / "jira-queue.jsonl"
        self.assertFalse(queue_file.exists())

    def test_flush_on_empty_queue_returns_zero(self):
        import importlib
        import jira_sync
        importlib.reload(jira_sync)

        result = jira_sync.flush_queue(quiet=True)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["remaining"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
