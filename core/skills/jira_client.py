#!/usr/bin/env python3
"""jira_client.py — thin, injectable Jira REST client.

Exports:
    JiraClient        — Protocol (interface)
    RestJiraClient    — real urllib implementation (no extra deps)
    FakeJiraClient    — in-memory fake for tests
    make_client(cfg)  — factory: returns RestJiraClient for real use

All methods raise RuntimeError on HTTP/network errors with a descriptive
message. Tests inject FakeJiraClient to run with zero network.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_file_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_file_dir))


# ---------------------------------------------------------------------------
# Protocol (interface)
# ---------------------------------------------------------------------------

class JiraClient:
    """Protocol-like base; subclass or duck-type."""

    def get_issue(self, key: str) -> dict:
        raise NotImplementedError

    def get_transitions(self, key: str) -> list[dict]:
        raise NotImplementedError

    def transition_issue(self, key: str, transition_id: str,
                         fields: dict | None = None) -> None:
        raise NotImplementedError

    def add_comment(self, key: str, body: str) -> dict:
        raise NotImplementedError

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        raise NotImplementedError

    def get_issue_comments(self, key: str) -> list[dict]:
        raise NotImplementedError

    def get_current_user(self) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Real REST implementation
# ---------------------------------------------------------------------------

class RestJiraClient(JiraClient):
    """Jira REST API v3 client using stdlib urllib only."""

    def __init__(self, base_url: str, auth_env: str, auth_user_env: str = "",
                 timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._auth_env = auth_env
        self._user_env = auth_user_env
        self._timeout = timeout

    def _token(self) -> str:
        t = os.environ.get(self._auth_env, "")
        if not t:
            raise RuntimeError(
                f"Jira auth: env var {self._auth_env!r} is not set"
            )
        return t

    def _auth_header(self) -> str:
        if self._user_env:
            user = os.environ.get(self._user_env, "")
            if user:
                import base64
                creds = base64.b64encode(
                    f"{user}:{self._token()}".encode()
                ).decode()
                return f"Basic {creds}"
        return f"Bearer {self._token()}"

    def _request(self, method: str, url: str,
                 body: dict | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"Jira HTTP {exc.code} {url}: {body_text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Jira network error {url}: {exc.reason}") from exc

    def get_issue(self, key: str) -> dict:
        url = f"{self._base}/rest/api/3/issue/{key}"
        return self._request("GET", url)

    def get_transitions(self, key: str) -> list[dict]:
        url = f"{self._base}/rest/api/3/issue/{key}/transitions"
        data = self._request("GET", url)
        return data.get("transitions") or []

    def transition_issue(self, key: str, transition_id: str,
                         fields: dict | None = None) -> None:
        url = f"{self._base}/rest/api/3/issue/{key}/transitions"
        body: dict = {"transition": {"id": transition_id}}
        if fields:
            body["fields"] = fields
        self._request("POST", url, body)

    def add_comment(self, key: str, body: str) -> dict:
        url = f"{self._base}/rest/api/3/issue/{key}/comment"
        payload = {"body": {"type": "doc", "version": 1,
                             "content": [{"type": "paragraph",
                                          "content": [{"type": "text",
                                                       "text": body}]}]}}
        return self._request("POST", url, payload)

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        url = f"{self._base}/rest/api/3/issue/{key}/comment/{comment_id}"
        payload = {"body": {"type": "doc", "version": 1,
                             "content": [{"type": "paragraph",
                                          "content": [{"type": "text",
                                                       "text": body}]}]}}
        self._request("PUT", url, payload)

    def get_issue_comments(self, key: str) -> list[dict]:
        url = f"{self._base}/rest/api/3/issue/{key}/comment"
        data = self._request("GET", url)
        return data.get("comments") or []

    def get_current_user(self) -> dict:
        url = f"{self._base}/rest/api/3/myself"
        return self._request("GET", url)


# ---------------------------------------------------------------------------
# Fake client for tests
# ---------------------------------------------------------------------------

@dataclass
class FakeJiraClient(JiraClient):
    """In-memory Jira client for tests. Zero network, records all calls."""

    issues: dict[str, dict] = field(default_factory=dict)
    transitions_map: dict[str, list[dict]] = field(default_factory=dict)
    comments_map: dict[str, list[dict]] = field(default_factory=dict)
    current_user: dict = field(default_factory=lambda: {"name": "testuser",
                                                         "emailAddress": "test@example.com"})
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)
    _comment_id_counter: int = field(default=100, repr=False)

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, args, kwargs))

    def get_issue(self, key: str) -> dict:
        self._record("get_issue", key)
        if key not in self.issues:
            raise RuntimeError(f"Jira HTTP 404 /rest/api/3/issue/{key}: Not Found")
        return self.issues[key]

    def get_transitions(self, key: str) -> list[dict]:
        self._record("get_transitions", key)
        return self.transitions_map.get(key, [])

    def transition_issue(self, key: str, transition_id: str,
                         fields: dict | None = None) -> None:
        self._record("transition_issue", key, transition_id, fields=fields)

    def add_comment(self, key: str, body: str) -> dict:
        self._record("add_comment", key, body)
        self._comment_id_counter += 1
        comment = {"id": str(self._comment_id_counter), "body": body}
        self.comments_map.setdefault(key, []).append(comment)
        return comment

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        self._record("update_comment", key, comment_id, body)
        comments = self.comments_map.get(key, [])
        for c in comments:
            if c["id"] == comment_id:
                c["body"] = body
                return

    def get_issue_comments(self, key: str) -> list[dict]:
        self._record("get_issue_comments", key)
        return self.comments_map.get(key, [])

    def get_current_user(self) -> dict:
        self._record("get_current_user")
        return self.current_user

    def recorded_calls(self, method: str) -> list[tuple]:
        """Return all recorded calls for a given method name."""
        return [(args, kwargs) for m, args, kwargs in self.calls if m == method]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_client(cfg: Any) -> JiraClient:
    """Return RestJiraClient configured from JiraConfig.

    Intentionally accepts Any so the import doesn't force a jira_config import
    in tests. Duck-typed: reads .base_url, .auth_env, .auth_user_env.
    """
    return RestJiraClient(
        base_url=cfg.base_url,
        auth_env=cfg.auth_env,
        auth_user_env=cfg.auth_user_env,
    )
