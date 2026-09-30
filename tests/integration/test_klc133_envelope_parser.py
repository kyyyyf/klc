"""AC-1/AC-2: a strict, total parser reads the eight named fields from either
envelope form (a single JSON object, or the ``--verbose`` array's last
``type: "result"`` element), and the output split never lets hostile stdout
(garbage, wrong types, bad encoding, a non-string ``result``) raise out of
``run_agent``.
"""
from __future__ import annotations

import copy
import json
from unittest.mock import patch

import pytest

from _klc133_support import (  # noqa: E402
    fixture_json,
    fixture_text,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)


# --- AC-1: every named field, from every AC-13 fixture ------------------------

_AC1_EXPECTED = {
    "envelope-single.json": {
        "input_tokens": 9, "output_tokens": 43,
        "cache_read_input_tokens": 18003, "cache_creation_input_tokens": 3408,
        "total_cost_usd": 0.0088403, "num_turns": 1, "duration_ms": 1150,
        "is_error": False,
    },
    # step-10 review-fix (AC-1, code-review MEDIUM + external MEDIUM): this
    # fixture's own `total_cost_usd` (0.02810725, the earlier segment's
    # point-in-time figure) disagrees with its own `modelUsage` costUSD sum
    # (0.03161175, already whole-run cumulative on this segment too — see
    # the README's Q-009 evidence). The parser now prefers the
    # modelUsage-derived, basis-consistent figure on a mismatch and records
    # `cost_basis` — it no longer silently pins the inconsistent pair.
    "envelope-multiturn-cache.json": {
        "input_tokens": 37, "output_tokens": 446,
        "cache_read_input_tokens": 61525, "cache_creation_input_tokens": 15813,
        "total_cost_usd": 0.03161175, "cost_basis": "modelUsage",
        "num_turns": 2, "duration_ms": 4000,
        "is_error": False,
    },
    "envelope-is-error.json": {
        "input_tokens": 9, "output_tokens": 43,
        "cache_read_input_tokens": 18003, "cache_creation_input_tokens": 3408,
        "total_cost_usd": 0.0088403, "num_turns": 1, "duration_ms": 1150,
        "is_error": True,
    },
    # step-10 review-fix (AC-1): num_turns/duration_ms are now SUMMED across
    # every `type: "result"` element of the --verbose array (2 + 1 turns,
    # 4000 + 1176 ms) instead of taken from only the last segment, so they
    # share the same whole-run-cumulative basis as the modelUsage token
    # counts. The last element's own total_cost_usd (0.03161175) already
    # agrees with its modelUsage costUSD sum, so no cost_basis is recorded.
    "envelope-verbose-subagent.json": {
        "input_tokens": 37, "output_tokens": 446,
        "cache_read_input_tokens": 61525, "cache_creation_input_tokens": 15813,
        "total_cost_usd": 0.03161175, "num_turns": 3, "duration_ms": 5176,
        "is_error": False,
    },
}


def _assert_matches(result: dict, expected: dict) -> None:
    assert set(result.keys()) == set(expected.keys())
    for key, value in expected.items():
        if key == "total_cost_usd":
            assert result[key] == pytest.approx(value)
        else:
            assert result[key] == value


@pytest.mark.parametrize("fixture_name", sorted(_AC1_EXPECTED))
def test_parser_extracts_every_named_field_from_each_ac13_fixture(fixture_name):
    """AC-1: the parser extracts exactly the eight named fields from every
    AC-13 fixture. usage-source: modelUsage (README) — the four token
    fields come from `modelUsage`'s per-field sum, not the raw `usage`
    block; `num_turns`/`duration_ms`/`total_cost_usd`/`is_error` always
    come from the result element itself."""
    import runner
    text = fixture_text(fixture_name)
    result = runner._parse_envelope(text)
    _assert_matches(result, _AC1_EXPECTED[fixture_name])


# --- AC-1: an absent field is absent, never coerced to 0 -----------------------

_CAMEL = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}
_EIGHT_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_input_tokens",
    "cache_creation_input_tokens", "total_cost_usd", "num_turns",
    "duration_ms", "is_error",
)


