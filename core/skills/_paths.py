"""Shared path helpers for klc skills.

Per-project state lives in $PROJECT_ROOT/.klc/.
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
    scratch/, retrospective."""
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
    A blank or whitespace-only override is treated as unset. Mirrors
    `core.shared.paths.klc_card_root` (the dotted-path module `artefacts.py`
    uses) — kept in sync here so bare-`_paths` callers in `core/skills`
    (e.g. `token_journal.py`) need no second import mechanism."""
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
    """In-session externalized memory for an agent: intermediate findings
    that should not pollute the final artefacts but must survive context
    compression and re-opening in a later session."""
    return klc_ticket_dir(ticket_id) / "scratch"


def klc_ticket_meta_file(ticket_id: str) -> Path:
    """Tiny per-ticket metadata: track (XS/S/M/L), current phase, owner."""
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


def klc_verification_log() -> Path:
    """Append-only JSONL log of FACT re-verification runs. One line per
    item inspected. Used by retrospectives to surface stale-rate
    trends across the knowledge base."""
    return klc_knowledge_dir() / "verification-log.jsonl"
