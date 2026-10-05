"""Path resolution utilities for klc framework.

Per-project state lives in $PROJECT_ROOT/.klc/.
Skills never write inside the klc repo; they read templates/rules
from there and write generated data into the per-project directory.

Layout resolution:

  framework_root() — the klc repo itself (parent of scripts/, core/, config/)
    Path(__file__) walked up levels: core/shared/<file>.py → repo root

  project_root() — wherever tickets/indices/artefacts live:
    1. $PROJECT_ROOT env var (explicit) - required in multi-project layout
    2. Fallback: directory one level above framework_root()
       (works when klc repo is subdirectory of project)

Extracted from core/skills/_paths.py (KLC-007).
"""
from __future__ import annotations

import os
from pathlib import Path


def framework_root() -> Path:
    """Path to the klc repo root.

    core/shared/<file>.py → core/shared → core → repo root.
    """
    return Path(__file__).resolve().parent.parent.parent


def project_root() -> Path:
    """Project root (where .klc/ lives).

    Returns $PROJECT_ROOT if set, else parent of framework_root().
    """
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return framework_root().parent


def klc_dir() -> Path:
    """Per-project state directory (.klc/)."""
    return project_root() / ".klc"


def klc_index_dir() -> Path:
    """Deterministic indices (inventory, modules, depgraph)."""
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
    """Where tickets move when integrated. Scratchpad survives."""
    return klc_tickets_dir() / "archive"


def klc_ticket_dir(ticket_id: str) -> Path:
    """Live ticket directory: spec, design/, impl-plan, test-plan, scratch/."""
    return klc_tickets_dir() / ticket_id


def design_doc_path(ticket_id: str) -> Path:
    """design.md for a new ticket, design/options.md for an archived one."""
    tdir = klc_ticket_dir(ticket_id)
    new = tdir / "design.md"
    return new if new.exists() else tdir / "design" / "options.md"


CARD_ROOT_ENV = "KLC_CARD_ROOT"


def klc_card_root() -> Path:
    """Root for DERIVED prompt cards, outside the ticket artefact tree
    (KLC-118). `.klc/scratch/` by default; overridable with `KLC_CARD_ROOT`.
    A blank or whitespace-only override is treated as unset."""
    raw = (os.environ.get(CARD_ROOT_ENV) or "").strip()
    return Path(raw).expanduser() if raw else klc_dir() / "scratch"


def klc_card_path(ticket_id: str, phase_id: str, step: int | None = None) -> Path:
    """Canonical location of a rendered prompt card (KLC-118), without any
    existence check or ticket-directory fallback — see
    `core/skills/artefacts.py:card_path` for the reader-facing resolver."""
    name = f"_prompt_step_{step}.md" if step is not None else "_prompt.md"
    return klc_card_root() / ticket_id / phase_id / name

def transient_dir(ticket_id: str) -> Path:
    """Derived per-ticket files (retrieval trace, build step files) under the
    card root, never under the tracked ticket directory (KLC-176)."""
    return klc_card_root() / ticket_id


def transient_read_path(ticket_id: str, rel: str) -> Path:
    """Where to READ a transient file: scratch first, then the legacy path in
    the ticket directory (old tickets), else the scratch path (KLC-176)."""
    new = transient_dir(ticket_id) / rel
    if new.exists():
        return new
    old = klc_ticket_dir(ticket_id) / rel
    return old if old.exists() else new


def klc_ticket_scratch_dir(ticket_id: str) -> Path:
    """In-session externalized memory for agent.

    Intermediate findings that survive context compression.
    """
    return klc_ticket_dir(ticket_id) / "scratch"


def klc_ticket_meta_file(ticket_id: str) -> Path:
    """Per-ticket metadata: track (XS/S/M/L), current phase, owner."""
    return klc_ticket_dir(ticket_id) / "meta.json"


def klc_ticket_raw_file(ticket_id: str) -> Path:
    """Raw ticket input (raw.md)."""
    return klc_ticket_dir(ticket_id) / "raw.md"


def klc_ticket_index_file(ticket_id: str) -> Path:
    """.index.json of inline items for ticket.

    Rebuilt by items.py after every artefact write.
    """
    return klc_ticket_dir(ticket_id) / ".index.json"


def klc_global_tickets_index() -> Path:
    """Global cross-ticket index (tickets-index.jsonl)."""
    return klc_knowledge_dir() / "tickets-index.jsonl"


def klc_config_dir() -> Path:
    """Per-project config directory (.klc/config/)."""
    return klc_dir() / "config"


def klc_knowledge_dir() -> Path:
    """Cross-ticket knowledge.

    Allowlists, few-shot examples, global index, process metrics.
    """
    return klc_dir() / "knowledge"


def klc_verification_log() -> Path:
    """Append-only JSONL log of FACT re-verification runs.

    One line per item inspected. Used by retrospectives.
    """
    return klc_knowledge_dir() / "verification-log.jsonl"
