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


# --- budget loading ----------------------------------------------------------

def _load_budget_limits() -> tuple[dict[str, int], dict[str, int]]:
    """Return (soft_limits, hard_limits) from config/budgets.yml.

    Supports both the new soft_limits/hard_limits keys and the legacy
    prompt_input_limits key (treated as hard limit only).
    """
    try:
        import yaml
        from _paths import framework_root
        path = framework_root() / "config" / "budgets.yml"
        if not path.exists():
            return {}, {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        soft = {k: int(v) for k, v in (data.get("soft_limits") or {}).items()}
        hard = {k: int(v) for k, v in (data.get("hard_limits") or {}).items()}
        # legacy fallback
        if not hard and not soft:
            legacy = {k: int(v) for k, v in
                      (data.get("prompt_input_limits") or {}).items()}
            return {}, legacy
        return soft, hard
    except Exception:
        return {}, {}


# --- token telemetry helpers -------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars."""
    return max(1, len(text) // 4)


def _parse_usage_from_output(text: str) -> dict[str, int]:
    """Extract token counts from claude CLI JSON output if present.

    `claude --output-format json` embeds a usage block. Falls back to
    estimation when not available.
    """
    if not text.strip().startswith("{"):
        return {}
    try:
        payload = json.loads(text)
        usage = payload.get("usage") or {}
        result = {}
        if "input_tokens" in usage:
            result["tokens_in"] = int(usage["input_tokens"])
        if "output_tokens" in usage:
            result["tokens_out"] = int(usage["output_tokens"])
        if "cache_read_input_tokens" in usage:
            result["cache_hit"] = int(usage["cache_read_input_tokens"])
        return result
    except Exception:
        return {}


def _write_token_metrics(ticket: str | None, phase_id: str,
                         tokens_in: int, tokens_out: int,
                         cache_hit: int, source: str = "estimated") -> None:
    """Persist token counts into meta.json:metrics.tokens.<phase_id>.

    source: "provider" when parsed from real API usage block,
            "estimated" when derived from len(text)//4.
    cache_hit is always 0 for estimated source.
    """
    if not ticket:
        return
    try:
        from _paths import klc_ticket_meta_file
        meta_path = klc_ticket_meta_file(ticket)
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        metrics = meta.setdefault("metrics", {})
        tokens = metrics.setdefault("tokens", {})
        tokens[phase_id] = {
            "in":        tokens_in,
            "out":       tokens_out,
            "cache_hit": cache_hit if source == "provider" else 0,
            "source":    source,
        }
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass  # telemetry is non-fatal


# --- prompt composition ------------------------------------------------------

def _compose_prompt(prompt_path: Path,
                    inputs: dict[str, Path | str] | None) -> str:
    """Join the role prompt with labelled input blocks.

    `inputs` maps a human label ("diff", "spec", "context") to either
    a Path (contents inlined) or a string (used verbatim). Files are
    wrapped in triple-backtick fences so the LLM sees clear sections.
    """
    body: list[str] = [prompt_path.read_text(encoding="utf-8")]
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
    args_raw = os.environ.get("CLAUDE_ARGS", "--print")
    argv = [bin_name, *args_raw.split(), "--model", resolved.model,
            *resolved.extra_args]
    env = {**os.environ, **extra_env}
    try:
        r = subprocess.run(argv, input=prompt, capture_output=True,
                           text=True, timeout=timeout, env=env)
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
    return (0, text, "")


def _dispatch_ollama(resolved: ResolvedModel, prompt: str,
                     timeout: int, extra_env: dict[str, str]) -> tuple[int, str, str]:
    bin_name = os.environ.get("KLC_OLLAMA_CLI", "ollama")
    if not shutil.which(bin_name):
        return (2, "", f"runner: '{bin_name}' not on PATH (install ollama)")
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
              ) -> int:
    """Resolve, dispatch, write output. Returns 0 on success, non-zero
    on provider / dispatch failure (a synthetic CRITICAL partial is
    still written to out_path so pipelines can proceed).

    When `ticket` is provided, token usage is written to
    meta.json:metrics.tokens.<phase_id> after a successful run.
    """
    try:
        models = load_models()
        resolved = models.resolve(phase_id, track=track)
    except (FileNotFoundError, KeyError, ValueError) as e:
        _write_synthetic_critical(out_path, phase_id, str(e))
        return 2

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

    rc, stdout, stderr = dispatcher(resolved, prompt, timeout, extra_env)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if rc == 0 and stdout.strip():
        out_path.write_text(stdout, encoding="utf-8")
        # --- token telemetry -------------------------------------------------
        usage = _parse_usage_from_output(stdout)
        if usage:
            tokens_in  = usage.get("tokens_in",  _estimate_tokens(prompt))
            tokens_out = usage.get("tokens_out", _estimate_tokens(stdout))
            cache_hit  = usage.get("cache_hit",  0)
            source     = "provider"
        else:
            tokens_in  = _estimate_tokens(prompt)
            tokens_out = _estimate_tokens(stdout)
            cache_hit  = 0
            source     = "estimated"
        _write_token_metrics(ticket, phase_id, tokens_in, tokens_out,
                             cache_hit, source=source)
        return 0

    # Failure — preserve any partial stdout, append synthetic notice.
    detail = stderr.strip() or "(no stderr)"
    _write_synthetic_critical(out_path, phase_id, detail,
                              extra_body=stdout if stdout.strip() else "")
    return rc or 2


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
