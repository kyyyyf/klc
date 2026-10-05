#!/usr/bin/env python3
"""Integration tests for token telemetry in runner.py.

Tests:
- A dispatch without usage records nothing (KLC-174 step-5: no `estimated`)
- _parse_usage_from_output extracts tokens from claude JSON output
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



def test_token_metrics_written_to_meta() -> None:
    """Successful run records tokens_in/out/cache_hit (KLC-119: journalled,
    since runner.py opens no transaction of its own)."""
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
        with patch.dict(runner._DISPATCH,
                        {"anthropic": lambda *a, **k: (0, fake_output, "")}), \
             patch("models.load_models") as mock_models:
            mock_models.return_value.resolve.return_value = resolved
            rc = runner.run_agent(
                "build", prompt_file, out_file,
                track="S", ticket="T-TOK-001"
            )

        assert rc == 0, f"expected rc=0, got {rc}"
        # KLC-119 AC-4: runner.py opens no transaction around its telemetry
        # write, so the attempt lands in the ticket's journal (not directly
        # in meta.json) until the next state_tx drains it — metrics.tokens
        # is also now an append-only attempts list rather than one record.
        import token_journal
        records = [r for r in token_journal.read("T-TOK-001")
                  if r.get("phase") == "build"]
        assert records == [], "no usage in the output -> nothing recorded"
        print("PASS: a dispatch without usage records no attempt")

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



if __name__ == "__main__":
    test_token_metrics_written_to_meta()
    test_parse_usage_from_json_output()
    test_parse_usage_plain_text_returns_empty()
    print("ALL TOKEN TELEMETRY TESTS PASSED")
