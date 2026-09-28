"""KLC-128 step-3 — AC-12: a malformed recorded range, a range pointing at
unreachable objects, or git itself being unavailable, must never raise out of
the integrate ack — it always completes with an unchanged verdict."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _merged_no_recording,
    _read_meta,
    _run_ack,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]

_OK_TRACE = {"status": "ok", "confidence": "medium", "mode": "deterministic",
            "degraded_inputs": [], "files_likely_to_edit": ["widgets/thing.py"],
            "files_to_read_first": [], "tests_to_read_or_run": [],
            "affected_modules_hint": ["widgets"]}

_FAKE_SHA_A = "a" * 40
_FAKE_SHA_B = "b" * 40


def test_malformed_pre_merge_range_missing_head_key_does_not_raise(tmp_path, monkeypatch):
    """AC-12, case 1/3: `pre_merge_range` present but missing the `head`
    field — the ack completes (`ok is True`, unchanged verdict), no
    exception propagates, and it degrades per AC-8's `none` shape."""
    ticket = "KLC-925"
    clone = _merged_no_recording(tmp_path, ticket)
    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": _FAKE_SHA_A,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    rc = _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1)
    assert rc == 0

    report = json.loads((tdir / "drift-report.json").read_text(encoding="utf-8"))
    assert report["ground_truth_source"] == "none"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["metrics"]["retrieval"]["ground_truth_source"] == "none"


def test_range_pointing_at_unreachable_objects_does_not_raise(tmp_path, monkeypatch):
    """AC-12, case 2/3: `pre_merge_range` holds syntactically valid 40-char
    shas that do not exist as objects in this repo at all (fabricated hex,
    never committed) — no exception, clean degrade."""
    ticket = "KLC-926"
    clone = _merged_no_recording(tmp_path, ticket)
    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": _FAKE_SHA_A, "head": _FAKE_SHA_B,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    rc = _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1)
    assert rc == 0

    report = json.loads((tdir / "drift-report.json").read_text(encoding="utf-8"))
    assert report["ground_truth_source"] == "none"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["metrics"]["retrieval"]["ground_truth_source"] == "none"


def test_git_binary_unavailable_does_not_raise(tmp_path, monkeypatch):
    """AC-12, case 3/3: the git-invocation seam raises for every call (the
    one fault-injected sub-case in this plan, since 'git is unavailable'
    cannot be reproduced by a real repo alone) — the integrate ack still
    completes cleanly with an unchanged verdict, never propagating."""
    ticket = "KLC-927"
    clone = _merged_no_recording(tmp_path, ticket)
    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": _FAKE_SHA_A, "head": _FAKE_SHA_B,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc

    def _raise(args, repo=None):
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(_pc, "_git", _raise)

    ok, _msg = _pc.can_complete(ticket, "integrate", persist=True)
    assert ok is True

    import lifecycle as _lc
    _lc.set_state(ticket, "integrate", "ack-needed", event="manual-completion", note="test")

    report = json.loads((tdir / "drift-report.json").read_text(encoding="utf-8"))
    assert report["ground_truth_source"] == "none"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["metrics"]["retrieval"]["ground_truth_source"] == "none"
