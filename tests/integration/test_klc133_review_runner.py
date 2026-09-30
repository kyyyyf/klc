"""AC-5: `scripts/review-runner.py` delegates all telemetry for a reviewer
dispatch to `run_agent` (ticket + `telemetry_phase="review"` + reviewer name
+ the job card's byte size) and no longer writes an attempt of its own.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from _klc133_support import (  # noqa: E402
    all_attempts,
    fixture_json,
    fixture_text,
    seed_ticket,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)

FW_ROOT = Path(__file__).resolve().parents[2]


def _load_review_runner():
    """`scripts/review-runner.py` cannot be `import`ed by a dotted module
    name (the file has a hyphen) — load it via `spec_from_file_location`."""
    spec = importlib.util.spec_from_file_location(
        "klc133_review_runner", FW_ROOT / "scripts" / "review-runner.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_card(tmp_path: Path, name: str, spec_path: Path) -> Path:
    card = tmp_path / f"job-{name}.md"
    card.write_text(
        f"# Review sub-agent job: {name}\n\n"
        f"Prompt file: core/agents/review/{name}.md\n"
        "Inputs:\n"
        f"- spec:              {spec_path}\n",
        encoding="utf-8",
    )
    return card


# --- a successful dispatch leaves exactly one review attempt -----------------

_SUCCESS_CASES = [
    pytest.param(lambda: fixture_text("envelope-single.json"), "provider", id="envelope"),
    pytest.param(lambda: "plain reviewer text, no envelope", "estimated", id="plain-text"),
]


@pytest.mark.parametrize("build_stdout,expected_source", _SUCCESS_CASES)
def test_successful_dispatch_leaves_exactly_one_review_attempt_provider_or_estimated(
        tmp_path, klc133_hermetic, monkeypatch, build_stdout, expected_source):
    """AC-5: a successful dispatch leaves exactly one `review` attempt
    (provider when the envelope parsed, estimated with `card_bytes`
    otherwise), tagged with the reviewer name and carrying no `run_pass`
    key (test-plan-review F-3: the reviewer/run_pass tag families never
    both appear on one attempt)."""
    import runner
    rr = _load_review_runner()
    project = klc133_hermetic
    tdir = seed_ticket(project, "KLC-RR1", track="M", phase="review:work")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")

    monkeypatch.setitem(runner._DISPATCH, "anthropic",
                        lambda *a, **k: (0, build_stdout(), ""))

    card = _write_card(tmp_path, "security", tdir / "spec.md")
    partial = tmp_path / "security.partial.md"
    rc = rr.main([str(card), str(partial)])
    assert rc == 0

    attempts = all_attempts("KLC-RR1", "review")
    assert len(attempts) == 1
    a = attempts[0]
    assert a["source"] == expected_source
    assert a["reviewer"] == "security"
    assert "run_pass" not in a
    if expected_source == "estimated":
        assert a["card_bytes"] == card.stat().st_size
    else:
        assert "card_bytes" not in a


# --- a failed dispatch leaves at most the AC-4 failed:true attempt ----------

_FAILED_CASES = [
    pytest.param(lambda: fixture_text("envelope-single.json"), id="rc1-with-envelope"),
    pytest.param(lambda: "", id="rc1-without-envelope"),
]


@pytest.mark.parametrize("build_stdout", _FAILED_CASES)
def test_failed_dispatch_leaves_at_most_the_ac4_failed_attempt(
        tmp_path, klc133_hermetic, monkeypatch, build_stdout):
    """AC-5: a failed dispatch leaves at most the AC-4 `failed: true`
    attempt — one when the envelope still parsed, none otherwise."""
    import runner
    rr = _load_review_runner()
    project = klc133_hermetic
    tdir = seed_ticket(project, "KLC-RR2", track="M", phase="review:work")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")

    stdout_text = build_stdout()
    monkeypatch.setitem(runner._DISPATCH, "anthropic",
                        lambda *a, **k: (1, stdout_text, "boom"))

    card = _write_card(tmp_path, "security", tdir / "spec.md")
    partial = tmp_path / "security.partial.md"
    rc = rr.main([str(card), str(partial)])
    assert rc == 1

    attempts = all_attempts("KLC-RR2", "review")
    if stdout_text:
        assert len(attempts) == 1
        assert attempts[0]["failed"] is True
    else:
        assert attempts == []


# --- the partial file and rc are unchanged by the delegation ----------------

_PARTIAL_CASES = [
    pytest.param(lambda: fixture_text("envelope-single.json"),
                lambda: fixture_json("envelope-single.json")["result"],
                id="envelope"),
    pytest.param(lambda: "plain reviewer text, no envelope",
                lambda: "plain reviewer text, no envelope",
                id="plain-text"),
]


@pytest.mark.parametrize("build_stdout,expected_text", _PARTIAL_CASES)
def test_partial_file_and_rc_are_unchanged_by_the_delegation(
        tmp_path, klc133_hermetic, monkeypatch, build_stdout, expected_text):
    """AC-5: the partial file and rc are unchanged by delegating telemetry
    to run_agent — the partial holds the result text (or the plain text),
    and rc is 0."""
    import runner
    rr = _load_review_runner()
    project = klc133_hermetic
    tdir = seed_ticket(project, "KLC-RR3", track="M", phase="review:work")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")

    monkeypatch.setitem(runner._DISPATCH, "anthropic",
                        lambda *a, **k: (0, build_stdout(), ""))

    card = _write_card(tmp_path, "security", tdir / "spec.md")
    partial = tmp_path / "security.partial.md"
    rc = rr.main([str(card), str(partial)])
    assert rc == 0
    assert partial.read_text(encoding="utf-8") == expected_text()


# --- the stale docstring is corrected ----------------------------------------

def test_stale_no_provider_usage_block_docstring_is_corrected():
    """AC-5: the stale "no provider usage block to read" docstring is gone
    now that the review runner delegates to run_agent, which does read
    one."""
    text = (FW_ROOT / "scripts" / "review-runner.py").read_text(encoding="utf-8")
    assert "this path has no provider usage block to read" not in text


# --- a ticketless spec records no attempt ------------------------------------

def test_ticketless_spec_records_no_attempt(tmp_path, klc133_hermetic, monkeypatch):
    """AC-5: a spec outside any ticket dir dispatches fine (rc 0) and
    records no attempt anywhere under the tmp project — write_token_metrics
    itself already no-ops on an empty ticket, and `_ticket_from_spec`
    returns None for a spec with no sibling meta.json."""
    import runner
    rr = _load_review_runner()
    project = klc133_hermetic
    spec_path = tmp_path / "standalone-spec.md"
    spec_path.write_text("spec\n", encoding="utf-8")

    monkeypatch.setitem(runner._DISPATCH, "anthropic",
                        lambda *a, **k: (0, "plain reviewer text", ""))

    card = _write_card(tmp_path, "security", spec_path)
    partial = tmp_path / "security.partial.md"
    rc = rr.main([str(card), str(partial)])
    assert rc == 0

    scratch = project / ".klc" / "scratch"
    assert not scratch.exists() or list(scratch.rglob("*.jsonl")) == []
