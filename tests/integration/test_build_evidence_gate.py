"""KLC-038 step-1: build ack requires an Evidence block in build-log.

Gate: build-log.md must have an `## Evidence` section with at least one
non-empty fenced block.  A plain prose log (no Evidence section) must block.
An Evidence heading with no fenced block must also block.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.phase_completion import can_complete  # noqa: E402

# ---------------------------------------------------------------------------
# Shared build-log fixtures
# ---------------------------------------------------------------------------

_BUILD_LOG_NO_EVIDENCE = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Step 1 — 2026-06-23
**Attempt**: write the feature
**Outcome**: green
**Notes**: all tests pass
"""

_BUILD_LOG_WITH_EVIDENCE = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Step 1 — 2026-06-23
**Attempt**: write the feature
**Outcome**: green
**Notes**: all tests pass

## Evidence

```
$ python3 -m pytest tests/ -q
15 passed in 0.42s
```
"""

_BUILD_LOG_EVIDENCE_EMPTY_FENCE = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Evidence

```
```
"""

_BUILD_LOG_MULTIPLE_EVIDENCE_BLOCKS = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Evidence

```
$ pytest tests/ -q
15 passed
```

```
$ grep -n "Evidence" core/agents/impl.md
42:Evidence block is required.
```
"""


def _make_build_ticket(tmp_path: Path, ticket: str, build_log: str | None) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "build:ack-needed",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"],
        "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if build_log is not None:
        (ticket_dir / "build-log.md").write_text(
            build_log.format(ticket=ticket), encoding="utf-8"
        )
    return ticket_dir


# ---------------------------------------------------------------------------
# BE01: no Evidence section → blocked
# ---------------------------------------------------------------------------

def test_build_log_without_evidence_blocks_ack(tmp_path, monkeypatch):
    """AC-1: build-log.md with no Evidence section must block build ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE01", _BUILD_LOG_NO_EVIDENCE)
    ok, msg = can_complete("KLC-BE01", "build")
    assert not ok, "expected False: build-log without Evidence should block"
    assert "Evidence" in msg, f"expected 'Evidence' in error msg, got: {msg!r}"


# ---------------------------------------------------------------------------
# BE02: Evidence section with non-empty fenced block → passes
# ---------------------------------------------------------------------------

def test_build_log_with_evidence_passes_ack(tmp_path, monkeypatch):
    """AC-2/AC-3: build-log.md with ## Evidence + non-empty fenced block passes build ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE02", _BUILD_LOG_WITH_EVIDENCE)
    ok, msg = can_complete("KLC-BE02", "build")
    assert ok, f"expected True for build-log with Evidence, got: {msg!r}"


# ---------------------------------------------------------------------------
# BE03: Evidence heading present but no fenced block → blocked
# ---------------------------------------------------------------------------

def test_build_log_evidence_empty_fence_blocks_ack(tmp_path, monkeypatch):
    """Edge case: ## Evidence present but fenced block is empty → must block."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE03", _BUILD_LOG_EVIDENCE_EMPTY_FENCE)
    ok, msg = can_complete("KLC-BE03", "build")
    assert not ok, "expected False: Evidence section with empty fence must block"
    assert "Evidence" in msg, f"expected 'Evidence' in error msg, got: {msg!r}"


# ---------------------------------------------------------------------------
# BE04: build-log.md missing → generic "Missing" error (not Evidence-specific)
# ---------------------------------------------------------------------------

def test_missing_build_log_blocks_ack(tmp_path, monkeypatch):
    """Edge case: build-log.md absent → blocked before Evidence check runs."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE04", build_log=None)
    ok, msg = can_complete("KLC-BE04", "build")
    assert not ok, "expected False: missing build-log.md must block"
    assert "build-log" in msg or "Missing" in msg, f"unexpected msg: {msg!r}"


# ---------------------------------------------------------------------------
# BE05: multiple Evidence blocks → passes (one or more is fine)
# ---------------------------------------------------------------------------

def test_build_log_multiple_evidence_blocks_passes(tmp_path, monkeypatch):
    """Edge case: multiple fenced blocks under ## Evidence → passes."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE05", _BUILD_LOG_MULTIPLE_EVIDENCE_BLOCKS)
    ok, msg = can_complete("KLC-BE05", "build")
    assert ok, f"expected True for build-log with multiple Evidence fences, got: {msg!r}"


# ---------------------------------------------------------------------------
# BE06: language-tagged fenced block (```bash, ```text) counts as Evidence
# ---------------------------------------------------------------------------

_BUILD_LOG_EVIDENCE_LANG_FENCE = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Evidence

```bash
$ python3 -m pytest tests/ -q
15 passed in 0.42s
```
"""


def test_build_log_language_tagged_fence_passes(tmp_path, monkeypatch):
    """Edge case: language-tagged fence (```bash) under Evidence passes."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE06", _BUILD_LOG_EVIDENCE_LANG_FENCE)
    ok, msg = can_complete("KLC-BE06", "build")
    assert ok, f"expected True for language-tagged Evidence fence, got: {msg!r}"


# ---------------------------------------------------------------------------
# BE07: Evidence fenced block followed by another ## section → passes
# ---------------------------------------------------------------------------

_BUILD_LOG_EVIDENCE_THEN_SECTION = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Step 1 — 2026-06-23
**Attempt**: write the feature
**Outcome**: green

## Evidence

```
$ python3 -m pytest tests/ -q
5 passed in 0.04s
```

## Step 2 — 2026-06-23
**Attempt**: follow-up fix
**Outcome**: green
"""

_BUILD_LOG_FENCE_ONLY_AFTER_STEP = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Evidence

## Step 1 — 2026-06-23

```
$ python3 -m pytest tests/ -q
5 passed in 0.04s
```
"""


def test_build_log_evidence_before_later_section_passes(tmp_path, monkeypatch):
    """Edge case: Evidence block + later ## section — fence in Evidence still passes."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE07", _BUILD_LOG_EVIDENCE_THEN_SECTION)
    ok, msg = can_complete("KLC-BE07", "build")
    assert ok, f"expected True when Evidence fence precedes a later ## section, got: {msg!r}"


def test_build_log_fence_after_boundary_blocks(tmp_path, monkeypatch):
    """Edge case: non-empty fence appears only after next ## heading (outside Evidence) → blocks."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_build_ticket(tmp_path, "KLC-BE08", _BUILD_LOG_FENCE_ONLY_AFTER_STEP)
    ok, msg = can_complete("KLC-BE08", "build")
    assert not ok, "expected False: fence is outside ## Evidence section (after next ##)"
    assert "Evidence" in msg, f"expected 'Evidence' in msg, got: {msg!r}"
