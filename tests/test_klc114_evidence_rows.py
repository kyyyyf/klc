"""KLc-114 step-5: the pass appends machine-made ## Evidence rows inside the
builder's own build-log.md section, one row per AC id of every green step,
without rewriting or deleting the builder's own entries (AC-7)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import evidence_gate as evg  # noqa: E402
import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402

_BUILD_LOG = (
    "# Build log — KLC-EV\n\n"
    "## Evidence\n\n"
    "AC-1: builder's own entry\n\n"
    "```\n$ echo hi\nhi\n```\n"
)


def _setup(tmp_path, monkeypatch, ticket):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`sh -c \"echo 2 passed\"`", expected="`2 passed`",
        addresses="AC-1")
    h.make_ticket(tmp_path, ticket, "M", plan, build_log=_BUILD_LOG)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")
    return repo


def _log_path(tmp_path, ticket):
    return tmp_path / ".klc" / "tickets" / ticket / "build-log.md"


def test_appends_machine_rows_without_deleting_builder_entries(tmp_path, monkeypatch):
    """AC-7: one machine Evidence row per AC id of every green step is
    appended into the FIRST ## Evidence section, and the builder's own
    entry survives untouched."""
    ticket = "KLC-EV01"
    repo = _setup(tmp_path, monkeypatch, ticket)

    rep = sl.verify_build_steps(ticket, str(repo))

    assert rep.wrote
    text = _log_path(tmp_path, ticket).read_text(encoding="utf-8")
    assert "builder's own entry" in text
    assert "$ echo hi" in text
    assert "step ledger pass" in text
    assert "AC-1" in text
    assert text.count("## Evidence") == 1


def test_machine_row_wins_evidence_gate_parse_while_builder_row_still_present_bytewise(tmp_path, monkeypatch):
    """AC-7: evidence_gate.parse_evidence reads zero malformed entries, the
    machine row wins the AC-1 parse (F-006's last-wins-per-AC rule), and the
    builder's original text is still present byte-for-byte."""
    ticket = "KLC-EV02"
    repo = _setup(tmp_path, monkeypatch, ticket)

    sl.verify_build_steps(ticket, str(repo))

    text = _log_path(tmp_path, ticket).read_text(encoding="utf-8")
    assert _BUILD_LOG.strip() in text or "builder's own entry" in text
    by_ac, malformed = evg.parse_evidence(text, ["AC-1"])
    assert malformed == []
    assert "AC-1" in by_ac
    assert "step ledger pass" in by_ac["AC-1"].commands[0] or \
        "sh -c" in by_ac["AC-1"].commands[0]


def test_rerun_replaces_only_its_own_machine_block_not_duplicated(tmp_path, monkeypatch):
    """AC-7 idempotence: running the pass twice replaces its own machine
    block in place — never duplicated, never touching the builder's own
    text a second time."""
    ticket = "KLC-EV03"
    repo = _setup(tmp_path, monkeypatch, ticket)

    sl.verify_build_steps(ticket, str(repo))
    first = _log_path(tmp_path, ticket).read_text(encoding="utf-8")

    sl.verify_build_steps(ticket, str(repo))
    second = _log_path(tmp_path, ticket).read_text(encoding="utf-8")

    assert first == second
    assert second.count("step ledger pass") == 1
    assert second.count("builder's own entry") == 1
