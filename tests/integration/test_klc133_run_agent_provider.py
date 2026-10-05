"""AC-3/AC-4: `run_agent` writes exactly one attempt per headless dispatch —
a provider attempt when the envelope parses, an estimated one otherwise —
tagged under keyword-only telemetry tags separate from the existing
`ticket`/`phase_id`, and a failed dispatch that still reported usage is
recorded with `failed: true`.
"""
from __future__ import annotations

import json

import pytest

from _klc133_support import (  # noqa: E402
    FakeAnthropic,
    all_attempts,
    fixture_json,
    fixture_text,
    seed_ticket,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)


def _paths(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do the thing", encoding="utf-8")
    out_path = tmp_path / "out.md"
    return prompt_path, out_path


# --- AC-3: one provider attempt per fixture, fields equal to the envelope -----

_PROVIDER_EXPECTED = {
    "envelope-single.json": {
        "in": 9, "out": 43, "cache_hit": 18003, "cache_write": 3408,
        "cost_usd": 0.0088403, "num_turns": 1, "duration_ms": 1150,
    },
    # step-10 review-fix (AC-1): this fixture's own total_cost_usd
    # (0.02810725) disagrees with its modelUsage costUSD sum (0.03161175);
    # the parser now prefers the modelUsage figure and records cost_basis.
    "envelope-multiturn-cache.json": {
        "in": 37, "out": 446, "cache_hit": 61525, "cache_write": 15813,
        "cost_usd": 0.03161175, "cost_basis": "modelUsage",
        "num_turns": 2, "duration_ms": 4000,
    },
    # step-10 review-fix (AC-1): num_turns/duration_ms are now summed across
    # both result elements of the real captured array (2+1, 4000+1176).
    "envelope-verbose-subagent.json": {
        "in": 37, "out": 446, "cache_hit": 61525, "cache_write": 15813,
        "cost_usd": 0.03161175, "num_turns": 3, "duration_ms": 5176,
    },
}


@pytest.mark.parametrize("fixture_name", sorted(_PROVIDER_EXPECTED))
def test_run_agent_writes_one_provider_attempt_per_fixture_through_the_fake_dispatcher(
        tmp_path, klc133_hermetic, monkeypatch, fixture_name):
    """AC-3: run_agent writes one provider attempt per fixture, through the
    real dispatcher contract (FakeAnthropic), with in/out/cache_hit/
    cache_write/cost_usd/num_turns/duration_ms equal to the fixture."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R1", track="M", phase="build:work")
    fake = FakeAnthropic(lambda resolved, prompt: (0, fixture_text(fixture_name), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("build", prompt_path, out_path, telemetry_ticket="KLC-R1")
    assert rc == 0

    attempts = all_attempts("KLC-R1", "build")
    assert len(attempts) == 1
    a = attempts[0]
    assert a["source"] == "provider"
    expected = _PROVIDER_EXPECTED[fixture_name]
    for key, value in expected.items():
        if key == "cost_usd":
            assert a[key] == pytest.approx(value)
        else:
            assert a[key] == value
    if "cost_basis" not in expected:
        assert "cost_basis" not in a


# --- AC-3: the tag phase, when given, wins over the dispatch phase -----------

@pytest.mark.parametrize("give_tag_phase", [True, False],
                         ids=["tag-phase-given", "tag-phase-absent"])
def test_attempt_lands_under_the_tag_phase_when_given_and_the_dispatch_phase_otherwise(
        tmp_path, klc133_hermetic, monkeypatch, give_tag_phase):
    """AC-3: an attempt lands under telemetry_phase when given, else under
    the dispatch's own phase_id."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R2", track="M", phase="build:work")
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    kwargs = {"telemetry_ticket": "KLC-R2"}
    if give_tag_phase:
        kwargs["telemetry_phase"] = "review"
    rc = runner.run_agent("build", prompt_path, out_path, **kwargs)
    assert rc == 0

    expected_phase = "review" if give_tag_phase else "build"
    other_phase = "build" if give_tag_phase else "review"
    assert len(all_attempts("KLC-R2", expected_phase)) == 1
    assert all_attempts("KLC-R2", other_phase) == []


# --- AC-3: telemetry-only kwargs never trigger the C-005 park guard ----------

def test_telemetry_only_kwargs_never_trigger_the_interactive_park_guard_and_do_write_an_attempt(
        tmp_path, klc133_hermetic, monkeypatch):
    """AC-3: passing only telemetry tags (no `ticket=`) against an
    interactive phase never triggers the C-005 park guard — the dispatcher
    really runs — and still writes exactly one attempt, tagged from
    `telemetry_ticket` alone."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R3", track="M", phase="intake",
                clarify_required=True)
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("intake", prompt_path, out_path,
                          telemetry_ticket="KLC-R3", telemetry_phase="intake")
    assert rc == 0
    assert fake.calls == ["intake"], "the dispatcher must actually have run"

    meta = json.loads(
        (project / ".klc" / "tickets" / "KLC-R3" / "meta.json").read_text())
    assert "parked" not in meta
    assert len(all_attempts("KLC-R3", "intake")) == 1


# --- AC-3/AC-7: the autorunner's own call shape (ticket= alone) --------------

def test_ticket_kwarg_alone_still_records_under_the_dispatch_phase(
        tmp_path, klc133_hermetic, monkeypatch):
    """AC-3/AC-7: `ticket=` alone (the autorunner's call shape, no telemetry
    tags) still records one provider attempt under the dispatch phase,
    carrying cost_usd."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R4", track="M", phase="review:work")
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("review", prompt_path, out_path, track="M",
                          ticket="KLC-R4")
    assert rc == 0
    attempts = all_attempts("KLC-R4", "review")
    assert len(attempts) == 1
    assert attempts[0]["cost_usd"] == pytest.approx(0.0088403)


