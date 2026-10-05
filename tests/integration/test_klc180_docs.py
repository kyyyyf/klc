"""KLC-180 step-4 — AC-9 and the stale-name guard: docs/process.md records the
single hook, the plugin surface, the agents symlink and the `model:` answer."""
from __future__ import annotations

import re
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
DOC = FW / "docs" / "process.md"
STALE = ("/klc:run", "skills/run/", "gate.py", "remind.py", "heartbeat.py",
         "KLC_GATE", "KLC_TICKET")


def _section(title_part: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    heads = [(m.start(), m.group(0)) for m in re.finditer(r"^#{2,3} .*$", text, re.M)]
    for i, (pos, h) in enumerate(heads):
        if title_part.lower() in h.lower():
            end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
            return text[pos:end]
    raise AssertionError(f"no heading containing {title_part!r}")


def test_process_md_documents_hook_symlink_and_model_probe():
    hook = _section("single hook")
    for needle in ("never blocks", "systemMessage", "heartbeat"):
        assert needle in hook
    assert "detached" in hook
    surface = _section("plugin surface")
    for needle in ("six commands", "discuss-feature", "14 agents", "0.2.0"):
        assert needle in surface
    link = _section("agents symlink")
    assert ".claude/agents" in link and "klc-plugin/agents" in link
    model = _section("frontmatter `model:`")
    assert "evidence=assumed" in model and "unconfirmed" in model
    assert "model=" in model


def test_retired_names_are_gone_from_prompts_plugin_and_process_doc():
    files = [p for root in ("core/agents", "klc-plugin") for p in (FW / root).rglob("*")
             if p.is_file() and p.suffix in {".md", ".py", ".json", ".yml"}]
    assert files
    for p in files:
        t = p.read_text(encoding="utf-8")
        for bad in STALE:
            assert bad not in t, f"{p.relative_to(FW)} mentions {bad}"
    doc = DOC.read_text(encoding="utf-8")
    hits = [(bad, line) for line in doc.splitlines() for bad in STALE if bad in line]
    # one sentence naming the retired pieces is allowed, and it must say so
    assert len({line for _, line in hits}) <= 1, hits
    for _, line in hits:
        assert "retired" in line.lower()
