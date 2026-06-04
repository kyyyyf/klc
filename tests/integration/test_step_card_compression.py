#!/usr/bin/env python3
"""Integration tests for KLC-017: compressed step cards + telemetry source.

Tests:
- Compressed card (default) does NOT embed impl.md; contains path reference
- Inline card DOES embed impl.md
- KLC_CARD_INLINE=1 env var triggers inline mode
- Explicit inline=True wins over KLC_CARD_INLINE=0
- Compressed card is smaller than inline by at least impl.md size
- Telemetry source="provider" set from real usage block
- Telemetry source="estimated" set when plain text output
- cache_hit is 0 for estimated source
- metrics rollup includes source_counts
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

FW_ROOT = Path(__file__).resolve().parent.parent.parent
# core/skills must come before core/shared — both have artefacts.py,
# core/skills version has write_step_card.
sys.path.insert(0, str(FW_ROOT / "core" / "shared"))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

# PROJECT_ROOT must be set before importing artefacts (it resolves paths at
# import time via core.shared.paths). Use a stable temp location.
import tempfile as _tmpmod
_GLOBAL_SCRATCH = Path(_tmpmod.mkdtemp(prefix="klc-test-"))
os.environ.setdefault("PROJECT_ROOT", str(_GLOBAL_SCRATCH))

IMPL_MD = FW_ROOT / "core" / "agents" / "impl.md"
IMPL_MD_SIZE = IMPL_MD.stat().st_size if IMPL_MD.exists() else 0

import artefacts  # noqa: E402 — must import after PROJECT_ROOT is set


def _make_ticket_env(scratch: Path, ticket: str) -> dict:
    tdir = scratch / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "raw.md").write_text(
        f"---\nticket: {ticket}\n---\nFake.\n", encoding="utf-8"
    )
    (tdir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: tech\nauthority: agent\n---\n"
        "## Goals\nFake.\n## Acceptance Criteria\n- [ ] AC-1\n"
        "## Estimate\ntotal: 1\n",
        encoding="utf-8"
    )
    (tdir / "impl-plan.md").write_text(
        "## step-1 — fake step\nDo something.\n", encoding="utf-8"
    )
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [],
        "track": "S", "estimate": None, "layer": "code",
        "affected_modules": [], "created": "2026-06-04T00:00:00Z",
        "owner": "test", "jira_url": None, "links": [],
        "rework_count": {}, "metrics": {},
    }
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(scratch)
    env.pop("KLC_CARD_INLINE", None)
    return env, meta, tdir


def test_compressed_card_does_not_embed_impl_md() -> None:
    """Default mode: card references impl.md path, does not embed content."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta, tdir = _make_ticket_env(scratch, "T-COMP-001")
        with patch.dict(os.environ, env, clear=True):
            card = artefacts.write_step_card("T-COMP-001", 1, meta, inline=False)

        content = card.read_text(encoding="utf-8")
        assert IMPL_MD.exists(), "impl.md must exist for this test"
        # Should NOT contain the impl.md body
        impl_snippet = IMPL_MD.read_text(encoding="utf-8").splitlines()[5]
        assert impl_snippet not in content, (
            "Compressed card must not embed impl.md content"
        )
        # SHOULD contain a path reference
        assert str(IMPL_MD) in content or "impl.md" in content, (
            "Compressed card must reference impl.md path"
        )
        assert "Before acting, read the role prompt" in content
        print("PASS: compressed card does not embed impl.md")


def test_inline_card_embeds_impl_md() -> None:
    """inline=True: card embeds full impl.md content."""


    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta, tdir = _make_ticket_env(scratch, "T-INLN-001")
        with patch.dict(os.environ, env, clear=True):
            card = artefacts.write_step_card("T-INLN-001", 1, meta, inline=True)

        content = card.read_text(encoding="utf-8")
        impl_text = IMPL_MD.read_text(encoding="utf-8") if IMPL_MD.exists() else ""
        impl_snippet = impl_text.splitlines()[5] if len(impl_text.splitlines()) > 5 else ""
        assert impl_snippet and impl_snippet in content, (
            "Inline card must embed impl.md content"
        )
        print("PASS: inline card embeds impl.md")


