#!/usr/bin/env python3
"""KLC-120 step-1 — AC-3: each executed review pass appends exactly one
`metrics.tokens.<phase>.attempts[]` record carrying a `reviewer` field
through `budget_guard.write_token_metrics`, the tag survives the journal
drain (D-007), and a caller that omits `reviewer=` never gains the key
(Q-005 regression guard).

Other AC-1/AC-2/AC-9 rows for this file are added in step-3 (the review
planner itself); this step only wires the attempt writer.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))

import budget_guard  # noqa: E402
import metrics  # noqa: E402
import models as models_mod  # noqa: E402
import review as rv  # noqa: E402
import review_cascade  # noqa: E402
import review_plan  # noqa: E402
import state_feature  # noqa: E402
import state_tx as state_tx_mod  # noqa: E402
import token_journal  # noqa: E402


def _load_review_runner():
    """`scripts/review-runner.py` cannot be `import`ed by a dotted module
    name (the file has a hyphen) — load it via `spec_from_file_location`,
    as the impl-plan's RED bullet requires."""
    spec = importlib.util.spec_from_file_location(
        "klc120_review_runner", FW_ROOT / "scripts" / "review-runner.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _seed_ticket(tmp_path: Path, ticket: str, *, track: str = "M") -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")
    return tdir


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


def test_executed_pass_appends_one_reviewer_tagged_attempt(tmp_path, monkeypatch):
    """AC-3 (test-plan row): three executed headless passes each append
    exactly one reviewer-tagged attempt through the one writer, so the
    count of reviewer-tagged records equals the count of executed passes."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed_ticket(tmp_path, "KLC-990")
    rr = _load_review_runner()

    def _fake_run_agent(*, phase_id, prompt_path, out_path, inputs, track):
        out_path.write_text("partial output\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(rr, "run_agent", _fake_run_agent)

    calls: list[dict] = []
    real_write = budget_guard.write_token_metrics

    def _spy(*args, **kwargs):
        calls.append(kwargs)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(budget_guard, "write_token_metrics", _spy)

    reviewers = ["security", "architecture", "performance"]
    for name in reviewers:
        card = _write_card(tmp_path, name, tdir / "spec.md")
        partial = tmp_path / f"{name}.partial.md"
        rc = rr.main([str(card), str(partial)])
        assert rc == 0

    assert len(calls) == 3, "one write_token_metrics call per executed pass"
    assert all("reviewer" in kw for kw in calls), \
        "every call must carry a reviewer keyword"
    assert {kw["reviewer"] for kw in calls} == set(reviewers)

    meta = json.loads((tdir / "meta.json").read_text())
    tagged = [rec for _phase, rec in metrics.iter_attempts(meta, "KLC-990")
              if rec.get("reviewer")]
    assert len(tagged) == 3, \
        "the count of reviewer-tagged records must equal the count of " \
        "executed passes (AC-3)"


def test_failed_dispatch_appends_no_reviewer_tagged_attempt(tmp_path, monkeypatch):
    """Regression pin (impl-plan D-017): a failed dispatch (rc != 0) never
    appends a reviewer-tagged attempt. This already held before this step's
    GREEN, because review-runner.py called run_agent without ticket= at all
    (F-011) — the pin proves the new write path stays outcome-gated too."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed_ticket(tmp_path, "KLC-991")
    rr = _load_review_runner()

    def _failing_run_agent(*, phase_id, prompt_path, out_path, inputs, track):
        return 1

    monkeypatch.setattr(rr, "run_agent", _failing_run_agent)

    card = _write_card(tmp_path, "drift", tdir / "spec.md")
    partial = tmp_path / "drift.partial.md"
    rc = rr.main([str(card), str(partial)])
    assert rc == 1

    meta = json.loads((tdir / "meta.json").read_text())
    tagged = [rec for _phase, rec in metrics.iter_attempts(meta, "KLC-991")
              if rec.get("reviewer")]
    assert tagged == []


