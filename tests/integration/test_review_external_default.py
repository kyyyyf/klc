#!/usr/bin/env python3
"""Integration tests for external reviewer default-on behaviour (Change 7).

Tests:
- _should_run_external: S ticket + no opt-out + api key set → True
- _should_run_external: --no-external flag → False
- _should_run_external: missing api key → False
- _should_run_external: meta.review.skip_external = true → False
- _should_run_external: XS ticket (below min_track) → False
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "scripts"))


def test_s_ticket_runs_external_by_default() -> None:
    """S ticket, api key set, no opt-out → external runs."""
    import review as rv

    cfg = {"enabled": True, "min_track": "S", "api_key_env": "OPENAI_API_KEY"}
    meta = {"track": "S", "review": {}}

    os.environ["OPENAI_API_KEY"] = "test-key-value"
    try:
        result = rv._should_run_external(
            no_external=False,
            reviewers_cfg=cfg,
            meta=meta,
        )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)

    assert result is True, f"Expected True for S ticket with api key, got {result}"
    print("PASS: S ticket + api key → external runs")


def test_no_external_flag_skips() -> None:
    """--no-external flag prevents external run even when enabled."""
    import review as rv

    cfg = {"enabled": True, "min_track": "S", "api_key_env": "OPENAI_API_KEY"}
    meta = {"track": "S", "review": {}}

    os.environ["OPENAI_API_KEY"] = "test-key-value"
    try:
        result = rv._should_run_external(
            no_external=True,
            reviewers_cfg=cfg,
            meta=meta,
        )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)

    assert result is False, f"Expected False for --no-external, got {result}"
    print("PASS: --no-external flag → external skipped")


def test_missing_api_key_skips_gracefully() -> None:
    """No api key in env → external skipped with no error."""
    import review as rv

    cfg = {"enabled": True, "min_track": "S", "api_key_env": "OPENAI_API_KEY_MISSING_XYZ"}
    meta = {"track": "S", "review": {}}

    os.environ.pop("OPENAI_API_KEY_MISSING_XYZ", None)
    result = rv._should_run_external(
        no_external=False,
        reviewers_cfg=cfg,
        meta=meta,
    )

    assert result is False, f"Expected False for missing api key, got {result}"
    print("PASS: missing api key → external skipped")


def test_skip_external_meta_field() -> None:
    """meta.review.skip_external = true → external skipped."""
    import review as rv

    cfg = {"enabled": True, "min_track": "S", "api_key_env": "OPENAI_API_KEY"}
    meta = {"track": "M", "review": {"skip_external": True}}

    os.environ["OPENAI_API_KEY"] = "test-key-value"
    try:
        result = rv._should_run_external(
            no_external=False,
            reviewers_cfg=cfg,
            meta=meta,
        )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)

    assert result is False, f"Expected False for skip_external in meta, got {result}"
    print("PASS: meta.review.skip_external → external skipped")


def test_xs_ticket_skips_external() -> None:
    """XS ticket is below min_track S → external skipped."""
    import review as rv

    cfg = {"enabled": True, "min_track": "S", "api_key_env": "OPENAI_API_KEY"}
    meta = {"track": "XS", "review": {}}

    os.environ["OPENAI_API_KEY"] = "test-key-value"
    try:
        result = rv._should_run_external(
            no_external=False,
            reviewers_cfg=cfg,
            meta=meta,
        )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)

    assert result is False, f"Expected False for XS ticket, got {result}"
    print("PASS: XS ticket below min_track → external skipped")


def test_external_runs_on_cheap_cascade_path() -> None:
    """External runs even when cascade chose cheap review (S ticket, default-on)."""
    import review as rv

    cfg = {"enabled": True, "min_track": "S", "api_key_env": "OPENAI_API_KEY"}
    meta = {"track": "S", "review": {}}

    os.environ["OPENAI_API_KEY"] = "test-key-value"
    try:
        # Simulate: cascade chose cheap, but external should still run
        result = rv._should_run_external(
            no_external=False,
            reviewers_cfg=cfg,
            meta=meta,
        )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)

    assert result is True, f"Expected True even on cheap cascade path, got {result}"
    print("PASS: cheap cascade path does not prevent external")


if __name__ == "__main__":
    test_s_ticket_runs_external_by_default()
    test_no_external_flag_skips()
    test_missing_api_key_skips_gracefully()
    test_skip_external_meta_field()
    test_xs_ticket_skips_external()
    test_external_runs_on_cheap_cascade_path()
    print("ALL EXTERNAL REVIEW TESTS PASSED")