def _drop_field(envelope: dict, field: str) -> dict:
    env = copy.deepcopy(envelope)
    if field in _CAMEL:
        camel = _CAMEL[field]
        for model_usage in (env.get("modelUsage") or {}).values():
            if isinstance(model_usage, dict):
                model_usage.pop(camel, None)
        usage = env.get("usage")
        if isinstance(usage, dict):
            usage.pop(field, None)
    else:
        env.pop(field, None)
    return env


@pytest.mark.parametrize("field", _EIGHT_FIELDS)
def test_field_absent_from_envelope_is_absent_from_result_not_zero(field):
    """AC-1: a field absent from the envelope is absent from the parsed
    result — never coerced to 0 — so a downstream writer can tell "not
    reported" from "reported as zero"."""
    import runner
    envelope = fixture_json("envelope-single.json")
    modified = _drop_field(envelope, field)
    result = runner._parse_envelope(json.dumps(modified))
    assert field not in result


# --- AC-2: the single-object and --verbose array forms agree ------------------

def test_single_object_and_verbose_array_forms_agree_on_usage_and_result_text(tmp_path):
    """AC-2: parsing the --verbose array form agrees with parsing its own
    last `type: "result"` element standalone on the token fields, cost and
    result text, and a ticketless `run_agent` whose fake dispatcher returns
    the array writes exactly that element's `result` text. (D-116,
    impl-plan.md: `envelope-multiturn-cache.json` is derived from the
    EARLIER of the two captured result elements, not the last one, so the
    comparison here extracts the array's actual last element directly
    rather than reusing that fixture file. step-10 review-fix, AC-1:
    `num_turns`/`duration_ms` deliberately do NOT agree between the two
    parses any more — the array form now sums them over every result
    element (whole-run basis), which a standalone parse of just the last
    element cannot know about; excluded from this comparison on purpose.)"""
    import runner
    verbose_text = fixture_text("envelope-verbose-subagent.json")
    verbose_array = json.loads(verbose_text)
    last_result = [
        m for m in verbose_array
        if isinstance(m, dict) and m.get("type") == "result"
    ][-1]

    array_result = runner._parse_envelope(verbose_text)
    standalone_result = runner._parse_envelope(json.dumps(last_result))
    shared_keys = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                  "cache_creation_input_tokens", "total_cost_usd", "is_error")
    for key in shared_keys:
        assert array_result[key] == standalone_result[key], key
    assert "cost_basis" not in array_result
    assert "cost_basis" not in standalone_result

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do the thing", encoding="utf-8")
    out_path = tmp_path / "out.md"
    with patch.dict(runner._DISPATCH,
                    {"anthropic": lambda *a, **k: (0, verbose_text, "")}):
        rc = runner.run_agent("build:work", prompt_path, out_path)
    assert rc == 0
    assert out_path.read_text(encoding="utf-8") == last_result["result"]


# --- AC-2: 15 hostile inputs never raise, always yield empty usage ------------
# (step-10 review-fix, AC-2: 4 of the original 19 cases — a single-model
# envelope with one malformed modelUsage field — no longer belong here; they
# now fall back to the raw usage block instead of failing closed. See
# test_single_model_malformed_modelusage_field_falls_back_to_the_raw_usage_block
# below.)

def _mutated(mutator) -> str:
    env = fixture_json("envelope-single.json")
    mutator(env)
    return json.dumps(env, allow_nan=True)