# --- AC-3: pin — no ticket, no telemetry_ticket => zero attempts -------------

def test_no_ticket_and_no_telemetry_ticket_writes_zero_attempts(
        tmp_path, klc133_hermetic, monkeypatch):
    """AC-3: pin — the ticketless indexing-agent shape of scripts/init.py:
    neither ticket= nor telemetry_ticket= writes zero attempts."""
    import runner
    project = klc133_hermetic
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("build", prompt_path, out_path)
    assert rc == 0
    scratch = project / ".klc" / "scratch"
    assert not scratch.exists() or list(scratch.rglob("*.jsonl")) == []


# --- AC-3: no measured key ever appears on an estimated attempt --------------

def _envelope_missing_output_tokens() -> str:
    env = fixture_json("envelope-single.json")
    env["usage"].pop("output_tokens", None)
    for model_usage in env.get("modelUsage", {}).values():
        model_usage.pop("outputTokens", None)
    return json.dumps(env)


_ESTIMATED_INPUTS = [
    pytest.param("plain text reply, no envelope here", id="plain-text"),
    pytest.param(
        fixture_text("envelope-single.json")
        [: len(fixture_text("envelope-single.json")) // 2],
        id="fixture-cut-in-half"),
    pytest.param(_envelope_missing_output_tokens(), id="usage-without-output-tokens"),
]


@pytest.mark.parametrize("stdout_text", _ESTIMATED_INPUTS)
def test_dispatch_without_usable_usage_records_no_attempt(
        tmp_path, klc133_hermetic, monkeypatch, stdout_text):
    """AC-3 / KLC-174 step-5: a reply without usable usage leaves NO attempt
    (the `estimated` fallback is gone, so no measured key can sit on one)."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R6", track="M", phase="build:work")
    fake = FakeAnthropic(lambda resolved, prompt: (0, stdout_text, ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("build", prompt_path, out_path,
                          telemetry_ticket="KLC-R6")
    assert rc == 0
    assert all_attempts("KLC-R6", "build") == []


# --- AC-4: a failed run that still holds usage is recorded failed: true -----

_FAILED_WITH_ENVELOPE = [
    pytest.param(1, "envelope-single.json", id="rc1-with-envelope"),
    pytest.param(0, "envelope-is-error.json", id="rc0-is-error"),
]


@pytest.mark.parametrize("rc_value,fixture_name", _FAILED_WITH_ENVELOPE)
def test_failed_dispatch_with_envelope_records_one_failed_true_attempt(
        tmp_path, klc133_hermetic, monkeypatch, rc_value, fixture_name):
    """AC-4: a failed run (non-zero rc, or is_error: true) that still holds
    a parseable envelope with usage records exactly one provider attempt
    with failed: true."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R7", track="M", phase="build:work")
    fake = FakeAnthropic(
        lambda resolved, prompt: (rc_value, fixture_text(fixture_name), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    runner.run_agent("build", prompt_path, out_path, telemetry_ticket="KLC-R7")
    attempts = all_attempts("KLC-R7", "build")
    assert len(attempts) == 1
    assert attempts[0]["source"] == "provider"
    assert attempts[0]["failed"] is True


# --- AC-4: a failed run with no usable envelope records nothing -------------

_FAILED_NO_ENVELOPE = [
    pytest.param(1, "", "boom: dispatch failed", id="rc1-stderr-only"),
    pytest.param(2, "garbage {not json", "", id="rc2-garbage-stdout"),
]


@pytest.mark.parametrize("rc_value,stdout_text,stderr_text", _FAILED_NO_ENVELOPE)
def test_failed_dispatch_without_envelope_records_nothing(
        tmp_path, klc133_hermetic, monkeypatch, rc_value, stdout_text, stderr_text):
    """AC-4: a failed dispatch with no usable envelope records nothing at all."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R8", track="M", phase="build:work")
    fake = FakeAnthropic(lambda resolved, prompt: (rc_value, stdout_text, stderr_text))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    runner.run_agent("build", prompt_path, out_path, telemetry_ticket="KLC-R8")
    assert all_attempts("KLC-R8", "build") == []


def test_successful_run_attempt_has_no_failed_key(tmp_path, klc133_hermetic, monkeypatch):
    """AC-4: a normal successful run's attempt carries no `failed` key at all."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R9", track="M", phase="build:work")
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("build", prompt_path, out_path, telemetry_ticket="KLC-R9")
    assert rc == 0
    attempts = all_attempts("KLC-R9", "build")
    assert len(attempts) == 1
    assert "failed" not in attempts[0]


# --- step-10 review-fix (AC-4, code-review LOW + external LOW) --------------

def test_is_error_with_rc0_and_no_usable_usage_records_nothing(
        tmp_path, klc133_hermetic, monkeypatch):
    """AC-4: rc 0 with an `is_error: true` envelope but no parseable
    input_tokens/output_tokens records NOTHING (KLC-174 step-5: no
    `estimated` attempt), so an is_error run never counts as an executed,
    successful review pass."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R12", track="M", phase="review:work")
    stdout_text = json.dumps({
        "type": "result", "is_error": True, "usage": {}, "modelUsage": {},
        "result": "boom",
    })
    fake = FakeAnthropic(lambda resolved, prompt: (0, stdout_text, ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("review", prompt_path, out_path,
                          telemetry_ticket="KLC-R12", reviewer="security")
    assert rc == 0  # the CLI itself still "succeeded" procedurally

    assert all_attempts("KLC-R12", "review") == []


# --- C-003: a telemetry-write failure never changes rc or output ------------

def test_telemetry_write_failure_never_changes_rc_or_output(
        tmp_path, klc133_hermetic, monkeypatch):
    """AC-3/C-003: a telemetry-write failure never changes run_agent's rc or
    the output file it wrote."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R10", track="M", phase="build:work")
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(runner, "_write_token_metrics", _boom)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("build", prompt_path, out_path, telemetry_ticket="KLC-R10")
    assert rc == 0
    assert out_path.read_text(encoding="utf-8") == "ok"


# --- AC-3: reviewer/step/run_pass are copied onto the attempt ---------------

def test_reviewer_step_and_run_pass_tags_are_copied_onto_the_attempt(
        tmp_path, klc133_hermetic, monkeypatch):
    """AC-3: reviewer/step/run_pass tags are copied verbatim onto the attempt."""
    import runner
    project = klc133_hermetic
    seed_ticket(project, "KLC-R11", track="M", phase="build:work")
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)
    prompt_path, out_path = _paths(tmp_path)

    rc = runner.run_agent("build", prompt_path, out_path,
                          telemetry_ticket="KLC-R11", reviewer="code-reviewer",
                          step=3, run_pass="per-step-review")
    assert rc == 0
    attempts = all_attempts("KLC-R11", "build")
    assert len(attempts) == 1
    assert attempts[0]["reviewer"] == "code-reviewer"
    assert attempts[0]["step"] == 3
    assert attempts[0]["run_pass"] == "per-step-review"
