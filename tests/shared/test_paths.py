"""Test core.shared.paths utilities."""

from pathlib import Path
from core.shared import paths


def test_framework_root():
    """Test framework_root() resolves to klc repo root."""
    root = paths.framework_root()
    assert root.is_dir()
    # Verify it's klc repo (has core/, scripts/, config/)
    assert (root / "core").is_dir()
    assert (root / "scripts").is_dir()
    assert (root / "config").is_dir()


def test_project_root_with_env_var(monkeypatch):
    """Test project_root() uses $PROJECT_ROOT if set."""
    test_path = "/tmp/test_project"
    monkeypatch.setenv("PROJECT_ROOT", test_path)
    root = paths.project_root()
    assert str(root) == test_path


def test_project_root_fallback(monkeypatch):
    """Test project_root() falls back to parent of framework_root()."""
    # KLC-103: monkeypatch.delenv (not a bare os.environ.pop) so the REAL
    # PROJECT_ROOT this pytest process was invoked with is restored after
    # this test, not left permanently unset for the rest of the run — a
    # bare pop() here (and the analogous one this test used to have in
    # test_project_root_with_env_var's manual finally block) silently broke
    # every later test in the suite that resolves paths via PROJECT_ROOT
    # without its own override (e.g. detect_languages.detect() reading
    # .klc/index/structural.json).
    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    root = paths.project_root()
    assert root == paths.framework_root().parent


def test_klc_dir():
    """Test klc_dir() returns .klc/ under project root."""
    klc = paths.klc_dir()
    assert klc.name == ".klc"
    assert klc.parent == paths.project_root()


def test_klc_index_dir():
    """Test klc_index_dir() returns .klc/index/."""
    index = paths.klc_index_dir()
    assert index.name == "index"
    assert index.parent == paths.klc_dir()


def test_klc_tickets_dir():
    """Test klc_tickets_dir() returns .klc/tickets/."""
    tickets = paths.klc_tickets_dir()
    assert tickets.name == "tickets"
    assert tickets.parent == paths.klc_dir()


def test_klc_ticket_dir():
    """Test klc_ticket_dir() returns .klc/tickets/<KEY>/."""
    ticket_dir = paths.klc_ticket_dir("KLC-001")
    assert ticket_dir.name == "KLC-001"
    assert ticket_dir.parent == paths.klc_tickets_dir()


def test_klc_ticket_meta_file():
    """Test klc_ticket_meta_file() returns meta.json path."""
    meta = paths.klc_ticket_meta_file("KLC-007")
    assert meta.name == "meta.json"
    assert meta.parent.name == "KLC-007"


def test_klc_knowledge_dir():
    """Test klc_knowledge_dir() returns .klc/knowledge/."""
    knowledge = paths.klc_knowledge_dir()
    assert knowledge.name == "knowledge"
    assert knowledge.parent == paths.klc_dir()
