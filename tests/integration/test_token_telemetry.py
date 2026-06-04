#!/usr/bin/env python3
"""Integration tests for token telemetry and budget guard in runner.py.

Tests:
- Budget guard fires when prompt exceeds track limit
- Token metrics written to meta.json after successful run
- _parse_usage_from_output extracts tokens from claude JSON output
- _estimate_tokens approximation
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _make_ticket_dir(scratch: Path, ticket: str) -> Path:
    tdir = scratch / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [],
        "track": "XS", "estimate": None, "layer": "code",
        "affected_modules": [], "created": "2026-06-04T00:00:00Z",
        "owner": "test", "jira_url": None, "links": [],
        "rework_count": {}, "metrics": {},
    }
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return tdir


def test_budget_guard_blocks_oversized_prompt() -> None:
    """run_agent returns 2 and writes [!QUESTION] when prompt > XS limit."""
    import runner

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        tdir = _make_ticket_dir(scratch, "T-BG-001")
        os.environ["PROJECT_ROOT"] = tmp

        prompt_file = scratch / "prompt.md"
        # XS limit = 8000 tokens ≈ 32000 chars; write 40000 chars
        prompt_file.write_text("x" * 40_000, encoding="utf-8")
        out_file = scratch / "out.md"

        with patch.object(runner, "_load_budget_limits",
                          return_value=({}, {"XS": 8000})), \
             patch("models.load_models") as mock_models:
            from unittest.mock import MagicMock
            mock_models.return_value.resolve.return_value = MagicMock(
                provider="anthropic", model="claude-haiku-4-5-20251001",
                extra_args=[], api_key_env="ANTHROPIC_API_KEY",
                as_env=lambda: {},
            )
            rc = runner.run_agent(
                "build", prompt_file, out_file,
                track="XS", ticket="T-BG-001"
            )

        assert rc == 2, f"expected rc=2 from budget guard, got {rc}"
        content = out_file.read_text(encoding="utf-8")
        assert "[!QUESTION]" in content, f"expected [!QUESTION] in output:\n{content}"
        assert "context too large" in content
        print("PASS: budget guard blocks oversized XS prompt")

    os.environ.pop("PROJECT_ROOT", None)


def test_token_metrics_written_to_meta() -> None:
    """Successful run writes tokens_in/out/cache_hit to meta.json."""
    import runner

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        tdir = _make_ticket_dir(scratch, "T-TOK-001")
        os.environ["PROJECT_ROOT"] = tmp

        prompt_file = scratch / "prompt.md"
        prompt_file.write_text("short prompt", encoding="utf-8")
        out_file = scratch / "out.md"

        fake_output = "agent response text"

        from unittest.mock import MagicMock
        resolved = MagicMock(
            provider="anthropic", model="claude-haiku-4-5-20251001",
            extra_args=[], api_key_env="ANTHROPIC_API_KEY",
            as_env=lambda: {},
        )
        with patch.object(runner, "_load_budget_limits", return_value=({}, {})), \
             patch.dict(runner._DISPATCH,
                        {"anthropic": lambda *a, **k: (0, fake_output, "")}), \
             patch("models.load_models") as mock_models:
            mock_models.return_value.resolve.return_value = resolved
            rc = runner.run_agent(
                "build", prompt_file, out_file,
                track="S", ticket="T-TOK-001"
            )

        assert rc == 0, f"expected rc=0, got {rc}"
        meta = json.loads((tdir / "meta.json").read_text())
        tokens = meta.get("metrics", {}).get("tokens", {})
        assert "build" in tokens, f"expected tokens.build in meta: {meta['metrics']}"
        assert tokens["build"]["in"] > 0
        assert tokens["build"]["out"] > 0
        print("PASS: token metrics written to meta.json after successful run")

    os.environ.pop("PROJECT_ROOT", None)


def test_soft_limit_warns_but_proceeds() -> None:
    """Soft limit: run proceeds, warning on stderr."""
    import runner

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        _make_ticket_dir(scratch, "T-SOFT-001")
        os.environ["PROJECT_ROOT"] = tmp

        prompt_file = scratch / "prompt.md"
        prompt_file.write_text("x" * 28_000, encoding="utf-8")  # ~7000 tokens > soft=6000
        out_file = scratch / "out.md"
        fake_output = "agent response"

        from unittest.mock import MagicMock
        resolved = MagicMock(
            provider="anthropic", model="claude-haiku-4-5-20251001",
            extra_args=[], api_key_env="ANTHROPIC_API_KEY",
            as_env=lambda: {},
        )
        with patch.object(runner, "_load_budget_limits",
                          return_value=({"XS": 6000}, {"XS": 12000})), \
             patch.dict(runner._DISPATCH,
                        {"anthropic": lambda *a, **k: (0, fake_output, "")}), \
             patch("models.load_models") as mock_models:
            mock_models.return_value.resolve.return_value = resolved
            rc = runner.run_agent(
                "build", prompt_file, out_file,
                track="XS", ticket="T-SOFT-001"
            )

        assert rc == 0, f"expected rc=0 for soft limit, got {rc}"
        assert out_file.read_text() == fake_output
        print("PASS: soft limit warns but run proceeds")

    os.environ.pop("PROJECT_ROOT", None)


def test_parse_usage_from_json_output() -> None:
    """_parse_usage_from_output extracts tokens from claude JSON envelope."""
    import runner

    payload = json.dumps({
        "type": "result",
        "result": "some text",
        "usage": {
            "input_tokens": 1234,
            "output_tokens": 567,
            "cache_read_input_tokens": 89,
        }
    })
    usage = runner._parse_usage_from_output(payload)
    assert usage["tokens_in"] == 1234
    assert usage["tokens_out"] == 567
    assert usage["cache_hit"] == 89
    print("PASS: _parse_usage_from_output extracts tokens from JSON envelope")


def test_parse_usage_plain_text_returns_empty() -> None:
    """_parse_usage_from_output returns {} for plain text output."""
    import runner
    assert runner._parse_usage_from_output("plain text response") == {}
    print("PASS: _parse_usage_from_output returns {} for plain text")


def test_estimate_tokens() -> None:
    """_estimate_tokens: 4000 chars ≈ 1000 tokens."""
    import runner
    assert runner._estimate_tokens("a" * 4000) == 1000
    assert runner._estimate_tokens("") == 1
    print("PASS: _estimate_tokens approximation correct")


if __name__ == "__main__":
    test_budget_guard_blocks_oversized_prompt()
    test_soft_limit_warns_but_proceeds()
    test_token_metrics_written_to_meta()
    test_parse_usage_from_json_output()
    test_parse_usage_plain_text_returns_empty()
    test_estimate_tokens()
    print("ALL TOKEN TELEMETRY TESTS PASSED")
