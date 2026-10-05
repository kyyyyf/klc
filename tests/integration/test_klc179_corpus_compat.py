"""KLC-179 step-5 (AC-3, AC-8): the REAL archived corpus still reads.

Every .klc/tickets/*/meta.json of this repo is copied, read-only, into a tmp
PROJECT_ROOT. Derivation and the rule table must succeed for each, `status --json`
renders a sample of ten (an XS and a cancelled ticket included) and the metrics
rollup completes.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
KLC = _FW / "scripts" / "klc"
sys.path.insert(0, str(_FW / "core" / "skills"))

import rules  # noqa: E402

REAL = _FW / ".klc" / "tickets"
# `.klc/` is git-ignored (ticket state lives on the klc-state branch), so a fresh clone has no
# corpus: the tests skip with a reason instead of failing or running over nothing.
pytestmark = pytest.mark.skipif(len(list(REAL.glob("*/meta.json"))) <= 20 if REAL.exists() else True,
                                reason=".klc/tickets (the real corpus) is not present in this checkout")


def _metas():
    return sorted(REAL.glob("*/meta.json"))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("corpus")
    for f in _metas():
        dst = root / ".klc" / "tickets" / f.parent.name
        dst.mkdir(parents=True)
        shutil.copyfile(f, dst / "meta.json")
    return root


def _klc(root, *args):
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    env.pop("KLC_TICKETS_DIR", None)
    return subprocess.run([sys.executable, str(KLC), *args], capture_output=True,
                          text=True, env=env)


def _num(key: str) -> int:
    tail = key.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def test_archived_tickets_derive_every_required_fact(corpus):
    """Not only `done`: without the terminal marker, every fact the lane requires holds."""
    checked = 0
    for f in sorted((corpus / ".klc" / "tickets").glob("*/meta.json")):
        meta = json.loads(f.read_text("utf-8"))
        if meta.get("phase") != "archived" or _num(f.parent.name) < 100:
            continue                                  # older tickets predate the history shape
        facts = {k: v for k, v in rules.derive_facts(meta).items() if k != "terminal"}
        lane = rules.lane_of(meta)
        required = rules.required_facts(facts, lane, risk_tags=meta.get("risk_tags"))
        missing = [n for n in required if not rules.holds(facts, n)]
        assert not missing, (f.parent.name, missing)
        checked += 1
    assert checked > 5


def test_derive_facts_and_next_move_succeed_for_every_ticket(corpus):
    for f in sorted((corpus / ".klc" / "tickets").glob("*/meta.json")):
        meta = json.loads(f.read_text("utf-8"))
        facts = rules.derive_facts(meta)
        move = rules.next_move(facts, rules.lane_of(meta), risk_tags=meta.get("risk_tags"))
        assert move.action, f.parent.name
        if meta.get("phase") in ("archived", "cancelled"):
            assert move.action == "done", f.parent.name


def _sample(corpus):
    metas = {f.parent.name: json.loads(f.read_text("utf-8"))
             for f in (corpus / ".klc" / "tickets").glob("*/meta.json")}
    xs = sorted(k for k, m in metas.items() if m.get("track") == "XS")[0]
    cancelled = sorted(k for k, m in metas.items() if m.get("phase") == "cancelled")[0]
    archived = [k for k, m in sorted(metas.items()) if m.get("phase") == "archived"
                and k not in (xs, cancelled)]
    return [xs, cancelled] + archived[:: max(1, len(archived) // 8)][:8]


def test_status_json_renders_for_a_sample_of_ten(corpus):
    sample = _sample(corpus)
    assert len(sample) == 10
    for key in sample:
        meta_path = corpus / ".klc" / "tickets" / key / "meta.json"
        before = hashlib.sha256(meta_path.read_bytes()).hexdigest()
        r = _klc(corpus, "status", key, "--json")
        assert r.returncode == 0, (key, r.stderr)
        out = json.loads(r.stdout)
        assert out["lane"] in ("light", "full") and out["next_move"]["action"] == "done", key
        assert isinstance(out["facts"], dict)
        text = _klc(corpus, "status", key)
        assert text.returncode == 0, (key, text.stderr)
        assert hashlib.sha256(meta_path.read_bytes()).hexdigest() == before   # read-only
    assert _klc(corpus, "status", sample[0], "--json").returncode == 0


def test_metrics_rollup_completes_on_the_corpus(corpus):
    r = _klc(corpus, "metrics", "--rollup")
    assert r.returncode == 0, r.stderr
    assert (corpus / ".klc" / "knowledge" / "process-metrics.json").exists()
