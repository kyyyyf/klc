"""AC-14: a real-substrate property test. Seeded random sequences of
dispatches (fixture-derived envelopes with random counts, plain-text
replies, failed runs, all three headless callers, inside and outside an
open transaction) drive the real `run_agent`, `write_token_metrics`, the
token journal, `state_tx`'s drain and the rollup on a scratch ticket tree.
"""
from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

from _klc133_support import (  # noqa: E402
    FakeAnthropic,
    fixture_json,
    fixture_text,
    seed_ticket,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)

FW_ROOT = Path(__file__).resolve().parents[2]
SEEDS = list(range(1, 31))

_CALLERS = ("review", "build", "ticket_run_agent")
_REPLIES = ("multiturn", "is_error", "plain", "rc1_envelope", "rc1_stderr")
# KLC-174 step-5: replies without a parseable usage envelope record nothing.
_NO_USAGE_REPLIES = ("plain", "rc1_stderr")


def _load_review_runner():
    spec = importlib.util.spec_from_file_location(
        "klc133_prop_review_runner", FW_ROOT / "scripts" / "review-runner.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_card(card_path: Path, spec_path: Path, *, reviewer: str = "security") -> Path:
    """`reviewer` names a REAL prompt file under core/agents/review/ (only
    `security.md` is used here); `card_path` may vary freely per dispatch
    without touching that reference."""
    card_path.write_text(
        f"# Review sub-agent job: {reviewer}\n\n"
        f"Prompt file: core/agents/review/{reviewer}.md\n"
        "Inputs:\n"
        f"- spec:              {spec_path}\n",
        encoding="utf-8",
    )
    return card_path


def _random_envelope(rng: random.Random) -> str:
    """A real captured multi-turn envelope with its counts randomized."""
    env = fixture_json("envelope-multiturn-cache.json")
    bonus = rng.randint(0, 500)
    for model_usage in env["modelUsage"].values():
        for key in ("inputTokens", "outputTokens", "cacheReadInputTokens",
                    "cacheCreationInputTokens"):
            if key in model_usage:
                model_usage[key] = model_usage[key] + bonus
    env["total_cost_usd"] = round(env["total_cost_usd"] + rng.random(), 6)
    return json.dumps(env)


def _reply_for(spec: str, rng: random.Random) -> tuple[int, str, str]:
    """(rc, stdout, stderr) for one of the five named reply shapes."""
    if spec == "multiturn":
        return (0, _random_envelope(rng), "")
    if spec == "is_error":
        return (0, fixture_text("envelope-is-error.json"), "")
    if spec == "plain":
        return (0, "plain reviewer text, no envelope", "")
    if spec == "rc1_envelope":
        return (1, fixture_text("envelope-single.json"), "boom")
    if spec == "rc1_stderr":
        return (1, "", "boom: dispatch failed")
    raise ValueError(spec)


def _read_meta(project: Path, ticket: str) -> dict:
    return json.loads(
        (project / ".klc" / "tickets" / ticket / "meta.json")
        .read_text(encoding="utf-8"))


def _write_meta(project: Path, ticket: str, meta: dict) -> None:
    (project / ".klc" / "tickets" / ticket / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _attempt_ids(project: Path, ticket: str) -> set[str]:
    import metrics
    meta = _read_meta(project, ticket)
    return {rec.get("id") for _phase, rec in metrics.iter_attempts(meta, ticket)}


def _attempts_by_id(project: Path, ticket: str) -> dict[str, tuple[str, dict]]:
    import metrics
    meta = _read_meta(project, ticket)
    return {rec.get("id"): (phase, rec)
           for phase, rec in metrics.iter_attempts(meta, ticket)}


def _run_one_dispatch(rng, project, ticket, tmp_path, caller, reply_spec, n):
    """Dispatch one call through the real code and return the phase it was
    tagged under."""
    import runner

    rc_value, stdout_text, stderr_text = _reply_for(reply_spec, rng)
    monkeypatch_dispatch = lambda *a, **k: (rc_value, stdout_text, stderr_text)  # noqa: E731
    runner._DISPATCH["anthropic"] = monkeypatch_dispatch

    if caller == "review":
        rr = _load_review_runner()
        spec_path = project / ".klc" / "tickets" / ticket / "spec.md"
        card = _write_card(tmp_path / f"job-{n}.md", spec_path)
        partial = tmp_path / f"security-{n}.partial.md"
        rr.main([str(card), str(partial)])
        return "review"

    if caller == "build":
        import build_orchestrator as bo
        prompt_path = tmp_path / f"prompt-{n}.md"
        prompt_path.write_text("do the thing", encoding="utf-8")
        out_path = tmp_path / f"out-{n}.md"
        dispatch = bo._telemetry_dispatch(ticket)
        step = rng.randint(1, 5)
        run_pass = rng.choice(["step", "per-step-review", "per-step-fix"])
        dispatch("build", prompt_path, out_path, track="M", step=step,
                 run_pass=run_pass)
        return "build"

    # "ticket_run_agent": the autorunner's own call shape (ticket= alone),
    # NOT the real autorunner._dispatch — that would ALSO render a card and
    # write a second, intended attempt per dispatch (AC-7), which would
    # break "at most one attempt per dispatch" here (impl-plan-review F-4).
    prompt_path = tmp_path / f"prompt-{n}.md"
    prompt_path.write_text("do the thing", encoding="utf-8")
    out_path = tmp_path / f"out-{n}.md"
    runner.run_agent("design", prompt_path, out_path, track="M", ticket=ticket)
    return "design"


def _run_sequence(rng, project, ticket, tmp_path, state_tx, dispatches):
    """Drive `dispatches` random dispatches through the real callers,
    tracking (a) the record captured right after each dispatch (`recorded`,
    with AC-8's carry-forward modelled per-phase) and (b) the count of
    successful (non-failed) reviewer dispatches. Asserts the "at most one
    (exactly one unless rc1_stderr)" new-attempt invariant along the way."""
    import contextlib

    recorded: dict[str, dict] = {}
    last_card_bytes: dict[str, int] = {}
    successes = 0

    for n, (caller, reply_spec, inside) in enumerate(dispatches):
        before = _attempt_ids(project, ticket)
        ctx = (state_tx.state_tx(ticket, "prop dispatch") if inside
              else contextlib.nullcontext())
        with ctx:
            _run_one_dispatch(rng, project, ticket, tmp_path, caller,
                              reply_spec, n)

        new_ids = _attempt_ids(project, ticket) - before
        assert len(new_ids) <= 1, f"dispatch {n}: >1 new attempt"
        if reply_spec in _NO_USAGE_REPLIES:
            assert len(new_ids) == 0, \
                f"dispatch {n}: a dispatch with no usable envelope must " \
                f"record nothing (KLC-174: no `estimated` attempt)"
        else:
            assert len(new_ids) == 1, \
                f"dispatch {n}: expected exactly one new attempt"

        if new_ids:
            rid = next(iter(new_ids))
            rec_phase, rec = _attempts_by_id(project, ticket)[rid]
            recorded[rid] = dict(rec)
            if rec.get("source") != "provider" and "card_bytes" not in rec:
                inherited = last_card_bytes.get(rec_phase)
                if inherited is not None:
                    recorded[rid]["card_bytes"] = inherited
            if rec.get("card_bytes") is not None:
                last_card_bytes[rec_phase] = rec["card_bytes"]
            if caller == "review" and reply_spec == "multiturn":
                successes += 1

    return recorded, successes


@pytest.mark.parametrize("seed", SEEDS)
def test_seeded_dispatch_sequences_leave_one_attempt_each_and_agree_end_to_end(
        seed, klc133_hermetic, tmp_path, monkeypatch):
    """AC-14: every dispatch leaves at most one attempt (exactly one unless
    the reply is a failed dispatch with no usable envelope), no attempt
    carries a measured key unless source is provider, the drained
    meta.json equals the journaled records (a non-provider attempt
    recorded without card_bytes inherits the previous same-phase attempt's
    card_bytes — the only place AC-8's carry-forward is modelled, D-111/
    A-101), every rollup by_source bucket's samples equals the attempt
    count of that source, and review_llm_passes_per_ticket equals the
    count of successful (non-failed) reviewer dispatches."""
    import state_feature
    import state_tx

    rng = random.Random(seed)
    monkeypatch.setattr(state_feature, "enabled", lambda: False)
    project = klc133_hermetic
    ticket = "KLC-P01"
    tdir = seed_ticket(project, ticket, track="M", phase="review:work")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")

    n_dispatches = rng.randint(5, 30)
    dispatches = [
        (rng.choice(_CALLERS), rng.choice(_REPLIES), rng.choice([True, False]))
        for _ in range(n_dispatches)
    ]
    recorded, successes = _run_sequence(rng, project, ticket, tmp_path,
                                        state_tx, dispatches)

    # Final drain: fold everything still buffered into meta.json.
    with state_tx.state_tx(ticket, "final drain"):
        pass

    _verify_against(project, ticket, recorded, successes)


def _verify_against(project: Path, ticket: str, recorded: dict,
                    successes: int) -> None:
    """The property checker: raises AssertionError on any disagreement
    between what was recorded at dispatch time and the final drained
    state, or between the drained state and the rollup."""
    import metrics

    meta = _read_meta(project, ticket)
    all_recs = list(metrics.iter_attempts(meta, ticket))

    # 1. no measured key on a non-provider attempt.
    for phase, rec in all_recs:
        if rec.get("source") != "provider":
            for key in ("cost_usd", "num_turns", "duration_ms", "cache_write"):
                assert key not in rec, (
                    f"measured key {key!r} found on non-provider attempt "
                    f"{rec.get('id')} (phase {phase})")

    # 2. every recorded attempt survives the drain, byte-identical modulo
    #    'phase' (and the modelled carry-forward already folded into
    #    `recorded` above).
    drained_by_id = {rec.get("id"): rec for _phase, rec in all_recs}
    for rid, expected in recorded.items():
        assert rid in drained_by_id, f"attempt {rid} missing after the drain"
        actual = drained_by_id[rid]
        exp = {k: v for k, v in expected.items() if k != "phase"}
        assert actual == exp, f"attempt {rid}: {actual} != {exp}"

    # 3. every rollup by_source bucket's samples equals the attempt count
    #    of that source.
    counts: dict[str, dict[str, int]] = {}
    for phase, rec in all_recs:
        source = rec.get("source", "estimated")  # old records may lack it
        counts.setdefault(phase, {}).setdefault(source, 0)
        counts[phase][source] += 1

    metrics.cmd_rollup(None)
    payload = json.loads(
        (project / ".klc" / "knowledge" / "process-metrics.json")
        .read_text(encoding="utf-8"))
    track = payload["per_track"]["M"]
    for phase, source_counts in counts.items():
        bucket = track["tokens_by_phase"][phase]["by_source"]
        for source, n in source_counts.items():
            assert bucket[source]["samples"] == n, (
                f"{phase}/{source}: rollup samples {bucket[source]['samples']}"
                f" != actual {n}")

    # 4. review_llm_passes_per_ticket equals the count of successful
    #    (non-failed) reviewer dispatches.
    expected_rlp = successes if successes else None
    actual_rlp = track["review_llm_passes_per_ticket"]
    if expected_rlp is None:
        assert actual_rlp is None
    else:
        assert actual_rlp == pytest.approx(expected_rlp)


def test_property_checker_rejects_a_corrupted_record(klc133_hermetic, tmp_path,
                                                      monkeypatch):
    """impl-plan-review F-5: the checker itself must actually bite — inject
    a cost_usd into one non-provider attempt, and separately delete one
    attempt, and assert the checker raises for each."""
    import state_feature
    import state_tx

    rng = random.Random(SEEDS[0])
    monkeypatch.setattr(state_feature, "enabled", lambda: False)
    project = klc133_hermetic
    ticket = "KLC-P02"
    tdir = seed_ticket(project, ticket, track="M", phase="review:work")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")

    dispatches = [
        (rng.choice(_CALLERS), rng.choice(_REPLIES), rng.choice([True, False]))
        for _ in range(10)
    ]
    # Guarantee at least one provider attempt exists for the corruptions to
    # target, regardless of what the random draws above happened to produce.
    dispatches.append(("ticket_run_agent", "multiturn", False))
    recorded, successes = _run_sequence(rng, project, ticket, tmp_path,
                                        state_tx, dispatches)

    with state_tx.state_tx(ticket, "final drain"):
        pass

    # Sanity: the clean state passes.
    _verify_against(project, ticket, recorded, successes)

    # --- corruption 1: add a non-provider attempt carrying a measured key ---
    meta = _read_meta(project, ticket)
    entry = meta["metrics"]["tokens"].setdefault("design", {"attempts": []})
    entry["attempts"].append({"id": "corrupt1", "ts": "2026-01-01T00:00:00Z",
                              "in": 1, "out": 1, "cache_hit": 0,
                              "source": "signal", "cost_usd": 999})
    _write_meta(project, ticket, meta)

    with pytest.raises(AssertionError):
        _verify_against(project, ticket, recorded, successes)

    meta = _read_meta(project, ticket)
    meta["metrics"]["tokens"]["design"]["attempts"] = [
        a for a in meta["metrics"]["tokens"]["design"]["attempts"]
        if a.get("id") != "corrupt1"]
    _write_meta(project, ticket, meta)

    # --- corruption 2: delete one attempt entirely -------------------------
    meta = _read_meta(project, ticket)
    removed = False
    for phase_id, entry in meta.get("metrics", {}).get("tokens", {}).items():
        if entry.get("attempts"):
            entry["attempts"].pop()
            removed = True
            break
    assert removed, "the seeded sequence must have produced at least one attempt"
    _write_meta(project, ticket, meta)

    with pytest.raises(AssertionError):
        _verify_against(project, ticket, recorded, successes)
