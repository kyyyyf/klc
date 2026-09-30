#!/usr/bin/env python3
"""runner.py — generic LLM dispatcher.

Reads `config/models.yml` and dispatches an agent run to the configured
provider. Callers don't know or care which CLI / HTTP endpoint runs —
they pass a phase id (or role name) and a prompt path, receive the
agent's answer in a file.

Public API:

    run_agent(
        phase_id:    str,
        prompt_path: Path,
        inputs:      dict[str, Path | str] | None = None,
        out_path:    Path,
        *,
        track:       str | None = None,
        role:        str | None = None,
        timeout:     int = 1200,
    ) -> int

On success returns 0 and writes the agent's response to `out_path`.
On failure, writes a synthetic `[CRITICAL]` markdown partial so
review aggregation (and similar pipelines) can still proceed. Returns
the provider's exit code (non-zero).

Providers dispatched today:
  - anthropic  → `claude --print --no-conversation` on stdin (configurable
                  via CLAUDE_CLI / CLAUDE_ARGS env).
  - openai     → urllib POST to /v1/chat/completions.
  - ollama     → `ollama run <model>` on stdin.
  - google     → NotImplementedError (placeholder until upstream support).

All runs also receive the KLC_MODEL_* env vars from ResolvedModel.as_env()
so hook scripts can inspect them.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from models import load_models, ResolvedModel  # noqa: E402
from model_guard import check_subagent_dispatch, require_subagent_model  # noqa: E402
from budget_guard import (  # noqa: E402
    load_budget_limits as _load_budget_limits,
    estimate_tokens as _estimate_tokens,
    write_token_metrics as _write_token_metrics,
)
import phase_resolver as _phase_resolver  # noqa: E402
import plugin_gen  # noqa: E402


# Distinct from the generic dispatch-failure rc (2): this rc means the
# runner deliberately refused to dispatch — the phase is interactive
# and headless runs must park, never guess (C-005).
PARK_RC = 3


def _write_park_marker(ticket: str, phase_id: str, reason: str, out_path: Path) -> None:
    from _paths import klc_ticket_meta_file
    meta_path = klc_ticket_meta_file(ticket)
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["parked"] = {"phase": phase_id, "reason": reason}
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(f"[!PARKED] {reason}\n", encoding="utf-8")


# --- token telemetry helpers -------------------------------------------------

# KLC-133: the README's `usage-source` finding (tests/fixtures/klc133/README.md)
# — a subagent's tokens are missing from the final result's own `usage` block
# on this CLI version, so the four token fields are read from `modelUsage`'s
# per-field sum instead. `test_usage_source_constant_matches_the_fixture_readme`
# pins this constant to that finding.
_USAGE_SOURCE = "modelUsage"

_TOKEN_FIELDS = ("input_tokens", "output_tokens",
                 "cache_read_input_tokens", "cache_creation_input_tokens")

_MODEL_USAGE_CAMEL = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}


def _is_count(v) -> bool:
    """A valid non-negative token/turn count. `bool` is a `int` subclass in
    Python, so it is excluded explicitly — `True`/`False` are never counts."""
    return type(v) is int and v >= 0


def _is_cost(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v) and v >= 0


def _result_elements(text):
    """Every `type: "result"` element of a `--verbose` array, in array
    order; a one-element list holding the single object for the plain
    `--output-format json` form. `None` for anything that isn't a
    recognisable envelope at all — plain text, broken JSON, an array with
    no result element, or a non-string input."""
    if not isinstance(text, str):
        return None
    body = text.strip().removeprefix("﻿").strip()
    if not body or body[0] not in "{[":
        return None
    try:
        payload = json.loads(body)
    except Exception:                                   # incl. RecursionError
        return None
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        results = [item for item in payload
                  if isinstance(item, dict) and item.get("type") == "result"]
        return results or None
    return None


def _result_element(text):
    """The envelope object a headless run's stdout carries: the single JSON
    object of the plain `--output-format json` form, or the LAST element
    whose `type` is `"result"` of the `--verbose` array form (AC-2) — the
    one whose own `usage`/`total_cost_usd` the CLI reports for the final
    segment. `None` when `_result_elements` is."""
    els = _result_elements(text)
    return els[-1] if els else None


def _model_usage_totals(el):
    """Per-field sum over `el["modelUsage"]` (camelCase names as the CLI
    reports them).

    KLC-133 step-10 review-fix ([!DECISION D-118], AC-2, code-review MEDIUM
    + external MEDIUM): a field is summed only when EVERY model entry
    carries it as a valid count — a field missing, misnamed (e.g. schema
    drift renaming `inputTokens` to `input_tokens`) or invalid on even ONE
    model makes the WHOLE block unusable (`None`), never a partial or
    undercounted sum. An empty or malformed `modelUsage` is likewise
    unusable. The caller (`_parse_envelope`) then falls back to the raw
    `usage` block of the same element instead of losing real data."""
    mu = el.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return None
    models = list(mu.values())
    if any(not isinstance(m, dict) for m in models):
        return None
    out: dict = {}
    for key, camel in _MODEL_USAGE_CAMEL.items():
        vals = [m.get(camel) for m in models]
        if any(not _is_count(v) for v in vals):
            return None
        out[key] = sum(vals)
    return out


def _parse_envelope(text) -> dict:
    """AC-1/AC-2: the eight named fields of a well-formed headless envelope
    (`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
    `cache_creation_input_tokens`, `total_cost_usd`, `num_turns`,
    `duration_ms`, `is_error`), plus an optional `cost_basis` note, or an
    empty dict for anything malformed or absent. A field missing from the
    envelope is missing from the result — never coerced to 0. Total: never
    raises, for any input.

    KLC-133 step-10 review-fix ([!DECISION D-118], code-review MEDIUM ×2 +
    external MEDIUM ×2, AC-1/AC-2): widens D-117. The four token fields
    come from the LAST result element's `modelUsage` sum when every model
    entry there is internally consistent (`_model_usage_totals`);
    otherwise — modelUsage absent, empty, or inconsistent across models —
    the raw `usage` block of that SAME element is used instead. This is a
    genuine widening of D-117 ("absent" only): a *malformed* modelUsage now
    falls back too, rather than failing the whole envelope closed, because
    a perfectly good `usage` block is sitting right there and silently
    losing real data is worse than a needless total failure.

    `num_turns`/`duration_ms` are summed across EVERY result element of a
    `--verbose` array (a single-object envelope has just the one, so this
    is a no-op there) — the modelUsage token counts are already whole-run
    cumulative, so the turn/duration figures now share that same basis
    instead of silently reporting only the last segment's (the reviewers'
    real-fixture repro: a subagent run recording `num_turns: 1` next to a
    full-session token count).

    `total_cost_usd` is cross-checked against the modelUsage-derived cost
    sum when modelUsage was used as the token basis; on a mismatch the
    modelUsage figure is recorded instead (never silently the other) and
    `cost_basis` names why. A `total_cost_usd` that is genuinely ABSENT
    from the envelope stays absent — there is nothing to cross-check
    against, so nothing to correct (the AC-1 "absent stays absent"
    contract still holds).
    """
    try:
        els = _result_elements(text)
        if els is None:
            return {}
        el = els[-1]
        usage = el.get("usage", {})
        if not isinstance(usage, dict):
            return {}
        model_usage_used = False
        if _USAGE_SOURCE == "modelUsage":
            mu_totals = _model_usage_totals(el)
            if mu_totals is not None:
                usage = mu_totals
                model_usage_used = True
            # else: modelUsage absent/empty/inconsistent — fall back to the
            # raw `usage` dict already assigned above (D-118).
        out: dict = {}
        for key in _TOKEN_FIELDS:
            if key in usage:
                if not _is_count(usage[key]):
                    return {}
                out[key] = usage[key]
        for key in ("num_turns", "duration_ms"):
            raw_vals = [e[key] for e in els if key in e]
            if raw_vals:
                if any(not _is_count(v) for v in raw_vals):
                    return {}
                out[key] = sum(raw_vals)
        cost = None
        if "total_cost_usd" in el:
            if not _is_cost(el["total_cost_usd"]):
                return {}
            cost = el["total_cost_usd"]
        if model_usage_used and cost is not None:
            mu = el.get("modelUsage") or {}
            cost_vals = [m.get("costUSD") for m in mu.values() if isinstance(m, dict)]
            if cost_vals and all(_is_cost(v) for v in cost_vals):
                mu_cost = sum(cost_vals)
                if not math.isclose(mu_cost, cost, rel_tol=1e-6, abs_tol=1e-9):
                    cost = mu_cost
                    out["cost_basis"] = "modelUsage"
        if cost is not None:
            out["total_cost_usd"] = cost
        if "is_error" in el:
            if type(el["is_error"]) is not bool:
                return {}
            out["is_error"] = el["is_error"]
        return out
    except Exception:
        return {}


def _envelope_result_text(text):
    """The envelope's own `result` text, or `None` when there is none or it
    isn't a string (AC-2) — the caller then falls back to raw stdout."""
    el = _result_element(text)
    value = el.get("result") if el else None
    return value if isinstance(value, str) else None


def _parse_usage_from_output(text: str) -> dict[str, int]:
    """Extract token counts from claude CLI JSON output if present.

    A thin wrapper over `_parse_envelope` (AC-2) that keeps this function's
    pre-KLC-133 key names (`tokens_in`/`tokens_out`/`cache_hit`) for existing
    callers.
    """
    env = _parse_envelope(text)
    result: dict[str, int] = {}
    if "input_tokens" in env:
        result["tokens_in"] = env["input_tokens"]
    if "output_tokens" in env:
        result["tokens_out"] = env["output_tokens"]
    if "cache_read_input_tokens" in env:
        result["cache_hit"] = env["cache_read_input_tokens"]
    return result


# --- prompt composition ------------------------------------------------------

def _compose_prompt(prompt_path: Path,
                    inputs: dict[str, Path | str] | None) -> str:
    """Join the role prompt with labelled input blocks.

    `inputs` maps a human label ("diff", "spec", "context") to either
    a Path (contents inlined) or a string (used verbatim). Files are
    wrapped in triple-backtick fences so the LLM sees clear sections.

    KLC-127 AC-16: the prompt source may carry `{{include:...}}` directives
    (core/agents/*.md ships them unexpanded); the headless dispatch path
    goes straight from the raw source through this function, so it must
    expand them itself (`klc-plugin/agents/` regeneration is the in-client
    path's own expansion, done once ahead of time). Raises `ValueError`
    on an unresolvable include name — fail-closed, never ship a literal
    `{{include:...}}` line to a dispatched subagent.
    """
    body: list[str] = [plugin_gen.expand_includes(prompt_path.read_text(encoding="utf-8"))]
    if inputs:
        body.append("\n\n---\n\n## Inputs for this run\n")
        for label, value in inputs.items():
            body.append(f"\n### {label}\n")
            if isinstance(value, Path):
                try:
                    text = value.read_text(encoding="utf-8")
                except OSError:
                    body.append(f"_(missing: {value})_\n")
                    continue
                fence = "```" + ("diff" if label == "diff" else "")
                body.append(f"{fence}\n{text}\n```\n")
            else:
                body.append(f"```\n{value}\n```\n")
        body.append(
            "\n---\n\nProduce the output specified by the role prompt above. "
            "Do not emit anything else.\n"
        )
    return "".join(body)


# --- provider dispatchers ----------------------------------------------------

def _dispatch_anthropic(resolved: ResolvedModel, prompt: str,
                        timeout: int, extra_env: dict[str, str]) -> tuple[int, str, str]:
    bin_name = os.environ.get("CLAUDE_CLI", "claude")
    if not shutil.which(bin_name):
        return (2, "",
                f"runner: '{bin_name}' not on PATH (install Claude Code or "
                f"set CLAUDE_CLI)")
    # `claude --print` is the non-interactive, print-and-exit mode. We
    # intentionally don't pass --no-conversation (not a flag on all
    # versions of the CLI); override via CLAUDE_ARGS if your install
    # requires something different.
    args_raw = os.environ.get("CLAUDE_ARGS", "--print --output-format json")
    argv = [bin_name, *args_raw.split(), "--model", resolved.model,
            *resolved.extra_args]
    env = {**os.environ, **extra_env}
    try:
        r = subprocess.run(argv, input=prompt, capture_output=True,
                           text=True, timeout=timeout, env=env,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return (2, "", f"runner: '{bin_name}' timed out after {timeout}s")
    except OSError as e:
        return (2, "", f"runner: '{bin_name}' failed to launch: {e}")
    return (r.returncode, r.stdout, r.stderr)


def _dispatch_openai(resolved: ResolvedModel, prompt: str,
                     timeout: int, extra_env: dict[str, str]) -> tuple[int, str, str]:
    api_key_env = resolved.api_key_env or "OPENAI_API_KEY"
    key = os.environ.get(api_key_env)
    if not key:
        return (2, "", f"runner: ${api_key_env} is unset")
    url = "https://api.openai.com/v1/chat/completions"
    body = json.dumps({
        "model":    resolved.model,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return (e.code, "",
                f"runner: openai HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")
    except urllib.error.URLError as e:
        return (2, "", f"runner: openai network error: {e.reason}")
    except json.JSONDecodeError as e:
        return (2, "", f"runner: openai reply unparseable: {e}")
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return (2, "", f"runner: openai reply missing choices[0].message.content: "
                       f"{payload!r}")
    # Wrap in envelope so run_agent() can extract both result text and usage.
    usage = payload.get("usage") or {}
    if usage:
        envelope = json.dumps({
            "result": text,
            "usage": {
                "input_tokens":  usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        })
        return (0, envelope, "")
    return (0, text, "")


def _dispatch_ollama(resolved: ResolvedModel, prompt: str,
                     timeout: int, extra_env: dict[str, str]) -> tuple[int, str, str]:
    bin_name = os.environ.get("KLC_OLLAMA_CLI", "ollama")
    if not shutil.which(bin_name):
        # Graceful fallback to local-coding role (Anthropic Haiku) so XS
        # tickets don't break on machines without a local model.
        # Uses resolve_role() directly — not coupled to the 'indexing' pseudo-phase.
        sys.stderr.write(
            f"runner: '{bin_name}' not on PATH — falling back to local-coding "
            f"(set KLC_OLLAMA_CLI or install ollama to use local model)\n"
        )
        try:
            fallback = load_models().resolve_role("local-coding")
            return _dispatch_anthropic(fallback, prompt, timeout, extra_env)
        except Exception as exc:
            return (2, "", f"runner: ollama absent and fallback failed: {exc}")
    argv = [bin_name, "run", resolved.model, *resolved.extra_args]
    env = {**os.environ, **extra_env}
    try:
        r = subprocess.run(argv, input=prompt, capture_output=True,
                           text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return (2, "", f"runner: '{bin_name}' timed out after {timeout}s")
    except OSError as e:
        return (2, "", f"runner: '{bin_name}' failed to launch: {e}")
    return (r.returncode, r.stdout, r.stderr)


def _dispatch_google(resolved: ResolvedModel, prompt: str,
                     timeout: int, extra_env: dict[str, str]) -> tuple[int, str, str]:
    return (2, "",
            "runner: 'google' provider is not implemented yet. "
            "Use anthropic / openai / ollama, or wire a custom runner.")


_DISPATCH = {
    "anthropic": _dispatch_anthropic,
    "openai":    _dispatch_openai,
    "ollama":    _dispatch_ollama,
    "google":    _dispatch_google,
}


# --- entry point -------------------------------------------------------------

def run_agent(phase_id: str,
              prompt_path: Path,
              out_path: Path,
              *,
              inputs:  dict[str, Path | str] | None = None,
              track:   str | None = None,
              ticket:  str | None = None,
              timeout: int = 1200,
              telemetry_ticket: str | None = None,
              telemetry_phase: str | None = None,
              reviewer: str | None = None,
              step: int | None = None,
              run_pass: str | None = None,
              card_bytes: int | None = None,
              ) -> int:
    """Resolve, dispatch, write output. Returns 0 on success, non-zero
    on provider / dispatch failure (a synthetic CRITICAL partial is
    still written to out_path so pipelines can proceed).

    When `ticket` is provided, token usage is written to
    meta.json:metrics.tokens.<phase_id> after a successful run.

    When `ticket` is provided and the phase resolves as interactive
    (clarify gate / human ack-pick), this refuses to dispatch and
    parks instead — headless runs never guess at interactive input
    (C-005). Returns PARK_RC in that case.

    KLC-133 AC-3: `telemetry_ticket`/`telemetry_phase` are keyword-only and
    SEPARATE from `ticket`/`phase_id` — they name where the attempt is
    RECORDED (defaulting to `ticket`/`phase_id` when unset), while `ticket`
    alone still governs the C-005 park guard above. This lets a caller like
    the ticketless indexing agents of `scripts/init.py` pass neither and
    record nothing, or a caller like the review runner pass only the
    telemetry tags (never triggering the park guard, which keys on `ticket`)
    on top of its own dispatch. `reviewer`/`step`/`run_pass` are copied onto
    the attempt verbatim; `card_bytes` is the caller's rendered artefact size
    for the `estimated` fallback (AC-3/AC-4, `_record_run` below). Exactly
    one attempt is written per dispatch whenever a telemetry ticket ends up
    known — a provider attempt when the envelope parses (AC-1's
    `input_tokens`/`output_tokens` both present, D-104), else `estimated`; a
    failed dispatch (non-zero rc, or `is_error: true` inside a parseable
    envelope) that still has usage is recorded with `failed: true`; a failed
    dispatch with no usable envelope records nothing (AC-4).
    """
    if ticket:
        try:
            resolved_phase = _phase_resolver.resolve_phase(ticket, phase_id)
        except (FileNotFoundError, KeyError, ValueError):
            resolved_phase = None
        if resolved_phase and resolved_phase.interactive:
            _write_park_marker(
                ticket, phase_id,
                "interactive phase — headless parks (C-005)",
                out_path,
            )
            return PARK_RC

    try:
        models = load_models()
        resolved = models.resolve(phase_id, track=track)
    except (FileNotFoundError, KeyError, ValueError) as e:
        _write_synthetic_critical(out_path, phase_id, str(e))
        return 2

    require_subagent_model(resolved)
    note = check_subagent_dispatch(resolved)
    if note:
        sys.stderr.write(f"runner: {note}\n")

    if not prompt_path.exists():
        msg = f"runner: prompt file missing: {prompt_path}"
        _write_synthetic_critical(out_path, phase_id, msg)
        return 2

    prompt = _compose_prompt(prompt_path, inputs)

    # --- budget guard --------------------------------------------------------
    soft_limits, hard_limits = _load_budget_limits()
    if track:
        estimated = _estimate_tokens(prompt)
        hard = hard_limits.get(track)
        soft = soft_limits.get(track)
        if hard and estimated > hard:
            msg = (
                f"[!QUESTION] context too large: estimated ~{estimated} tokens "
                f"exceeds {track} hard limit of {hard}. "
                f"Reduce inputs or upgrade track."
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(msg + "\n", encoding="utf-8")
            sys.stderr.write(
                f"runner: hard limit exceeded for {phase_id} "
                f"(~{estimated} > {hard} tokens for {track}) — aborted\n"
            )
            return 2
        elif soft and estimated > soft:
            sys.stderr.write(
                f"runner: soft limit warning for {phase_id} "
                f"(~{estimated} > {soft} soft tokens for {track}) — proceeding\n"
            )

    extra_env = resolved.as_env()

    dispatcher = _DISPATCH.get(resolved.provider)
    if dispatcher is None:
        msg = f"runner: no dispatcher for provider {resolved.provider!r}"
        _write_synthetic_critical(out_path, phase_id, msg)
        return 2

    # KLC-133 AC-3: where the one attempt of this dispatch is recorded.
    tags = {"reviewer": reviewer, "step": step, "run_pass": run_pass}
    rec_ticket = telemetry_ticket or ticket
    rec_phase = telemetry_phase or phase_id

    rc, stdout, stderr = dispatcher(resolved, prompt, timeout, extra_env)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if rc == 0 and stdout.strip():
        # --- envelope split (AC-C1 / KLC-133 AC-2) ---------------------------
        # If the provider returns a JSON envelope (e.g. --output-format json,
        # single object or --verbose array), write only the result text to
        # the artifact. Fall back to raw stdout when parsing fails, the
        # envelope has no 'result' key, or 'result' isn't a string (never
        # raises — a hostile result value is written as raw stdout instead).
        text = _envelope_result_text(stdout)
        out_path.write_text(stdout if text is None else text,
                            encoding="utf-8", errors="replace")
        _record_run(rec_ticket, rec_phase, prompt, stdout,
                    failed=False, card_bytes=card_bytes, tags=tags)
        return 0

    # Failure — preserve any partial stdout, append synthetic notice.
    detail = stderr.strip() or "(no stderr)"
    _write_synthetic_critical(out_path, phase_id, detail,
                              extra_body=stdout if stdout.strip() else "")
    _record_run(rec_ticket, rec_phase, prompt, stdout,
                failed=True, card_bytes=card_bytes, tags=tags)
    return rc or 2


def _record_run(ticket, phase, prompt, stdout, *, failed, card_bytes, tags) -> None:
    """KLC-133 AC-3/AC-4: the one attempt of a dispatch — never raises
    (C-003), so a telemetry-write failure never changes `run_agent`'s rc or
    output. A provider attempt requires BOTH `input_tokens` and
    `output_tokens` to parse (D-104); it is recorded with `failed: true`
    when the dispatch itself failed OR the envelope's own `is_error` is
    `true`. An `estimated` attempt is recorded only on an otherwise
    successful dispatch — a failed dispatch with no usable envelope records
    nothing at all.

    KLC-133 step-10 review-fix (AC-4, code-review LOW + external LOW): the
    `is_error` flag is now folded into the RECORDED `failed` value for
    BOTH branches, computed once — not only inside the provider branch's
    own `failed=` value as before. The branch GATE below (whether to write
    an `estimated` attempt at all) still keys on the caller's own `failed`
    (did the dispatch itself return non-zero?), unchanged — a genuinely
    failed dispatch with no usable envelope still records nothing. But
    when the dispatch itself succeeded (rc==0) and the envelope reports
    `is_error: true` with no usable input_tokens/output_tokens, the
    `estimated` attempt that DOES get written is now marked `failed: true`
    too, so it never wrongly counts toward `review_llm_passes_per_ticket`
    as an executed, successful pass."""
    if not ticket:
        return
    try:
        env = _parse_envelope(stdout)
        combined_failed = failed or env.get("is_error") is True
        if "input_tokens" in env and "output_tokens" in env:          # D-104
            _write_token_metrics(
                ticket, phase, env["input_tokens"], env["output_tokens"],
                env.get("cache_read_input_tokens", 0), source="provider",
                cache_write=env.get("cache_creation_input_tokens"),
                cost_usd=env.get("total_cost_usd"),
                cost_basis=env.get("cost_basis"),
                num_turns=env.get("num_turns"), duration_ms=env.get("duration_ms"),
                failed=combined_failed, **tags)
        elif not failed:
            _write_token_metrics(
                ticket, phase, _estimate_tokens(prompt), _estimate_tokens(stdout), 0,
                source="estimated", card_bytes=card_bytes,
                failed=True if combined_failed else None, **tags)
    except Exception:
        pass


def _write_synthetic_critical(out_path: Path,
                              phase_id: str,
                              detail: str,
                              extra_body: str = "") -> None:
    """Emit a markdown partial that review aggregation will count as
    ISSUES_TOTAL=1 ISSUES_BLOCKING=1, so the calling pipeline still
    surfaces the error instead of producing an empty file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        f"## Agent run failed — {phase_id}",
        "",
        f"### [CRITICAL] runner dispatch failed",
        f"**Issue**: {detail}",
        "**Fix**: inspect logs, verify API key / CLI availability, or switch "
        "provider in `config/models.yml`.",
        "",
    ]
    if extra_body:
        parts.extend(["### Partial output", "", extra_body, ""])
    parts.append("ISSUES_TOTAL=1 ISSUES_BLOCKING=1")
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


# --- CLI ---------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run an agent via the configured model.")
    ap.add_argument("--phase", required=True,
                    help="Phase id from config/phases.yml (also accepts "
                         "'indexing' or 'review-external').")
    ap.add_argument("--prompt", required=True, type=Path,
                    help="Path to the role prompt (markdown).")
    ap.add_argument("--out", required=True, type=Path,
                    help="Where to write the agent's response.")
    ap.add_argument("--input", action="append", default=[],
                    help="label=path (repeatable). Files inlined into prompt.")
    ap.add_argument("--track", default=None, choices=("XS", "S", "M", "L"))
    ap.add_argument("--ticket", default=None,
                    help="Ticket key for token telemetry (e.g. KLC-016).")
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args(argv)

    inputs: dict[str, Path | str] = {}
    for entry in args.input:
        if "=" not in entry:
            sys.stderr.write(f"runner: --input expects label=path, got {entry!r}\n")
            return 2
        label, _, path = entry.partition("=")
        inputs[label.strip()] = Path(path.strip())

    return run_agent(args.phase, args.prompt, args.out,
                     inputs=inputs, track=args.track, ticket=args.ticket,
                     timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