def test_drained_journal_attempt_keeps_reviewer_field(tmp_path, monkeypatch):
    """D-007: a reviewer-tagged attempt buffered in the journal (written
    with no open state_tx) keeps its `reviewer` field once a later state_tx
    drains it into meta.json — without this, `_drain_journal` would drop
    the field on its fixed-field replay (F-020)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed_ticket(tmp_path, "KLC-992")
    monkeypatch.setattr(state_feature, "enabled", lambda: False)

    token_journal.append("KLC-992", {
        "id": "att-rev-1", "ts": "2026-01-01T00:00:00Z",
        "in": 10, "out": 2, "cache_hit": 0, "source": "estimated",
        "card_bytes": 40, "phase": "review", "reviewer": "drift",
    })

    with state_tx_mod.state_tx("KLC-992", "drain test"):
        pass

    stored = json.loads((tdir / "meta.json").read_text())
    attempts = stored["metrics"]["tokens"]["review"]["attempts"]
    tagged = [a for a in attempts if a.get("id") == "att-rev-1"]
    assert len(tagged) == 1
    assert tagged[0].get("reviewer") == "drift", \
        "the reviewer field must survive the journal drain (D-007)"


def test_write_token_metrics_without_reviewer_adds_no_reviewer_key(tmp_path, monkeypatch):
    """Q-005 regression guard (impl-plan D-017 pin): a caller that does not
    pass `reviewer=` — e.g. `klc step`'s task_brief write
    (core/phases/task_brief.py:52) — must never gain a `reviewer` key,
    absent rather than null, so every existing caller of
    write_token_metrics stays untouched."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_ticket(tmp_path, "KLC-994")

    budget_guard.write_token_metrics(
        "KLC-994", "build", 10, 2, 0, source="estimated", card_bytes=40)

    meta_path = tmp_path / ".klc" / "tickets" / "KLC-994" / "meta.json"
    meta = json.loads(meta_path.read_text())
    attempts = [rec for _phase, rec in metrics.iter_attempts(meta, "KLC-994")]
    assert len(attempts) == 1
    assert "reviewer" not in attempts[0]


# --------------------------------------------------------------------------- #
# step-3 — AC-1/AC-2/AC-9: the review plan itself, on both paths.
# --------------------------------------------------------------------------- #

