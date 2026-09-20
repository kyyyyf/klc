"""index_coverage.py — the ONE shared coverage-verdict module (KLC-106).

Every index builder accepts an external tool's output the moment the process
exits 0 and the JSON parses; there is no check that the output actually
covers the project, so an empty graph and a correct graph are
indistinguishable to the code that consumes them. This module is the one
place that answers "did my output actually cover the code?", as a ratio
against a file universe. It never knows a language name, a tool name or a
file extension: a builder supplies its own two numbers (an observed count
and a universe count) and its own scope label, and this module does the
arithmetic (AC-1).

The threshold is a settings knob (AC-2), resolved through
``settings.index_coverage_threshold``. The denominator prefers a KLC-105
file-universe artifact when one is passed and falls back to
``structural.json`` otherwise (AC-3, A-001) — as of this ticket no separate
universe artifact is published on disk (KLC-105 folded the universe into
``structural.json`` itself), so ``universe_artifact`` is always ``None`` in
practice today; the parameter exists so a future publish is a one-line
caller change, not a signature change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import settings  # noqa: E402

DEFAULT_THRESHOLD = 0.25
DEFAULT_LANGUAGE_SHARE_THRESHOLD = 0.05
NOT_APPLICABLE = "not-applicable"

_VERDICT_ARTIFACTS = ("depgraph.json", "inventory.json", "module_edges.json",
                       "symbol_usage.json", "test_map.json")


def load_json_or_none(path) -> dict | None:
    """Tolerant read for an OPTIONAL artifact (D-203): absent, unreadable or
    malformed all read as None. Every read this ticket adds is optional
    evidence, and evidence that is missing must degrade the output, never
    end the process."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _coerce_ratio(value, default):
    """Shared yaml-string-ratio coercion (KLC-123): core/shared/yaml.py's
    minimal parser has no float literal (KLC-106 build-time finding, not in
    the design), so a bare `0.4` scalar comes back as the STRING "0.4", not a
    float. Tolerate that shape here rather than widen the shared parser,
    which is out of this ticket's affected set. Used by every ratio-shaped
    settings knob in this module, so the quirk is handled once."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def threshold_for(builder: str) -> float:
    """Coverage floor for *builder*: per-builder override, then the shared
    default, then the built-in — resolved through the settings ladder
    (AC-2). The built-in lives HERE, in one place, so no builder carries a
    hard-coded number."""
    return _coerce_ratio(settings.index_coverage_threshold(builder), DEFAULT_THRESHOLD)


def language_share_threshold() -> float:
    """The dominant-language floor (KLC-123 AC-9): the share of the code
    universe a language must reach, in the absence of any live candidate
    files, for its own degradation to still cap confidence. Same settings
    ladder and yaml-string-ratio coercion as `threshold_for`."""
    return _coerce_ratio(settings.index_coverage_language_share_threshold(),
                          DEFAULT_LANGUAGE_SHARE_THRESHOLD)


def inventory_language_verdicts(inventory) -> dict:
    """Every per-language coverage verdict recorded in `inventory.json`'s
    `errors[]` (KLC-106 AC-7 / `deterministic_inventory.inventory_coverage_verdicts`),
    keyed by language. Returns `{}` for an old-shape inventory (no
    `inventory:<lang>` entries at all) or a non-dict input — tolerant read,
    never a crash (KLC-123 AC-5)."""
    out = {}
    if not isinstance(inventory, dict):
        return out
    for e in inventory.get("errors") or []:
        if isinstance(e, dict) and isinstance(e.get("builder"), str) \
                and e["builder"].startswith("inventory:"):
            out[e["builder"].split(":", 1)[1]] = e
    return out


def language_shares(per_lang: dict) -> dict:
    """Each language's share of the code universe covered by *per_lang*'s
    own `universe` counts. A missing/malformed `universe` degrades that
    language's contribution to `0` (fail-closed: never a ZeroDivisionError,
    never `None` propagating into a comparison — KLC-123 edge case)."""
    denom = sum((v.get("universe") or 0) for v in per_lang.values())
    if denom <= 0:
        return {}
    return {lang: (v.get("universe") or 0) / denom for lang, v in per_lang.items()}


def dominant_languages(per_lang: dict, floor=None) -> set:
    """Languages at or above the dominant-share floor (KLC-123 AC-4) — the
    fallback relevance set used when a trace has no candidate files of its
    own to scope by."""
    bar = language_share_threshold() if floor is None else floor
    return {lang for lang, share in language_shares(per_lang).items() if share >= bar}


def scoped_inventory_degradation(inventory, candidate_languages, share_threshold=None):
    """The language-scoped decision (KLC-123 AC-2..AC-5) that replaces
    feeding the WHOLE inventory artifact into `degraded_inputs`: a language's
    degraded verdict caps only when that language is relevant to this trace
    — one of its own candidate languages, or, when none are known, one of
    the repo's dominant languages by share of the code universe. A degraded
    language outside that relevance set surfaces as an additive advisory
    (naming itself and its share) instead of capping.

    Returns `(degraded, advisories, scoped)`. `scoped=False` means the
    inventory carries no per-language verdicts at all (an old-shape
    artifact) — the caller must fall back to the unchanged
    `artifact_degraded(inventory)` check (AC-5)."""
    per_lang = inventory_language_verdicts(inventory)
    if not per_lang:
        return False, [], False
    relevant = set(candidate_languages) or dominant_languages(per_lang, share_threshold)
    shares = language_shares(per_lang)
    floor = language_share_threshold() if share_threshold is None else share_threshold
    degraded = False
    notes = []
    for lang in sorted(per_lang):
        v = per_lang[lang]
        if not v.get("degraded"):
            continue
        if lang in relevant:
            degraded = True
        else:
            notes.append(
                f"inventory.json: language '{lang}' uncovered "
                f"(share {shares.get(lang, 0.0):.1%} of the code universe, "
                f"below index.coverage.language_share_threshold {floor:.0%} "
                f"— not capped)")
    return degraded, notes, True


def universe_for(scope, structural, universe_artifact=None):
    """The denominator (AC-3). Prefers a KLC-105 file-universe artifact when
    present, else ``structural.json`` — one accessor, so the switch is a
    one-line change.

    scope=None    -> the whole project (a language-agnostic builder):
                     total_files.
    scope="<key>" -> that scope's file count.
    Returns None when the scope carries no file count at all (a producer
    whose nodes are not files -> metric not-applicable, D-002) and 0 when
    the denominator source itself is absent (fail closed: unmeasurable is
    never healthy)."""
    source = universe_artifact or structural
    if not source:
        return 0
    if scope is None:
        total = source.get("total_files")
        return int(total) if isinstance(total, int) else 0
    entry = (source.get("languages") or {}).get(scope)
    if not isinstance(entry, dict):
        return None
    count = entry.get("files")
    return int(count) if isinstance(count, int) else None


def verdict(builder, artifact, observed, universe, *, metric,
            threshold=None, reason=""):
    """The one verdict record every builder records (AC-1). Pure arithmetic
    over two integers: nothing here knows a language, a tool or a file
    extension."""
    floor = threshold_for(builder) if threshold is None else float(threshold)
    base = {"builder": builder, "artifact": artifact, "observed": observed,
             "threshold": floor}
    if metric == NOT_APPLICABLE or universe is None:
        return {**base, "metric": NOT_APPLICABLE, "universe": None, "ratio": None,
                "degraded": False,
                "reason": reason or "no file denominator for this producer"}
    if universe <= 0:
        return {**base, "metric": metric, "universe": universe, "ratio": None,
                "degraded": True,
                "reason": reason or "denominator unavailable — coverage unmeasurable"}
    ratio = round(observed / universe, 4)
    degraded = ratio < floor
    return {**base, "metric": metric, "universe": universe, "ratio": ratio,
            "degraded": degraded,
            "reason": reason or (
                f"{metric} {ratio} below threshold {floor} "
                f"({observed}/{universe})" if degraded else
                f"{metric} {ratio} at or above threshold {floor} "
                f"({observed}/{universe})")}


def artifact_degraded(artifact, nested_keys=("import_graphs", "package_graphs")):
    """Tolerant reader (A-004): an artifact written before KLC-106 has no
    ``degraded`` key at all and must read as NOT degraded, never as a
    KeyError and never as True. Also scans the per-entry flags of a nested
    mapping, because dep_graph stamps its verdict per producer entry rather
    than at the top level."""
    if not isinstance(artifact, dict):
        return False
    if artifact.get("degraded") is True:
        return True
    # A flat errors[] entry (inventory.json, callgraph/<lang>.json — no
    # per-language nesting to stamp a top-level flag onto) can itself carry
    # a verdict dict; widened here rather than a second reader, so every
    # consumer of this one function stays honest about both artifact shapes.
    for entry in (artifact.get("errors") or []):
        if isinstance(entry, dict) and entry.get("degraded") is True:
            return True
    for key in nested_keys:
        for entry in (artifact.get(key) or {}).values():
            if isinstance(entry, dict) and entry.get("degraded") is True:
                return True
    return False


def callgraph_degraded_input(callgraph, other_evidence_found: bool) -> bool:
    """AC-8/D-212: the ONE rule for whether an absent-or-unusable callgraph
    counts as a degraded input, used identically by test_map, module_edges
    and symbol_usage (the three AC-8 consumers).

    Bare ABSENCE of a callgraph is NEVER, by itself, degradation: neither
    the ``init`` nor the ``update`` entry-point script ever invokes a
    callgraph builder (Q-103) — that is the default and ONLY state a plain
    init/update run ever reaches. Flagging bare absence unconditionally forces
    ``confidence: low`` on every ordinary index forever, which is the exact
    over-claim AC-10 exists to prevent, just inverted (KLC-106 review round 1,
    HIGH finding #1).

    A callgraph that IS present but unusable — it self-reports
    ``degraded: true`` (via ``artifact_degraded``), or its own ``symbols``
    table is present and empty — is a real, concrete upstream degradation and
    always counts, regardless of whether some other evidence exists. That is
    the "a callgraph was expected" half of the rule: something ran and came
    back empty, which is worth naming.

    When the callgraph is simply absent (nothing ran, nothing expected),
    it counts only when the consumer's own OTHER evidence also came up
    empty (``other_evidence_found=False``) — the "genuinely vacuous given
    the available inputs" case, where a callgraph might have been the only
    thing that could have helped.
    """
    if callgraph is not None:
        if artifact_degraded(callgraph):
            return True
        symbols = callgraph.get("symbols") if isinstance(callgraph, dict) else None
        if isinstance(symbols, dict) and not symbols:
            return True
        return False
    return not other_evidence_found


def degraded_inputs(candidates):
    """Names of the inputs a consumer cannot trust. Each candidate is
    ``(name, artifact, vacuous)``: the flag fires on an upstream degrade,
    ``vacuous`` fires when the artifact is present and healthy but empty of
    the evidence THIS consumer needs. Two distinct triggers, one list,
    deterministically ordered."""
    out = []
    for name, artifact, vacuous in candidates:
        if artifact_degraded(artifact) or vacuous:
            out.append(name)
    return sorted(dict.fromkeys(out))


def collect_verdicts(index_dir):
    """Every persisted verdict, harvested from the artifacts' own
    ``errors[]``. This is the DERIVED aggregate (D-001): no ``index_health.json``
    is written, so the per-artifact verdicts stay the single authority."""
    index_dir = Path(index_dir)
    found = []
    for name in _VERDICT_ARTIFACTS:
        data = load_json_or_none(index_dir / name) or {}
        for entry in (data.get("errors") or []):
            if isinstance(entry, dict) and "ratio" in entry and "builder" in entry:
                found.append(entry)
    callgraph_dir = index_dir / "callgraph"
    if callgraph_dir.is_dir():
        for path in sorted(callgraph_dir.glob("*.json")):
            data = load_json_or_none(path) or {}
            found.extend(e for e in (data.get("errors") or [])
                         if isinstance(e, dict) and "ratio" in e and "builder" in e)
    return sorted(found, key=lambda v: (v.get("builder", ""), v.get("artifact", "")))


def format_summary(verdict_record):
    """One operator-readable line per builder — printed on EVERY run
    (AC-14), so a healthy index is visibly healthy rather than merely
    silent."""
    v = verdict_record
    return (f"  index coverage: {v['builder']} [{v['artifact']}] {v['metric']}="
            f"{v['observed']}/{v['universe']} ratio={v['ratio']} "
            f"degraded={str(v['degraded']).lower()}")


def render_error(entry) -> str:
    """The single formatter for a heterogeneous ``errors[]`` entry (D-003):
    a pre-existing human-readable string is returned verbatim, a verdict
    dict is rendered through ``format_summary`` (minus the leading indent) so
    it never reaches an operator as a Python dict repr."""
    if isinstance(entry, dict):
        return format_summary(entry).strip()
    return str(entry)
