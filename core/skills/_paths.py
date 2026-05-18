"""Shared path helpers for klc skills.

Per-project state lives in $PROJECT_ROOT/.klc/ (see MIGRATION.md).
Skills never write inside the klc repo; they read templates / rules
from there and write generated data into the per-project directory.

Layout resolution:

  framework_root() — the klc repo itself (parent of `scripts/`,
    `core/`, `config/`, ...). Since the repo *is* the framework after
    the "flat layout" refactor, this is just `Path(__file__)` walked
    up three levels (core/skills/<file>.py → repo root).

  project_root() — wherever tickets / indices / artefacts live:
    1. $PROJECT_ROOT env var (explicit). Required in the multi-project
       layout where one klc clone drives several projects.
    2. Fallback: the directory one level above `framework_root()`.
       Works when the klc repo is cloned as a subdirectory of the
       project (layout A in README.md).
"""

from __future__ import annotations

import os
from pathlib import Path


def framework_root() -> Path:
    """Path to the klc repo (was `framework/` in the old nested layout).

    core/skills/<file>.py → core/skills → core → repo root.
    """
    return Path(__file__).resolve().parent.parent.parent


def project_root() -> Path:
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return framework_root().parent


def klc_dir() -> Path:
    """Per-project state directory."""
    return project_root() / ".klc"


def klc_index_dir() -> Path:
    """Deterministic indices (inventory, modules, depgraph, ...)."""
    return klc_dir() / "index"


def klc_reports_dir() -> Path:
    """Review artefacts and partials."""
    return klc_dir() / "reports"


def klc_logs_dir() -> Path:
    """Log files from skills and scripts."""
    return klc_dir() / "logs"


def klc_tickets_dir() -> Path:
    """Per-ticket artefacts (specs, ADRs, impl-plans, retrospectives)."""
    return klc_dir() / "tickets"


def klc_tickets_archive_dir() -> Path:
    """Where tickets move to when the work is integrated. Scratchpad
    and cache survive the move so the trail is not lost."""
    return klc_tickets_dir() / "archive"


def klc_ticket_dir(ticket_id: str) -> Path:
    """Live ticket directory: spec, design/, impl-plan, test-plan,
    scratch/, serena-cache/, retrospective."""
    return klc_tickets_dir() / ticket_id


def klc_ticket_scratch_dir(ticket_id: str) -> Path:
    """In-session externalized memory for an agent: intermediate findings
    that should not pollute the final artefacts but must survive context
    compression and re-opening in a later session."""
    return klc_ticket_dir(ticket_id) / "scratch"


def klc_ticket_serena_cache_dir(ticket_id: str) -> Path:
    """Per-ticket Serena answer cache. One file per (operation, symbol,
    file, line) tuple; invalidated automatically when the underlying
    source file changes (git blob SHA mismatch)."""
    return klc_ticket_dir(ticket_id) / "serena-cache"


def klc_ticket_meta_file(ticket_id: str) -> Path:
    """Tiny per-ticket metadata: track (XS/S/M/L), current phase, owner.
    Used by serena-call.py to decide whether a given phase may call
    Serena on this track."""
    return klc_ticket_dir(ticket_id) / "meta.json"


def klc_ticket_raw_file(ticket_id: str) -> Path:
    return klc_ticket_dir(ticket_id) / "raw.md"


def klc_ticket_index_file(ticket_id: str) -> Path:
    """.index.json of inline items for a ticket. Rebuilt by items.py
    after every artefact write."""
    return klc_ticket_dir(ticket_id) / ".index.json"


def klc_global_tickets_index() -> Path:
    return klc_knowledge_dir() / "tickets-index.jsonl"


def klc_config_dir() -> Path:
    return klc_dir() / "config"


def klc_knowledge_dir() -> Path:
    """Cumulative, cross-ticket knowledge (allowlists, few-shot examples,
    global index, process metrics, promoted process rules)."""
    return klc_dir() / "knowledge"


def klc_serena_deny_file() -> Path:
    """Project-level Serena query denylist (accumulated over time). Has
    the same fall-back semantics as the reviewer allowlist: if the
    project file is missing, callers use the framework-shipped seed."""
    return klc_knowledge_dir() / "serena-deny.yml"


def klc_verification_log() -> Path:
    """Append-only JSONL log of FACT re-verification runs. One line per
    item inspected. Used by retrospectives to surface stale-rate
    trends across the knowledge base."""
    return klc_knowledge_dir() / "verification-log.jsonl"