def test_env_var_triggers_inline_mode() -> None:
    """KLC_CARD_INLINE=1 env var → inline mode."""


    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta, _ = _make_ticket_env(scratch, "T-ENV-001")
        env["KLC_CARD_INLINE"] = "1"
        with patch.dict(os.environ, env, clear=True):
            card = artefacts.write_step_card("T-ENV-001", 1, meta)

        content = card.read_text(encoding="utf-8")
        impl_text = IMPL_MD.read_text(encoding="utf-8") if IMPL_MD.exists() else ""
        impl_snippet = impl_text.splitlines()[5] if len(impl_text.splitlines()) > 5 else ""
        assert impl_snippet and impl_snippet in content, (
            "KLC_CARD_INLINE=1 must trigger inline mode"
        )
        print("PASS: KLC_CARD_INLINE=1 triggers inline mode")


def test_explicit_inline_arg_wins_over_env() -> None:
    """inline=True arg wins even when KLC_CARD_INLINE=0."""


    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta, _ = _make_ticket_env(scratch, "T-PRIO-001")
        env["KLC_CARD_INLINE"] = "0"
        with patch.dict(os.environ, env, clear=True):
            card = artefacts.write_step_card("T-PRIO-001", 1, meta, inline=True)

        content = card.read_text(encoding="utf-8")
        impl_text = IMPL_MD.read_text(encoding="utf-8") if IMPL_MD.exists() else ""
        impl_snippet = impl_text.splitlines()[5] if len(impl_text.splitlines()) > 5 else ""
        assert impl_snippet and impl_snippet in content, (
            "Explicit inline=True must win over KLC_CARD_INLINE=0"
        )
        print("PASS: explicit inline=True wins over KLC_CARD_INLINE=0")


def test_compressed_card_smaller_than_inline() -> None:
    """Compressed card must be at least impl.md size smaller than inline."""


    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta, _ = _make_ticket_env(scratch, "T-SIZE-001")
        with patch.dict(os.environ, env, clear=True):
            compressed = artefacts.write_step_card("T-SIZE-001", 1, meta, inline=False)
            inline = artefacts.write_step_card("T-SIZE-001", 2, meta, inline=True)

        comp_size = compressed.stat().st_size
        inln_size = inline.stat().st_size
        diff = inln_size - comp_size
        print(f"  compressed={comp_size}B  inline={inln_size}B  diff={diff}B  impl.md={IMPL_MD_SIZE}B")
        assert diff >= 5_000, (
            f"Compressed card should be ≥5000B smaller than inline (got {diff}B)"
        )
        print("PASS: compressed card is significantly smaller than inline")


