"""Shared test support for the KLC-133 (measured token/cost) test suite.

Not collected by pytest itself — helpers only. Every ``test_klc133_*`` module
imports the autouse fixture ``klc133_hermetic`` from here so no test in this
ticket's suite can reach the real Claude CLI, the network, or a live
``.klc`` project root (KLC-136 hermeticity guard).

One test module belongs to one step (impl-plan.md, "Rules that hold across
every step"); this module is the one exception — step-1 creates it and a
later step may ADD helper functions here, never change an existing one.

Every ``test_klc133_*`` module must import ``klc133_hermetic`` BY NAME (not
just the other helpers) — pytest only registers an autouse fixture for a
module that has it bound in its own namespace, so a module that imports
only e.g. ``fixture_json`` would silently run without the hermetic guard.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "klc133"


def fixture_text(name: str) -> str:
    """Raw text of a committed klc133 envelope fixture (or the README)."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    """Parsed JSON of a committed klc133 envelope fixture."""
    return json.loads(fixture_text(name))


@pytest.fixture(autouse=True)
def klc133_hermetic(tmp_path, monkeypatch):
    """AC-13: no klc133 test can reach the real CLI or a live card root."""
    monkeypatch.setenv("CLAUDE_CLI", str(tmp_path / "no-such-claude"))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    project = tmp_path / "project"
    (project / ".klc" / "tickets").mkdir(parents=True)
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    return project


# --- step-4 additions (AC-3/AC-4/AC-7): a real ticket + a fake dispatcher -----

def seed_ticket(project: Path, ticket: str, *, track: str = "M",
                phase: str = "build:work", clarify_required: bool = False,
                **extra) -> Path:
    """A minimal ticket dir under *project* (the hermetic fixture's
    PROJECT_ROOT) — enough for `phase_resolver.resolve_phase` and
    `run_agent`'s own telemetry/park-guard calls. Pass `clarify_required=True`
    for the C-005 interactive-park scenario (`phase="intake"`)."""
    tdir = project / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if clarify_required:
        meta["clarify_required"] = True
    meta.update(extra)
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return tdir


class FakeAnthropic:
    """Stands in for runner._dispatch_anthropic: same arguments, same return
    shape (the real dispatcher contract, C-004) — installed as
    ``runner._DISPATCH["anthropic"]``. Records each call's `resolved.phase`
    so a test can assert which phase(s) the dispatcher actually saw."""
    def __init__(self, reply):          # reply(resolved, prompt) -> (rc, stdout, stderr)
        self.reply, self.calls = reply, []

    def __call__(self, resolved, prompt, timeout, extra_env):
        self.calls.append(resolved.phase)
        return self.reply(resolved, prompt)


# --- step-6 addition (KLC-127 AC-30): the shared redaction gate -------------
# Moved verbatim from test_klc133_fixtures.py so the KLC-127 replay fixtures
# (tests/fixtures/klc127-replay/) can import the same patterns instead of
# re-implementing them. The gate itself is unchanged: a real leak is fixed by
# rewording the fixture text (D-115), never by narrowing a pattern here.

_ALLOWED_UUID_PLACEHOLDERS = (
    "00000000-0000-0000-0000-000000000000",  # klc133 step-1 script: session_id
    "00000000-0000-0000-0000-000000000001",  # klc133 step-1 script: uuid
)
_ALLOWED_SIGNATURE_LINE = '"signature": "REDACTED-SIG"'

FORBIDDEN_PATTERNS = (
    ("a /tmp/ path", re.compile(r"/tmp/")),
    ("a /home/ path", re.compile(r"/home/")),
    ("a real msg_<id>", re.compile(r"\bmsg_[0-9A-Za-z]")),
    ("a real toolu_0<id>", re.compile(r"\btoolu_0")),
    ("a UUID", re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
    ("the word 'signature' outside the redacted placeholder line",
     re.compile(r"signature")),
    ("an '@' (e-mail-shaped text)", re.compile(r"@")),
)


# --- KLC-165: private terms loaded at call time, never hard-coded here -----
# The gate must catch an organisation name and a surname without ever
# committing them to tracked code (the gh mirror must not publish them).
# They are loaded from KLC_REDACT_TERMS (comma-separated) and/or an
# untracked terms file, merged, and reported under one generic label that
# never echoes the term that matched.

REDACT_TERMS_ENV = "KLC_REDACT_TERMS"
REDACTION_TERMS_FILE = FW_ROOT / ".klc" / "config" / "redaction-terms.txt"
PRIVATE_TERM_LABEL = "a private redaction term"


def private_redaction_terms() -> tuple[str, ...]:
    """Private terms configured for this run, merged and de-duplicated
    case-insensitively from `KLC_REDACT_TERMS` (comma-separated, empty parts
    dropped) and `REDACTION_TERMS_FILE` (one term per line; blank lines and
    `#`-comments ignored). Empty — by design (AC-2's
    fail-open-when-unconfigured) — when neither source is configured, so
    the generic gate below still runs unmodified."""
    raw = os.environ.get(REDACT_TERMS_ENV, "").split(",")
    if REDACTION_TERMS_FILE.is_file():
        for line in REDACTION_TERMS_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                raw.append(stripped)
    terms: list[str] = []
    seen: set[str] = set()
    for term in (candidate.strip() for candidate in raw):
        if term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return tuple(terms)


def private_term_hit(text: str, terms: tuple[str, ...]) -> bool:
    """Whether *text* contains any of *terms*, matched case-insensitively
    and literally (`re.escape`) — the same style the old literal patterns
    used before this ticket moved them out of tracked code."""
    return any(re.search(re.escape(term), text, re.IGNORECASE) for term in terms)


def _tracked_relpaths(root: Path) -> list[str]:
    """Relative paths of every tracked file under *root*, in `git ls-files`
    order when *root* is a git checkout; otherwise every regular file found
    by walking the tree, skipping `.klc/` (the live ticket-state directory,
    never tracked on main) — a `git archive` scratch copy holds only
    tracked files anyway, so this fallback is exact there too."""
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True,
        )
        return [line for line in result.stdout.splitlines() if line]
    rels: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".klc":
            continue
        rels.append(str(relative))
    return rels


def tracked_files_with_private_terms(root: Path, terms: tuple[str, ...]) -> list[str]:
    """Relative paths of tracked files under *root* whose text contains any
    of *terms* — the autotest equivalent of the operator's
    `git grep -i -F -f .klc/config/redaction-terms.txt`. Vacuous (empty)
    when *terms* is empty, by design (AC-2's fail-open-when-unconfigured)."""
    if not terms:
        return []
    hits: list[str] = []
    for rel in _tracked_relpaths(root):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if private_term_hit(text, terms):
            hits.append(rel)
    return hits


def _strip_allowed(text: str) -> str:
    """Remove the fixed, documented placeholders the klc133 captures use
    before the forbidden patterns are checked, so they don't self-trigger."""
    scrubbed = text
    for placeholder in _ALLOWED_UUID_PLACEHOLDERS:
        scrubbed = scrubbed.replace(placeholder, "")
    return scrubbed.replace(_ALLOWED_SIGNATURE_LINE, "")


def forbidden_hits(text: str) -> list[str]:
    """Every forbidden-pattern label that matches *text*, after stripping the
    klc133 fixtures' own allowed placeholders. Shared by
    test_klc133_fixtures.py and test_klc127_fixture_redaction.py (KLC-127
    step-6) — callers apply their own per-file exemptions (e.g. a README that
    names a pattern descriptively) on top of this, never inside it."""
    scrubbed = _strip_allowed(text)
    hits = [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(scrubbed)]
    if private_term_hit(scrubbed, private_redaction_terms()):
        hits.append(PRIVATE_TERM_LABEL)
    return hits


def all_attempts(ticket: str, phase: str | None = None) -> list[dict]:
    """Every attempt currently buffered for *ticket* — none of these tests
    open a `state_tx` transaction, so a headless dispatch's attempt lands in
    the journal, not directly in meta.json. Optionally filtered to one
    phase."""
    import token_journal
    records = token_journal.read(ticket)
    if phase is not None:
        records = [r for r in records if r.get("phase") == phase]
    return records
