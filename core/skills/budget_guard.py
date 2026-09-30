#!/usr/bin/env python3
"""budget_guard.py — prompt-size budget helpers, shared by runner.py and
the orchestrator (KLC-052).

Moved out of runner.py verbatim (behavior preserved) so an advisory,
non-dispatching check (`check_prompt_budget`) can be reused by the
orchestrator loop before it even attempts a dispatch, instead of only
being enforced inline inside `run_agent`.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path


# --- budget loading ------------------------------------------------------------

def load_budget_limits() -> tuple[dict[str, int], dict[str, int]]:
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


# --- token telemetry helpers ----------------------------------------------------

def estimate_tokens_from_bytes(n: int) -> int:
    """The ONE size-to-token divisor (KLC-119 D-006), for a caller that
    already has a measured byte count (e.g. a file's on-disk size) rather
    than text in memory. `estimate_tokens` below delegates here — a
    caller with bytes in hand must call THIS, never re-derive `// 4`
    locally (KLC-120 review-fix MEDIUM: scripts/review-runner.py used to)."""
    return max(1, n // 4)


def estimate_tokens(text: str) -> int:
    """The ONE size-to-token rule (KLC-119 D-006): 1 token ~ 4 UTF-8 bytes.

    Pinned to bytes rather than characters (Q-005): `card_bytes` is already
    recorded in bytes and the two units differ by under 1.1% on real cards
    (spec F-014), so a single rule removes the ambiguity rather than keeping
    two numbers that mostly agree.
    """
    return estimate_tokens_from_bytes(len(text.encode("utf-8")))


def _new_attempt_id() -> str:
    """12 hex chars from uuid4 — distinct even for two attempts recorded in
    the same second (AC-2). A backfilled attempt uses a deterministic digest
    instead (see token_backfill.py, D-004)."""
    return uuid.uuid4().hex[:12]


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ATTEMPT_OPTIONAL_KEYS = ("run_pass", "cache_write", "cost_usd", "cost_basis",
                        "num_turns", "duration_ms", "failed")
_MEASURED_KEYS = ("cache_write", "cost_usd", "cost_basis", "num_turns", "duration_ms")


def attempt_record(tokens_in: int, tokens_out: int, cache_hit: int,
                   source: str, card_bytes: int | None,
                   step: int | None = None, attempt_id: str | None = None,
                   ts: str | None = None, reviewer: str | None = None, *,
                   run_pass: str | None = None,
                   cache_write: int | None = None,
                   cost_usd: float | None = None,
                   cost_basis: str | None = None,
                   num_turns: int | None = None,
                   duration_ms: int | None = None,
                   failed: bool | None = None) -> dict:
    """One attempt record — the unit `write_token_metrics` appends (AC-2/AC-3).
    The identifier is always assigned here (by the writer), never left to the
    caller, so two callers can never collide on one (D-004).

    reviewer: KLC-120 AC-3 — the reviewer name for an executed review pass.
            Absent (never null) when the caller doesn't pass one, so every
            pre-KLC-120 caller's records stay byte-identical (Q-005).

    KLC-133 AC-8: `run_pass`, `cache_write`, `cost_usd`, `num_turns`,
            `duration_ms` and `failed` are keyword-only and stored only when
            the caller passes them. `cache_write`/`cost_usd`/`cost_basis`/
            `num_turns`/`duration_ms` — the "measured" keys — are additionally
            dropped on any non-"provider" attempt, even when a caller passes
            them by mistake, so a rollup can trust `source == "provider"` as
            the one gate for "this attempt carries measured fields" (Q-003).

    KLC-133 step-10 review-fix ([!DECISION D-118], AC-1): `cost_basis` is an
            optional note — present (e.g. `"modelUsage"`) only when
            `runner._parse_envelope` corrected `cost_usd` to the
            modelUsage-derived, basis-consistent figure because it disagreed
            with the envelope's own `total_cost_usd`; absent otherwise, same
            provider-only gate as the other measured keys."""
    rec = {"id": attempt_id or _new_attempt_id(),
           "ts": ts or _utc_now(),
           "in": tokens_in, "out": tokens_out,
           "cache_hit": cache_hit if source == "provider" else 0,
           "source": source}
    if card_bytes is not None:
        rec["card_bytes"] = card_bytes
    if step is not None:
        rec["step"] = step
    if reviewer:
        rec["reviewer"] = reviewer
    if run_pass:
        rec["run_pass"] = run_pass
    if source == "provider":
        for key, value in zip(
                _MEASURED_KEYS,
                (cache_write, cost_usd, cost_basis, num_turns, duration_ms)):
            if value is not None:
                rec[key] = value
    if failed is True:
        rec["failed"] = True
    return rec


def _as_attempt(raw: dict, legacy: bool = False) -> dict:
    rec = dict(raw)
    rec.setdefault("id", "legacy")
    rec["legacy"] = legacy
    return rec


def normalize_attempts(entry) -> dict:
    """AC-14 / D-207: the ONE tolerant reader. Never raises, never silently
    discards data, for ANY shape found on disk — the corpus has survived
    several migrations and some of it is hand-edited.

    Returns ``{"attempts": [...], "legacy": <raw prior value or None>,
    "warnings": [...]}`` for every input shape:
      - absent/empty                    -> empty attempts, no warning;
      - a bare pre-KLC-119 record        -> one legacy attempt;
      - the current ``{"attempts": [...], "legacy": ...}`` shape -> read as-is,
        with any non-dict item in ``attempts`` skipped (warned, not raised);
      - anything else (a bare list, a string, a number) -> empty attempts,
        the raw value preserved under ``legacy``, and one warning string.
    """
    if not entry:
        return {"attempts": [], "legacy": None, "warnings": []}
    if not isinstance(entry, dict):
        return {"attempts": [], "legacy": entry,
                "warnings": [f"metrics.tokens entry is a {type(entry).__name__},"
                             f" not a record — degraded to zero attempts"]}
    raw = entry.get("attempts")
    if raw is None:                       # pre-KLC-119 single record
        return {"attempts": [_as_attempt(entry, legacy=True)],
                "legacy": entry, "warnings": []}
    if not isinstance(raw, list):
        return {"attempts": [], "legacy": entry,
                "warnings": ["metrics.tokens.attempts is not a list"]}
    out, warns = [], []
    prior = entry.get("legacy")
    if isinstance(prior, dict):
        out.append(_as_attempt(prior, legacy=True))
    elif prior is not None:
        warns.append("metrics.tokens.legacy is not a record — kept, not counted")
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        else:
            warns.append("a non-record entry in metrics.tokens.attempts was skipped")
    return {"attempts": out, "legacy": prior, "warnings": warns}


def _read_meta(ticket: str) -> dict:
    from _paths import klc_ticket_meta_file
    meta_path = klc_ticket_meta_file(ticket)
    if not meta_path.exists():
        raise FileNotFoundError(str(meta_path))
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    from _paths import klc_ticket_meta_file
    meta_path = klc_ticket_meta_file(ticket)
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _append_into_meta(ticket: str, phase_id: str, rec: dict) -> None:
    """The step-1 body: append *rec* straight into
    ``meta.json:metrics.tokens.<phase_id>.attempts``. Called only when a
    transaction is open for *ticket* (``token_journal.tx_open``) — otherwise
    ``write_token_metrics`` buffers the attempt in the journal instead
    (KLC-119 step-2, ADR-004 point 2)."""
    meta = _read_meta(ticket)
    tokens = meta.setdefault("metrics", {}).setdefault("tokens", {})
    entry = tokens.get(phase_id)
    if not isinstance(entry, dict) or "attempts" not in entry:
        prior = entry if isinstance(entry, dict) and entry else None
        entry = {"attempts": []}
        if prior is not None:              # first touch: keep the old record
            entry["legacy"] = prior
    if (rec.get("card_bytes") is None and rec.get("source") != "provider"
            and entry["attempts"]):
        carried = entry["attempts"][-1].get("card_bytes")
        if carried is not None:
            rec = dict(rec, card_bytes=carried)
    entry["attempts"].append(rec)
    tokens[phase_id] = entry
    _write_meta(ticket, meta)


def write_token_metrics(ticket: str | None, phase_id: str,
                         tokens_in: int, tokens_out: int,
                         cache_hit: int, source: str = "estimated",
                         card_bytes: int | None = None, *,
                         step: int | None = None,
                         attempt_id: str | None = None,
                         reviewer: str | None = None,
                         ts: str | None = None,
                         run_pass: str | None = None,
                         cache_write: int | None = None,
                         cost_usd: float | None = None,
                         cost_basis: str | None = None,
                         num_turns: int | None = None,
                         duration_ms: int | None = None,
                         failed: bool | None = None) -> None:
    """The single writer (AC-1) of ``meta.json:metrics.tokens.<phase_id>``.

    KLC-119: appends an attempt record to an ordered per-phase attempts list
    (AC-2) instead of replacing a single record. The pre-KLC-119 "never
    downgrade a provider record" rule (KLC-118 AC-5) becomes structurally
    true — appending cannot overwrite an existing attempt (AC-3) — so this
    function no longer needs to inspect the prior record's source before
    writing.

    KLC-119 step-2 (ADR-004 point 2): the writer is transaction-aware. When
    a `state_tx` is open for *ticket* the attempt is appended directly into
    `meta.json`, exactly as before; when none is open the attempt is
    buffered in the ticket's derived journal (`token_journal`) instead, and
    the next `state_tx` for that ticket drains it — so a telemetry write
    NEVER modifies a tracked file outside an open transaction (AC-4/AC-5).

    source: "provider" (real API usage), "signal" (the completion signal's
            own usage block) or "estimated" (derived from the rendered
            artefact's measured size). cache_hit is always 0 unless
            source == "provider".
    card_bytes: the rendered artefact's measured byte size. When omitted,
            carries forward the phase's last-known card size so a caller
            that only has token counts doesn't drop it.
    step: the build-step number, when this attempt belongs to `build`.
    attempt_id: an explicit id (used by the backfill for idempotency,
            D-004); the writer assigns one otherwise.
    reviewer: KLC-120 AC-3 — optional, keyword-only. Every existing caller
            stays source-compatible (none of them passes it).
    ts: KLC-133 AC-9 — optional, keyword-only. Used by the journal drain to
            preserve the ORIGINAL attempt time rather than re-stamping "now"
            (options F-104); every other caller leaves it unset and gets
            `_utc_now()` exactly as before.
    run_pass, cache_write, cost_usd, cost_basis, num_turns, duration_ms, failed:
            KLC-133 AC-8 — optional, keyword-only; forwarded verbatim to
            `attempt_record` (see its docstring for the storage rules).
    """
    if not ticket:
        return
    rec = attempt_record(tokens_in, tokens_out, cache_hit, source, card_bytes,
                         step=step, attempt_id=attempt_id, ts=ts,
                         reviewer=reviewer, run_pass=run_pass,
                         cache_write=cache_write, cost_usd=cost_usd,
                         cost_basis=cost_basis, num_turns=num_turns,
                         duration_ms=duration_ms, failed=failed)
    try:
        import token_journal
        if token_journal.tx_open(ticket):
            _append_into_meta(ticket, phase_id, rec)
        else:
            token_journal.append(ticket, dict(rec, phase=phase_id))
    except Exception:
        pass  # telemetry is never fatal


# --- AC-1 single-writer scan -----------------------------------------------

_TOKENS_WRITE_RE = re.compile(
    r'metrics(?:\[["\']tokens["\']\]|\.setdefault\(\s*["\']tokens["\'])'
    r'|\btokens\s*\[[^\]]+\]\s*=(?!=)'
)

_SELF_FILE = Path(__file__).resolve()


def find_second_writers(root: Path, exclude: set[Path] | None = None) -> list[Path]:
    """AC-1: scan `core/` and `klc-plugin/` under *root* for any module OTHER
    than this one that assigns into a `tokens` dict under `metrics` — the
    single-writer invariant. A heuristic source scan (not a full AST walk),
    matching a `metrics["tokens"]`/`metrics.setdefault("tokens", ...)` site or
    a `tokens[...] = ` assignment; `budget_guard.py` itself (the one legitimate
    writer) is always excluded.
    """
    root = Path(root)
    exclude = {p.resolve() for p in (exclude or set())}
    exclude.add(_SELF_FILE)
    hits: list[Path] = []
    for base in (root / "core", root / "klc-plugin"):
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if py.resolve() in exclude:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _TOKENS_WRITE_RE.search(text):
                hits.append(py)
    return hits


# --- AC-7 single-estimator scan ---------------------------------------------

_SIZE_TO_TOKEN_RE = re.compile(r'//\s*4\b')


def find_second_estimators(root: Path, exclude: set[Path] | None = None) -> list[Path]:
    """AC-7: scan `core/` AND `scripts/` under *root* for a second
    size-to-token rule. `estimate_tokens`/`estimate_tokens_from_bytes`
    (this module) are the ONE functions permitted to convert a measured
    size into a token count; any other `// 4` integer-division site is a
    competing rule (D-006 deletes the one that used to live in
    `artefacts._record_card_metrics`; KLC-120 review-fix MEDIUM widened
    the scan to `scripts/` after `scripts/review-runner.py` grew its own
    hand-rolled copy)."""
    root = Path(root)
    exclude = {p.resolve() for p in (exclude or set())}
    exclude.add(_SELF_FILE)
    hits: list[Path] = []
    for base in (root / "core", root / "scripts"):
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if py.resolve() in exclude:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _SIZE_TO_TOKEN_RE.search(text):
                hits.append(py)
    return hits


# --- advisory budget check (KLC-052) --------------------------------------------

@dataclass
class BudgetVerdict:
    hard_breach: bool
    soft_breach: bool
    estimated:   int
    limit:       int | None


def check_prompt_budget(track: str, estimated: int) -> BudgetVerdict:
    """Advisory check: does `estimated` tokens breach the soft/hard
    limit for `track`? Does not dispatch or write anything — callers
    (e.g. the orchestrator) decide what to do with the verdict."""
    soft_limits, hard_limits = load_budget_limits()
    hard = hard_limits.get(track)
    soft = soft_limits.get(track)
    return BudgetVerdict(
        hard_breach=bool(hard and estimated > hard),
        soft_breach=bool(soft and estimated > soft),
        estimated=estimated,
        limit=hard,
    )


# --- AC-9 fail-closed dispatch gate (/klc:run) ------------------------------

def gate_card_dispatch(track: str, est_tokens: int | None) -> BudgetVerdict:
    """AC-9: the callable the `/klc:run` prose calls (C-006). No estimate is
    NOT zero — it is a hard breach, so a card that failed to render (or
    whose estimate is otherwise unavailable) can never be dispatched past
    the gate. When an estimate IS available this is exactly
    `check_prompt_budget`."""
    if est_tokens is None:
        _soft_limits, hard_limits = load_budget_limits()
        return BudgetVerdict(hard_breach=True, soft_breach=True,
                             estimated=-1, limit=hard_limits.get(track))
    return check_prompt_budget(track, est_tokens)


# --- AC-8 / KLC-133 AC-11 calibration statement -----------------------------

def _total_input(a: dict) -> int:
    """KLC-133 AC-11/Q-003: a provider attempt's REAL total input — the
    uncached `in` plus whatever the cache read/wrote — vs. an `estimated`
    attempt's `in`, which measures the whole card. Only genuine `int`
    values count (a hand-edited corpus's stray string/bool/float is
    silently excluded, never raises)."""
    return sum(v for v in (a.get("in"), a.get("cache_hit"), a.get("cache_write"))
              if type(v) is int)


def calibration_statement(by_phase: dict[str, list[dict]]) -> str:
    """AC-8/KLC-133 AC-11: the estimator's calibration status, derived from
    the corpus — never a hardcoded claim. No second size rule is needed
    here: an `estimated` attempt already carries the number
    `estimate_tokens` produced, so the ratio is attempt over attempt, phase
    by phase, using each phase's LAST non-failed provider-sourced attempt
    and LAST estimated attempt. KLC-133 fixes F-012: the provider side of
    the ratio is the attempt's TOTAL input (in + cache_hit + cache_write),
    not the uncached `in` alone, and a failed provider attempt is skipped.
    """
    pairs = []
    for _phase, attempts in by_phase.items():
        actual = [a for a in attempts
                 if a.get("source") == "provider"
                 and a.get("failed") is not True
                 and _total_input(a) > 0]
        est = [a for a in attempts
              if a.get("source") == "estimated"
              and type(a.get("in")) is int and a["in"] > 0]
        if actual and est:
            pairs.append(est[-1]["in"] / _total_input(actual[-1]))
    if not pairs:
        return "uncalibrated: no provider-sourced attempts in the corpus"
    return (f"estimated in / provider total input (in + cache_hit + cache_write) = "
            f"{sum(pairs) / len(pairs):.2f} over {len(pairs)} provider-paired phases")