def test_telemetry_source_provider() -> None:
    """source='provider' when usage block present in output."""
    import runner

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        tdir = scratch / ".klc" / "tickets" / "T-SRC-001"
        tdir.mkdir(parents=True, exist_ok=True)
        meta = {"ticket": "T-SRC-001", "kind": "tech", "kind_source": "user",
                "phase": "build:work", "phase_history": [], "track": "S",
                "estimate": None, "layer": "code", "affected_modules": [],
                "created": "2026-06-04T00:00:00Z", "owner": "test",
                "jira_url": None, "links": [], "rework_count": {}, "metrics": {}}
        (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

        fake_output = json.dumps({
            "result": "done",
            "usage": {"input_tokens": 500, "output_tokens": 100,
                      "cache_read_input_tokens": 50}
        })
        prompt_file = scratch / "prompt.md"
        prompt_file.write_text("test", encoding="utf-8")
        out_file = scratch / "out.md"

        from unittest.mock import MagicMock
        resolved = MagicMock(provider="anthropic", model="claude-haiku-4-5-20251001",
                             extra_args=[], api_key_env="ANTHROPIC_API_KEY",
                             as_env=lambda: {})
        with patch.object(runner, "_load_budget_limits", return_value=({}, {})), \
             patch.dict(runner._DISPATCH,
                        {"anthropic": lambda *a, **k: (0, fake_output, "")}), \
             patch("models.load_models") as mm:
            mm.return_value.resolve.return_value = resolved
            os.environ["PROJECT_ROOT"] = tmp
            runner.run_agent("build", prompt_file, out_file,
                             track="S", ticket="T-SRC-001")
            os.environ.pop("PROJECT_ROOT", None)

        saved = json.loads((tdir / "meta.json").read_text())
        tok = saved["metrics"]["tokens"]["build"]
        assert tok["source"] == "provider", f"expected provider, got {tok['source']}"
        assert tok["cache_hit"] == 50
        print("PASS: telemetry source='provider' from real usage block")


def test_telemetry_source_estimated() -> None:
    """source='estimated' and cache_hit=0 for plain text output."""
    import runner

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        tdir = scratch / ".klc" / "tickets" / "T-EST-001"
        tdir.mkdir(parents=True, exist_ok=True)
        meta = {"ticket": "T-EST-001", "kind": "tech", "kind_source": "user",
                "phase": "build:work", "phase_history": [], "track": "S",
                "estimate": None, "layer": "code", "affected_modules": [],
                "created": "2026-06-04T00:00:00Z", "owner": "test",
                "jira_url": None, "links": [], "rework_count": {}, "metrics": {}}
        (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

        prompt_file = scratch / "prompt.md"
        prompt_file.write_text("test", encoding="utf-8")
        out_file = scratch / "out.md"

        from unittest.mock import MagicMock
        resolved = MagicMock(provider="anthropic", model="claude-haiku-4-5-20251001",
                             extra_args=[], api_key_env="ANTHROPIC_API_KEY",
                             as_env=lambda: {})
        with patch.object(runner, "_load_budget_limits", return_value=({}, {})), \
             patch.dict(runner._DISPATCH,
                        {"anthropic": lambda *a, **k: (0, "plain text output", "")}), \
             patch("models.load_models") as mm:
            mm.return_value.resolve.return_value = resolved
            os.environ["PROJECT_ROOT"] = tmp
            runner.run_agent("build", prompt_file, out_file,
                             track="S", ticket="T-EST-001")
            os.environ.pop("PROJECT_ROOT", None)

        saved = json.loads((tdir / "meta.json").read_text())
        tok = saved["metrics"]["tokens"]["build"]
        assert tok["source"] == "estimated", f"expected estimated, got {tok['source']}"
        assert tok["cache_hit"] == 0, f"cache_hit must be 0 for estimated, got {tok['cache_hit']}"
        print("PASS: telemetry source='estimated', cache_hit=0 for plain text")


def test_rollup_source_counts() -> None:
    """metrics rollup includes source_counts per phase."""
    import metrics as m_mod
    import argparse

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        tickets_dir = scratch / ".klc" / "tickets"
        knowledge_dir = scratch / ".klc" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        for i, source in enumerate(["provider", "estimated", "provider"]):
            tdir = tickets_dir / f"T-ROLL-00{i+1}"
            tdir.mkdir(parents=True, exist_ok=True)
            meta = {
                "ticket": f"T-ROLL-00{i+1}", "kind": "tech",
                "kind_source": "user", "phase": "learn:ack",
                "phase_history": [
                    {"phase": "intake:ack-needed", "started_at": "2026-06-04T00:00:00Z"},
                    {"phase": "learn:ack", "started_at": "2026-06-04T01:00:00Z",
                     "finished_at": "2026-06-04T02:00:00Z"},
                ],
                "track": "S", "estimate": {"complexity": 1, "uncertainty": 0,
                                           "risk": 0, "manual": 0, "total": 1},
                "layer": "code", "affected_modules": [],
                "created": "2026-06-04T00:00:00Z", "owner": "test",
                "jira_url": None, "links": [], "rework_count": {}, "metrics": {
                    "tokens": {"build": {"in": 100, "out": 20,
                                         "cache_hit": 10 if source == "provider" else 0,
                                         "source": source}}
                }
            }
            (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

        os.environ["PROJECT_ROOT"] = tmp
        from core.shared import paths as _p
        import importlib
        importlib.reload(_p)

        with patch("core.shared.paths.project_root", return_value=scratch):
            with patch("core.shared.paths.klc_tickets_dir",
                       return_value=tickets_dir), \
                 patch("core.shared.paths.klc_knowledge_dir",
                       return_value=knowledge_dir):
                args = argparse.Namespace()
                m_mod.cmd_rollup(args)

        out = knowledge_dir / "process-metrics.json"
        data = json.loads(out.read_text())
        build_tok = data["per_track"]["S"]["tokens_by_phase"]["build"]
        sc = build_tok["source_counts"]
        assert sc["provider"] == 2, f"expected 2 provider, got {sc}"
        assert sc["estimated"] == 1, f"expected 1 estimated, got {sc}"
        os.environ.pop("PROJECT_ROOT", None)
        print("PASS: rollup source_counts correct")


if __name__ == "__main__":
    test_compressed_card_does_not_embed_impl_md()
    test_inline_card_embeds_impl_md()
    test_env_var_triggers_inline_mode()
    test_explicit_inline_arg_wins_over_env()
    test_compressed_card_smaller_than_inline()
    test_telemetry_source_provider()
    test_telemetry_source_estimated()
    print("ALL STEP CARD COMPRESSION TESTS PASSED")
