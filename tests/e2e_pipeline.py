#!/usr/bin/env python3
"""e2e_pipeline.py — E2E test harness for klc lifecycle.

Tests a complete ticket journey through all phases using fake agents
that produce canned artefacts. Validates state transitions, artefact
generation, and ack logic per config/phases.yml.

Usage:
    python tests/e2e_pipeline.py              # all tracks
    python tests/e2e_pipeline.py --track S    # single track
    python tests/e2e_pipeline.py --keep       # preserve temp dir
    python tests/e2e_pipeline.py --negative   # run negative tests only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Framework and fixture paths
FW_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = FW_ROOT / "tests" / "fixtures" / "fake-agent-outputs"

# Add skills to path so we can load phases.yml
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _load_track_phases(track: str) -> list[str]:
    """Return ordered phase ids for track, as declared in phases.yml."""
    import phases as _ph
    ph = _ph.load_phases()
    return [p.id for p in ph.track_phases(track)]


def _load_phase_outputs() -> dict[str, list[str]]:
    """Return {phase_id: [output_paths]} from phases.yml."""
    import phases as _ph
    ph = _ph.load_phases()
    return {p.id: list(p.outputs) for p in ph.ordered}


# Fixture file → target artefact name mapping.
# Keys are names under tests/fixtures/fake-agent-outputs/
_FIXTURE_MAP: dict[str, list[tuple[str, str]]] = {
    "discovery":           [("discovery.md", "spec.md")],
    "acceptance-test-plan": [("acceptance-test-plan.md", "test-plan.md")],
    "design":              [("design.md", "design/options.md"),
                            ("impl-plan.md", "impl-plan.md")],
    "detailed-test-plan":  [("detailed-test-plan.md", "test-plan.md")],
    "build":               [("build.md", "build-log.md"),
                            ("impl-plan.md", "impl-plan.md")],
    "xs-build":            [("build.md", "build-log.md"),
                            ("impl-plan.md", "impl-plan.md")],
    "review":              [("review.md", "review-report.md")],
    "review-lite":         [("review.md", "review-lite-report.md")],
    "integrate":           [("integrate.md", "integrate.md")],
    "observe":             [("observe.md", "observe.md")],
    "learn":               [("retrospective.md", "retrospective.md")],
    "manual":              [],  # created inline (checklist)
}


class E2EPipeline:
    """E2E test harness for klc lifecycle."""

    def __init__(self, track: str, keep: bool = False):
        self.track = track
        self.keep = keep
        self.scratch: Path | None = None
        self.ticket_key = "E2E-TEST-001"
        self.env: dict[str, str] = {}
        # Loaded lazily once scratch env is set up
        self._track_phases: list[str] | None = None
        self._phase_outputs: dict[str, list[str]] | None = None

    def say(self, msg: str) -> None:
        print(f"[e2e:{self.track}] {msg}")

    def fail(self, msg: str) -> None:
        sys.stderr.write(f"[e2e:{self.track}] FAIL: {msg}\n")
        if self.keep and self.scratch:
            sys.stderr.write(f"[e2e:{self.track}] scratch preserved at {self.scratch}\n")
        sys.exit(1)

    def run_py(self, script: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=str(self.scratch),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def setup(self) -> None:
        self.say("setup: creating temp project")
        self.scratch = Path(tempfile.mkdtemp(prefix=f"klc-e2e-{self.track.lower()}-"))

        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.scratch)

        klc_dir = self.scratch / ".klc"
        (klc_dir / "tickets").mkdir(parents=True)
        (klc_dir / "config").mkdir()
        (klc_dir / "index").mkdir()
        (klc_dir / "knowledge").mkdir()
        (klc_dir / "logs").mkdir()

        shutil.copy(FW_ROOT / "config" / "phases.yml", klc_dir / "config" / "phases.yml")
        shutil.copy(FW_ROOT / "config" / "models.yml", klc_dir / "config" / "models.yml")

        (klc_dir / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")

        # Load phases once the env is ready
        self._track_phases = _load_track_phases(self.track)
        self._phase_outputs = _load_phase_outputs()

        self.say(f"setup: scratch at {self.scratch}")
        self.say(f"setup: phases = {self._track_phases}")

    def seed_ticket(self) -> None:
        self.say(f"seed: creating ticket {self.ticket_key}")

        ticket_dir = self.scratch / ".klc" / "tickets" / self.ticket_key
        ticket_dir.mkdir()

        (ticket_dir / "raw.md").write_text(
            f"---\nticket: {self.ticket_key}\nkind_hint: feature\n---\n"
            f"# {self.ticket_key} — Fake E2E test ticket\n\n"
            f"Minimal fake ticket for validating {self.track}-track lifecycle.\n",
            encoding="utf-8"
        )

        meta = {
            "ticket": self.ticket_key,
            "kind": "feature",
            "kind_source": "user",
            "phase": "intake:ack-needed",
            "phase_history": [{
                "phase": "intake:ack-needed",
                "started_at": "2026-05-28T12:00:00Z"
            }],
            "track": self.track,
            "estimate": {
                "complexity": 1 if self.track == "XS" else 2,
                "uncertainty": 0,
                "risk": 0,
                "manual": 0,
                "total": 1 if self.track == "XS" else 2
            },
            "layer": "code",
            "affected_modules": ["test-module"],
            # Provide risk_tags so observe phase condition is met for S/M/L;
            # XS doesn't have observe in its track so this has no effect.
            "risk_tags": ["user-facing"],
            # Provide rework_count so learn condition is met.
            "rework_count": {"build": 1},
            "created": "2026-05-28T12:00:00Z",
            "owner": "e2e-harness",
            "jira_url": None,
            "links": [],
            "metrics": {}
        }
        (ticket_dir / "meta.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )

        self.say(f"seed: ticket created at {ticket_dir}")

    def copy_fixture(self, phase_id: str) -> None:
        """Copy fixture artefacts for phase (config-driven via _FIXTURE_MAP)."""
        ticket_dir = self.scratch / ".klc" / "tickets" / self.ticket_key

        if phase_id == "manual":
            (ticket_dir / "manual-checklist.md").write_text(
                f"---\nticket: {self.ticket_key}\n---\n"
                "# Manual Checklist\n\n- [x] Manual step 1\n- [x] Manual step 2\n",
                encoding="utf-8"
            )
            return

        for fixture_file, target_name in _FIXTURE_MAP.get(phase_id, []):
            source = FIXTURES / fixture_file
            if not source.exists():
                self.fail(f"copy_fixture: missing fixture {source}")
            target = ticket_dir / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            content = source.read_text(encoding="utf-8")
            content = content.replace("TEST-001", self.ticket_key)
            target.write_text(content, encoding="utf-8")
            self.say(f"copy_fixture: {fixture_file} → {target_name}")

    def run_ack(self, phase_id: str, pick: int | None = None,
                expect_fail: bool = False) -> subprocess.CompletedProcess:
        klc_script = FW_ROOT / "scripts" / "klc"
        args = ["ack", self.ticket_key]
        if pick is not None:
            args.extend(["--pick", str(pick)])

        self.say(f"ack: running klc ack {self.ticket_key} (pick={pick})")
        result = self.run_py(klc_script, *args)

        if not expect_fail and result.returncode != 0:
            self.fail(f"ack failed for {phase_id}: {result.stderr.strip()[:300]}")
        if expect_fail and result.returncode == 0:
            self.fail(f"ack should have failed for {phase_id} but succeeded")
        return result

    def verify_artefacts(self, phase_id: str) -> None:
        """Verify expected artefacts exist (driven by phases.yml outputs)."""
        assert self._phase_outputs is not None
        expected = self._phase_outputs.get(phase_id, [])
        ticket_dir = self.scratch / ".klc" / "tickets" / self.ticket_key

        for artefact in expected:
            path = ticket_dir / artefact
            if not path.exists():
                self.fail(f"verify: missing artefact {artefact} for phase {phase_id}")

        self.say(f"verify: all artefacts present for {phase_id}")

    def run_phase(self, phase_id: str) -> None:
        self.say(f"phase: {phase_id}")
        self.copy_fixture(phase_id)
        pick = 1 if phase_id not in ("intake",) else None
        self.run_ack(phase_id, pick=pick)
        self.verify_artefacts(phase_id)

    def teardown(self) -> None:
        if self.keep:
            self.say(f"teardown: preserving {self.scratch}")
            return
        if self.scratch and self.scratch.exists():
            shutil.rmtree(self.scratch)
            self.say("teardown: temp dir removed")

    def run(self) -> None:
        try:
            self.setup()
            self.seed_ticket()

            self.run_ack("intake", pick=None)

            assert self._track_phases is not None
            for phase_id in self._track_phases[1:]:  # skip intake
                self.run_phase(phase_id)

            meta_path = self.scratch / ".klc" / "tickets" / self.ticket_key / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            final_phase = meta.get("phase", "")

            if final_phase.startswith("learn:work"):
                self.fail(f"final phase is {final_phase}, ack may have failed")

            self.say(f"SUCCESS: {self.track}-track completed (final: {final_phase})")

        finally:
            self.teardown()


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------

class NegativeTests:
    """Verify that ack fails with a clear error when required outputs are missing."""

    def __init__(self, keep: bool = False):
        self.keep = keep
        self.scratch: Path | None = None
        self.env: dict[str, str] = {}

    def say(self, msg: str) -> None:
        print(f"[e2e:negative] {msg}")

    def fail(self, msg: str) -> None:
        sys.stderr.write(f"[e2e:negative] FAIL: {msg}\n")
        if self.keep and self.scratch:
            sys.stderr.write(f"[e2e:negative] scratch preserved at {self.scratch}\n")
        sys.exit(1)

    def setup(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="klc-e2e-neg-"))
        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.scratch)

        klc_dir = self.scratch / ".klc"
        (klc_dir / "tickets").mkdir(parents=True)
        (klc_dir / "config").mkdir()
        (klc_dir / "index").mkdir()
        (klc_dir / "knowledge").mkdir()
        (klc_dir / "logs").mkdir()

        shutil.copy(FW_ROOT / "config" / "phases.yml", klc_dir / "config" / "phases.yml")
        shutil.copy(FW_ROOT / "config" / "models.yml", klc_dir / "config" / "models.yml")
        (klc_dir / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")

    def teardown(self) -> None:
        if self.keep:
            self.say(f"preserving {self.scratch}")
            return
        if self.scratch and self.scratch.exists():
            shutil.rmtree(self.scratch)

    def _make_ticket(self, key: str, track: str, phase: str) -> Path:
        ticket_dir = self.scratch / ".klc" / "tickets" / key
        ticket_dir.mkdir(parents=True, exist_ok=True)
        (ticket_dir / "raw.md").write_text(
            f"---\nticket: {key}\nkind_hint: feature\n---\nFake ticket.\n",
            encoding="utf-8"
        )
        meta = {
            "ticket": key, "kind": "feature", "kind_source": "user",
            "phase": phase,
            "phase_history": [{"phase": phase, "started_at": "2026-05-28T12:00:00Z"}],
            "track": track,
            "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0,
                         "manual": 0, "total": 1},
            "layer": "code", "affected_modules": ["test-module"],
            "created": "2026-05-28T12:00:00Z", "owner": "e2e-negative",
            "jira_url": None, "links": [], "rework_count": {}, "metrics": {}
        }
        (ticket_dir / "meta.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        return ticket_dir

    def run_ack(self, ticket: str, pick: int | None = None) -> subprocess.CompletedProcess:
        klc_script = FW_ROOT / "scripts" / "klc"
        args = ["ack", ticket]
        if pick is not None:
            args.extend(["--pick", str(pick)])
        return subprocess.run(
            [sys.executable, str(klc_script), *args],
            cwd=str(self.scratch),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_discovery_without_spec_fails(self) -> None:
        """ack on discovery:work without spec.md must fail."""
        key = "NEG-001"
        self._make_ticket(key, "S", "discovery:work")
        result = self.run_ack(key)
        if result.returncode == 0:
            self.fail("discovery ack without spec.md succeeded — expected failure")
        if "Missing spec.md" not in result.stderr and "spec.md" not in result.stderr:
            self.fail(
                f"discovery ack failed but error doesn't mention spec.md:\n"
                f"{result.stderr.strip()}"
            )
        self.say("PASS: discovery ack without spec.md fails with clear error")

    def test_build_without_build_log_fails(self) -> None:
        """ack on build:work without build-log.md must fail."""
        key = "NEG-002"
        ticket_dir = self._make_ticket(key, "S", "build:work")
        # Provide impl-plan.md (an input), but NOT build-log.md (the output)
        (ticket_dir / "impl-plan.md").write_text("# stub\n", encoding="utf-8")
        result = self.run_ack(key)
        if result.returncode == 0:
            self.fail("build ack without build-log.md succeeded — expected failure")
        if "build-log.md" not in result.stderr:
            self.fail(
                f"build ack failed but error doesn't mention build-log.md:\n"
                f"{result.stderr.strip()}"
            )
        self.say("PASS: build ack without build-log.md fails with clear error")

    def test_review_without_report_fails(self) -> None:
        """ack on review:work without review-report.md must fail."""
        key = "NEG-003"
        ticket_dir = self._make_ticket(key, "S", "review:work")
        (ticket_dir / "spec.md").write_text("# stub\n", encoding="utf-8")
        result = self.run_ack(key)
        if result.returncode == 0:
            self.fail("review ack without review-report.md succeeded — expected failure")
        if "review-report.md" not in result.stderr:
            self.fail(
                f"review ack failed but error doesn't mention review-report.md:\n"
                f"{result.stderr.strip()}"
            )
        self.say("PASS: review ack without review-report.md fails with clear error")

    def test_observe_skipped_without_risk_tags(self) -> None:
        """S-track ticket without risk_tags must skip observe (land on learn:work)."""
        import shutil as _shutil
        import tempfile as _tempfile
        import os as _os
        scratch = Path(_tempfile.mkdtemp(prefix="klc-e2e-skip-"))
        env = dict(_os.environ)
        env["PROJECT_ROOT"] = str(scratch)
        klc_dir = scratch / ".klc"
        (klc_dir / "tickets").mkdir(parents=True)
        (klc_dir / "config").mkdir()
        (klc_dir / "index").mkdir()
        (klc_dir / "knowledge").mkdir()
        (klc_dir / "logs").mkdir()
        _shutil.copy(FW_ROOT / "config" / "phases.yml", klc_dir / "config" / "phases.yml")
        _shutil.copy(FW_ROOT / "config" / "models.yml", klc_dir / "config" / "models.yml")
        (klc_dir / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")
        try:
            key = "SKIP-001"
            ticket_dir = klc_dir / "tickets" / key
            ticket_dir.mkdir()
            (ticket_dir / "raw.md").write_text(
                f"---\nticket: {key}\n---\nFake.\n", encoding="utf-8"
            )
            # integrate:ack → next should skip observe (no risk_tags) → land on learn:work
            meta = {
                "ticket": key, "kind": "tech", "kind_source": "user",
                "phase": "integrate:ack",
                "phase_history": [{"phase": "integrate:ack",
                                   "started_at": "2026-05-28T12:00:00Z"}],
                "track": "S",
                "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0,
                             "manual": 0, "total": 1},
                "layer": "code", "affected_modules": [],
                "risk_tags": [],         # no risk tags → observe should be skipped
                "rework_count": {"build": 1},  # rework present → learn runs
                "created": "2026-05-28T12:00:00Z", "owner": "e2e-skip",
                "jira_url": None, "links": [], "metrics": {}
            }
            (ticket_dir / "meta.json").write_text(
                json.dumps(meta, indent=2) + "\n", encoding="utf-8"
            )
            klc_script = FW_ROOT / "scripts" / "klc"
            result = subprocess.run(
                [sys.executable, str(klc_script), "next", key],
                cwd=str(scratch), env=env,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self.fail(f"klc next failed: {result.stderr.strip()[:200]}")
            import json as _json
            new_meta = _json.loads((ticket_dir / "meta.json").read_text())
            phase = new_meta.get("phase", "")
            if not phase.startswith("learn"):
                self.fail(
                    f"expected observe to be skipped → learn:work, got {phase!r}\n"
                    f"phase_history: {new_meta.get('phase_history', [])[-3:]}"
                )
            # Verify skipped event recorded
            skipped = [e for e in new_meta.get("phase_history", [])
                       if e.get("event") == "skipped"]
            if not skipped:
                self.fail("no 'skipped' event in phase_history for observe")
        finally:
            if not self.keep:
                _shutil.rmtree(scratch)
        self.say("PASS: observe skipped when risk_tags=[]")

    def run(self) -> None:
        try:
            self.setup()
            self.test_discovery_without_spec_fails()
            self.test_build_without_build_log_fails()
            self.test_review_without_report_fails()
            self.test_observe_skipped_without_risk_tags()
            self.say("ALL NEGATIVE TESTS PASSED")
        finally:
            self.teardown()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--track", choices=["XS", "S", "M", "L"], help="Test single track")
    ap.add_argument("--keep", action="store_true", help="Preserve temp dir")
    ap.add_argument("--negative", action="store_true", help="Run negative tests only")
    args = ap.parse_args()

    if args.negative:
        NegativeTests(keep=args.keep).run()
        return 0

    tracks = [args.track] if args.track else ["XS", "S", "M", "L"]
    for track in tracks:
        E2EPipeline(track, keep=args.keep).run()

    print(f"[e2e] ALL TESTS PASSED ({len(tracks)} tracks)")

    # Always run negative tests
    NegativeTests(keep=args.keep).run()
    print("[e2e] NEGATIVE TESTS PASSED")

    return 0


if __name__ == "__main__":
    sys.exit(main())