def _seed_project(tmp_path: Path, *, track: str = "M",
                  extra_meta: dict | None = None) -> tuple[Path, Path]:
    """A real `.klc/config/profile.yml` naming `generic` (A-001) plus a
    real KLC-990 ticket dir holding spec.md + meta.json. Returns
    (project_root, spec_path)."""
    project_root = tmp_path / "proj"
    (project_root / ".klc" / "config").mkdir(parents=True)
    (project_root / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    tdir = project_root / ".klc" / "tickets" / "KLC-990"
    tdir.mkdir(parents=True)
    meta = {
        "ticket": "KLC-990", "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if extra_meta:
        meta.update(extra_meta)
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    spec_path = tdir / "spec.md"
    spec_path.write_text("# spec\n", encoding="utf-8")
    return project_root, spec_path


def _write_diff(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _stub_claude_on_path(tmp_path: Path, monkeypatch) -> None:
    """Prepend a fake executable `claude` to PATH — never replace PATH
    outright, so git/python stay resolvable for review.py's own
    subprocess calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def _make_decide(use_full_review: bool, reason: str, tier: str):
    def _decide(ticket, diff_path):
        return review_cascade.CascadeDecision(
            use_full_review=use_full_review, reason=reason, tier=tier)
    return _decide


_HARMLESS_DIFF = (
    "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+docs update\n"
)


def test_review_plan_written_at_documented_path_with_required_fields(
        tmp_path, monkeypatch):
    """AC-1 (test-plan row): the plan is written at the documented path
    with every required top-level and per-pass field."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    monkeypatch.setattr(review_cascade, "decide",
                        _make_decide(True, "core files touched", "core"))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan_path = project_root / ".klc" / "tickets" / "KLC-990" / "review-plan.json"
    assert plan_path.is_file()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for key in ("ticket", "track", "diff_sha256", "cap", "override", "passes"):
        assert key in plan, f"missing top-level field {key!r}"
    assert plan["ticket"] == "KLC-990"
    assert plan["track"] == "M"
    assert isinstance(plan["passes"], list) and plan["passes"]
    for p in plan["passes"]:
        for field in ("reviewer", "source", "selected_by", "provider",
                      "model", "status"):
            assert field in p, f"pass entry missing {field!r}: {p}"


def test_review_plan_lists_manifest_always_reviewers_as_skipped_with_reason(
        tmp_path, monkeypatch):
    """AC-1/D-005: the four profiles/generic/manifest.yml `reviewers.always`
    entries appear with status skipped and the documented reason on the
    client path — never omitted."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    always_names = {"security", "architecture", "performance", "test-coverage"}
    seen = {p["reviewer"]: p for p in plan["passes"] if p["reviewer"] in always_names}
    assert set(seen) == always_names
    for name, p in seen.items():
        assert p["status"] == "skipped", f"{name} should be skipped on the client path"
        assert p["skip_reason"] == review_plan.PROFILE_SKIP


def test_review_plan_carries_per_step_build_review_not_counted_field(
        tmp_path, monkeypatch):
    """AC-1/Q-006: the fixed per_step_build_review field is always
    present, stating per-step build review is outside this inventory."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    assert plan["per_step_build_review"] == "not counted"


def test_planner_never_dispatches_a_model_call(tmp_path, monkeypatch):
    """AC-2: the planner's whole enumeration completes without dispatching
    any model call — verified by a fake REVIEW_RUNNER that raises (writes
    a marker) if reached."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()

    marker = tmp_path / "dispatched.marker"
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('dispatched', encoding='utf-8')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVIEW_RUNNER", str(fake_runner))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0
    assert not marker.exists(), "the planner must never dispatch a model call"

    plan_file = project_root / ".klc" / "tickets" / "KLC-990" / "review-plan.json"
    assert plan_file.is_file()
    job_cards = list((project_root / ".klc" / "reports").glob("pending-*/job-*.md"))
    assert job_cards == [], "no job card must be written under --plan-only"


def test_external_plan_entry_and_job_card_name_resolved_model_with_no_api_key_env_set(
        tmp_path, monkeypatch):
    """AC-9: with neither ANTHROPIC_API_KEY nor OPENAI_API_KEY set, the
    external entry of review-plan.json and job-external.md both name the
    resolved provider and model."""
    project_root, spec_path = _seed_project(tmp_path, track="S")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    monkeypatch.setattr(review_cascade, "decide",
                        _make_decide(False, "peripheral, no sentinel hits", "peripheral"))

    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "partial = Path(sys.argv[2])\n"
        "partial.write_text('## PASS\\nno findings\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVIEW_RUNNER", str(fake_runner))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path)])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    ext_entry = next(p for p in plan["passes"] if p["reviewer"] == "external")
    assert ext_entry["provider"] == "anthropic"
    assert ext_entry["model"]

    ext_cards = list((project_root / ".klc" / "reports").glob("pending-*/job-external.md"))
    assert len(ext_cards) == 1
    card_text = ext_cards[0].read_text(encoding="utf-8")
    assert "Provider: anthropic" in card_text
    assert f"Model:    {ext_entry['model']}" in card_text


def test_unevaluable_conditional_trigger_is_planned_with_reason(tmp_path, monkeypatch):
    """C-004: fail-closed stays — a conditional trigger the planner cannot
    evaluate is planned anyway, with a reason naming the failure, rather
    than treated as "no risk"."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated unreadable modules.json")

    monkeypatch.setattr(rv, "_evaluate_conditional_trigger", _boom)
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    deep_impact = next(p for p in plan["passes"] if p["reviewer"] == "deep-impact")
    assert deep_impact["status"] == "planned"
    assert "could not be evaluated" in deep_impact["selected_by"]


def test_plan_diff_sha256_matches_partials_diff_sha256(tmp_path, monkeypatch):
    """Edge case: diff_sha256 in review-plan.json is computed with the same
    hash routine already used for partials/diff.sha256."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    partials_dirs = sorted((project_root / ".klc" / "reports").glob("partials-*"))
    assert partials_dirs
    sha_file = partials_dirs[-1] / "diff.sha256"
    assert sha_file.is_file()
    assert plan["diff_sha256"] == sha_file.read_text(encoding="utf-8").strip()


def test_headless_plan_plans_manifest_reviewers_and_skips_in_client_passes(
        tmp_path, monkeypatch):
    """Edge case: a headless run (no --plan-only) plans the manifest
    reviewers.always entries (full path) and marks the two in-client-only
    passes (code-review, drift) as skipped with the CLIENT_ONLY reason.
    Track L (cap 6, step-4 D-012): this diff plans exactly 6 passes (four
    manifest-always, deep-impact and external), which sits AT the cap, not
    over it — this test is about pass categorization, not the cap."""
    project_root, spec_path = _seed_project(tmp_path, track="L")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    monkeypatch.setattr(review_cascade, "decide",
                        _make_decide(True, "core files touched", "core"))
    diff_path = _write_diff(
        tmp_path, "diff.patch",
        "--- a/core/skills/foo.py\n+++ b/core/skills/foo.py\n"
        "@@ -1 +1 @@\n-old\n+def bar():\n+    pass\n")

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path)])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    assert plan["path"] == "headless"
    always_names = {"security", "architecture", "performance", "test-coverage"}
    for p in plan["passes"]:
        if p["reviewer"] in always_names:
            assert p["status"] == "planned", p
        if p["reviewer"] in ("code-review", "drift"):
            assert p["status"] == "skipped"
            assert p["skip_reason"] == review_plan.CLIENT_ONLY


def test_conditional_pass_skipped_by_track_gate_labels_the_reason(tmp_path, monkeypatch):
    """KLC-120 review-fix MEDIUM: a conditional pass skipped because the
    ticket's track is not in its enabled_for_tracks is labelled "track <T>
    not in enabled_for_tracks", not the generic "no trigger fired" (which
    stays reserved for a genuinely non-matching pattern) — deep-impact's
    real manifest entry is enabled_for_tracks: [S, M, L], so an XS ticket
    is track-gated regardless of the diff."""
    project_root, spec_path = _seed_project(tmp_path, track="XS")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    deep_impact = next(p for p in plan["passes"] if p["reviewer"] == "deep-impact")
    assert deep_impact["status"] == "skipped"
    assert deep_impact["skip_reason"] == "track XS not in enabled_for_tracks"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