_HOSTILE_INPUTS = [
    pytest.param("just a plain reply, no JSON here", id="plain-text"),
    pytest.param("", id="empty"),
    pytest.param("   \n\t  ", id="whitespace-only"),
    pytest.param(fixture_text("envelope-single.json")
                [: len(fixture_text("envelope-single.json")) // 2],
                id="fixture-cut-in-half"),
    pytest.param("INFO: agent starting up\n" + fixture_text("envelope-single.json"),
                id="log-line-before-json"),
    pytest.param("null", id="top-level-null"),
    pytest.param('"just a string"', id="top-level-json-string"),
    pytest.param(json.dumps([{"type": "system"}, {"type": "assistant"}]),
                id="array-no-result-element"),
    pytest.param(json.dumps([1, 2, 3]), id="array-of-non-dicts"),
    pytest.param(_mutated(lambda e: e.__setitem__("usage", [1, 2, 3])),
                id="usage-as-list"),
    pytest.param(_mutated(lambda e: e.__setitem__("total_cost_usd", float("nan"))),
                id="cost-nan"),
    pytest.param(_mutated(lambda e: e.__setitem__("total_cost_usd", float("inf"))),
                id="cost-infinity"),
    pytest.param(_mutated(lambda e: e.__setitem__("is_error", "yes")),
                id="is-error-yes"),
    pytest.param("[" * 100_000 + "]" * 100_000, id="deeply-nested-brackets"),
    pytest.param('{"result": "abc\x01def"}', id="raw-control-character"),
]


@pytest.mark.parametrize("text", _HOSTILE_INPUTS)
def test_malformed_or_non_envelope_input_never_raises_and_yields_empty_usage(text):
    """AC-2: hostile stdout never raises out of the parser and always
    yields an empty usage mapping, so `run_agent` falls back to
    source="estimated"."""
    import runner
    assert runner._parse_envelope(text) == {}


# --- step-10 review-fix (AC-2, code-review MEDIUM + external MEDIUM): a ------
# --- malformed/inconsistent modelUsage falls back to the raw usage block ----

_SINGLE_MODEL_MALFORMED_FIELDS = [
    pytest.param(lambda e: e["modelUsage"]["claude-haiku-4-5-20251001"]
                .__setitem__("inputTokens", "9"), id="string-token-value"),
    pytest.param(lambda e: e["modelUsage"]["claude-haiku-4-5-20251001"]
                .__setitem__("inputTokens", True), id="bool-token-value"),
    pytest.param(lambda e: e["modelUsage"]["claude-haiku-4-5-20251001"]
                .__setitem__("inputTokens", -5), id="negative-count"),
    pytest.param(lambda e: e["modelUsage"]["claude-haiku-4-5-20251001"]
                .__setitem__("inputTokens", 9.5), id="float-count"),
]


@pytest.mark.parametrize("mutator", _SINGLE_MODEL_MALFORMED_FIELDS)
def test_single_model_malformed_modelusage_field_falls_back_to_the_raw_usage_block(mutator):
    """AC-2 (code-review MEDIUM + external MEDIUM): a malformed/mistyped
    modelUsage field on the (single) model makes the whole modelUsage block
    unusable, so the parser falls back to the raw `usage` block of the same
    element — recovering the FULL correct result — rather than failing the
    whole envelope closed. The raw `usage` block in envelope-single.json is
    untouched by these mutations, so the fallback is exact."""
    import runner
    text = _mutated(mutator)
    result = runner._parse_envelope(text)
    _assert_matches(result, _AC1_EXPECTED["envelope-single.json"])


def test_two_model_envelope_sums_correctly_when_both_models_are_well_formed():
    """AC-2: a genuine multi-model envelope sums a field across both models
    when both carry it as a valid count."""
    import runner
    env = fixture_json("envelope-single.json")
    env["modelUsage"]["second-model"] = {
        "inputTokens": 1, "outputTokens": 2,
        "cacheReadInputTokens": 3, "cacheCreationInputTokens": 4,
        "costUSD": 0.001,
    }
    result = runner._parse_envelope(json.dumps(env))
    assert result["input_tokens"] == 9 + 1
    assert result["output_tokens"] == 43 + 2
    assert result["cache_read_input_tokens"] == 18003 + 3
    assert result["cache_creation_input_tokens"] == 3408 + 4


def test_two_model_envelope_falls_back_to_usage_when_one_model_renames_a_field_never_a_partial_sum():
    """AC-2 (the exact code-review/external repro): a second model that
    renames `inputTokens` to the snake_case `input_tokens` must not silently
    drop that model's contribution from a partial sum — the whole
    modelUsage block becomes unusable and the parser falls back to the raw
    `usage` block instead, recovering the correct (un-inflated) numbers."""
    import runner
    env = fixture_json("envelope-single.json")
    env["modelUsage"]["second-model"] = {
        "input_tokens": 1000, "outputTokens": 500,
        "cacheReadInputTokens": 3, "cacheCreationInputTokens": 4,
        "costUSD": 0.001,
    }
    result = runner._parse_envelope(json.dumps(env))
    # Never a partial/undercounted sum (e.g. 9 alone, dropping the second
    # model's 1000) — the fallback recovers the exact single-model raw
    # usage values.
    _assert_matches(result, _AC1_EXPECTED["envelope-single.json"])


def test_empty_modelusage_falls_back_to_the_raw_usage_block():
    """AC-2: `modelUsage: {}` is treated the same as a malformed one — the
    parser falls back to the raw `usage` block."""
    import runner
    env = fixture_json("envelope-single.json")
    env["modelUsage"] = {}
    result = runner._parse_envelope(json.dumps(env))
    _assert_matches(result, _AC1_EXPECTED["envelope-single.json"])


def test_model_usage_totals_returns_none_for_inconsistent_or_empty_modelusage():
    """AC-2: `_model_usage_totals` itself (not just `_parse_envelope`)
    returns `None` — not a partial dict — for a two-model mismatch and for
    an empty modelUsage."""
    import runner
    single = fixture_json("envelope-single.json")

    mismatched = copy.deepcopy(single)
    mismatched["modelUsage"]["second-model"] = {"input_tokens": 1000}
    assert runner._model_usage_totals(mismatched) is None

    empty = copy.deepcopy(single)
    empty["modelUsage"] = {}
    assert runner._model_usage_totals(empty) is None


# --- step-10 review-fix (AC-1, code-review MEDIUM + external MEDIUM): -------
# --- num_turns/duration_ms summed across the array; cost basis consistency -

def test_num_turns_and_duration_ms_are_summed_across_every_result_element_of_the_verbose_array():
    """AC-1: num_turns/duration_ms are summed over EVERY `type: "result"`
    element of a --verbose array (2 + 1 = 3 turns, 4000 + 1176 = 5176 ms
    for the real captured fixture), sharing the same whole-run-cumulative
    basis as the modelUsage token counts — not just the last segment's."""
    import runner
    text = fixture_text("envelope-verbose-subagent.json")
    result = runner._parse_envelope(text)
    assert result["num_turns"] == 3
    assert result["duration_ms"] == 5176


def test_cost_usd_prefers_the_modelusage_sum_on_a_mismatch_and_records_cost_basis():
    """AC-1 (the exact code-review/external repro): when a result element's
    own `total_cost_usd` disagrees with the sum of its `modelUsage`
    costUSD, the parser prefers the modelUsage-derived figure (the same
    basis the token counts already use) and records `cost_basis` — it
    never silently keeps the point-in-time `total_cost_usd` next to
    whole-run-cumulative tokens."""
    import runner
    text = fixture_text("envelope-multiturn-cache.json")
    result = runner._parse_envelope(text)
    assert result["total_cost_usd"] == pytest.approx(0.03161175)
    assert result["cost_basis"] == "modelUsage"


def test_cost_usd_stays_the_top_level_figure_when_it_agrees_with_modelusage():
    """AC-1: pin — when the two bases already agree (the real single-turn
    fixture, no subagent), cost_usd is unchanged and no cost_basis note is
    added."""
    import runner
    text = fixture_text("envelope-single.json")
    result = runner._parse_envelope(text)
    assert result["total_cost_usd"] == pytest.approx(0.0088403)
    assert "cost_basis" not in result


def test_cost_usd_absent_from_the_envelope_stays_absent_even_when_modelusage_has_a_cost():
    """AC-1: pin — the "absent field stays absent" contract holds even for
    cost_usd: if the envelope carries no `total_cost_usd` at all, the
    parser does not invent one from modelUsage (there is nothing to
    cross-check against, so nothing to correct)."""
    import runner
    env = fixture_json("envelope-single.json")
    del env["total_cost_usd"]
    result = runner._parse_envelope(json.dumps(env))
    assert "total_cost_usd" not in result
    assert "cost_basis" not in result


# --- AC-2: a BOM prefix or non-ASCII/surrogate result never breaks usage ------

@pytest.mark.parametrize("build_text", [
    lambda: "﻿" + fixture_text("envelope-single.json"),
    lambda: json.dumps(dict(fixture_json("envelope-single.json"),
                            result="Привет, мир!")),
    lambda: json.dumps(dict(fixture_json("envelope-single.json"),
                            result="\ud800")),
], ids=["bom-prefixed", "cyrillic-result", "lone-surrogate-result"])
def test_bom_prefixed_and_non_ascii_envelopes_parse(build_text):
    """AC-2: a BOM prefix, or a non-ASCII or lone-surrogate `result` value,
    never breaks parsing of the surrounding envelope's usage."""
    import runner
    result = runner._parse_envelope(build_text())
    _assert_matches(result, _AC1_EXPECTED["envelope-single.json"])


# --- AC-2: the output split survives a hostile result value -------------------

_HOSTILE_RESULTS = [
    pytest.param('{"result": "\\ud800"}', True, id="surrogate"),
    pytest.param('{"result": 42}', False, id="int"),
    pytest.param('{"result": null}', False, id="null"),
    pytest.param('{"result": {"nested": true}}', False, id="object"),
]


@pytest.mark.parametrize("stdout_text,is_literal", _HOSTILE_RESULTS)
def test_run_agent_output_split_survives_hostile_result_values(
        tmp_path, stdout_text, is_literal):
    """AC-2: a hostile `result` value (surrogate/int/null/object) never
    raises out of run_agent's output split — the file holds the
    surrogate-replaced text when `result` is a string, or the raw stdout
    otherwise."""
    import runner
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do the thing", encoding="utf-8")
    out_path = tmp_path / "out.md"

    with patch.dict(runner._DISPATCH,
                    {"anthropic": lambda *a, **k: (0, stdout_text, "")}):
        rc = runner.run_agent("build:work", prompt_path, out_path)

    assert rc == 0
    written = out_path.read_text(encoding="utf-8", errors="surrogatepass")
    if is_literal:
        assert "\ud800" not in written  # replaced, never raised while writing
    else:
        assert written == stdout_text


# --- AC-2: the anthropic dispatcher decodes stdout as UTF-8 with replacement --

def test_anthropic_dispatcher_decodes_stdout_as_utf8_with_replacement(monkeypatch):
    """AC-2: the anthropic dispatcher decodes stdout as UTF-8 with
    replacement, so a hostile byte sequence never raises a
    UnicodeDecodeError. Nothing is launched — subprocess.run is faked."""
    import runner
    from models import ResolvedModel

    monkeypatch.setattr(runner.shutil, "which", lambda name: "/fake/claude")
    hostile = b"\xff" + fixture_text("envelope-single.json").encode("utf-8")
    captured = {}

    class _FakeCompleted:
        def __init__(self, stdout, stderr, returncode=0):
            self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

    def _fake_run(argv, input=None, capture_output=None, text=None,
                  timeout=None, env=None, encoding=None, errors=None):
        captured["encoding"], captured["errors"] = encoding, errors
        decoded = hostile.decode(encoding or "ascii", errors or "strict")
        return _FakeCompleted(decoded, "")

    monkeypatch.setattr(runner.subprocess, "run", _fake_run)

    resolved = ResolvedModel(role="coding", phase="build:work", track=None,
                            provider="anthropic", model="claude-haiku-4-5",
                            api_key_env=None, extra_args=[])
    rc, stdout, stderr = runner._dispatch_anthropic(resolved, "hi", 5, {})
    assert rc == 0
    assert captured["encoding"] == "utf-8"
    assert "�" in stdout


# --- usage-source constant and modelUsage summing ------------------------------

def test_usage_source_constant_matches_the_fixture_readme():
    """AC-2: `runner._USAGE_SOURCE` equals the README's `usage-source` finding."""
    import runner
    readme = fixture_text("README.md")
    line = next(l for l in readme.splitlines() if l.startswith("usage-source:"))
    expected = line.split(":", 1)[1].strip()
    assert runner._USAGE_SOURCE == expected


def test_model_usage_totals_sum_every_model_of_the_verbose_fixture():
    """AC-2: `_model_usage_totals` sums every model entry's fields — written
    as literals for the verbose fixture's last `result` element."""
    import runner
    verbose_array = fixture_json("envelope-verbose-subagent.json")
    last_result = [
        m for m in verbose_array
        if isinstance(m, dict) and m.get("type") == "result"
    ][-1]
    totals = runner._model_usage_totals(last_result)
    assert totals == {
        "input_tokens": 37, "output_tokens": 446,
        "cache_read_input_tokens": 61525, "cache_creation_input_tokens": 15813,
    }
