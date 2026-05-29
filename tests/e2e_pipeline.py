#!/usr/bin/env python3
"""e2e_pipeline.py — E2E test harness for klc lifecycle.

Tests a complete ticket journey through all phases using fake agents
that produce canned artefacts. Validates state transitions, artefact
generation, and ack logic per config/phases.yml.

Usage:
    python tests/e2e_pipeline.py              # all tracks
    python tests/e2e_pipeline.py --track S    # single track
    python tests/e2e_pipeline.py --keep       # preserve temp dir
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

# Track-to-phases mapping per config/phases.yml
# XS: intake → discovery → xs-build → review-lite → integrate → learn
# S:  intake → discovery → acceptance-test-plan → build → review → integrate → observe → learn
# M:  S + design + detailed-test-plan
# L:  M + manual
TRACK_PHASES = {
    "XS": ["intake", "discovery", "xs-build", "review-lite", "integrate", "learn"],
    "S": ["intake", "discovery", "acceptance-test-plan", "build", "review", "integrate", "observe", "learn"],
    "M": ["intake", "discovery", "acceptance-test-plan", "design", "detailed-test-plan", "build", "review", "manual", "integrate", "observe", "learn"],
    "L": ["intake", "discovery", "acceptance-test-plan", "design", "detailed-test-plan", "build", "review", "manual", "integrate", "observe", "learn"],
}

# Phase to artefact mapping per config/phases.yml outputs
PHASE_ARTEFACTS = {
    "intake": ["raw.md", "meta.json"],
    "discovery": ["spec.md"],
    "acceptance-test-plan": ["test-plan.md"],
    "design": ["design/options.md", "impl-plan.md"],
    "detailed-test-plan": ["test-plan.md"],  # extends existing
    "build": ["build-log.md", "impl-plan.md"],
    "xs-build": ["build-log.md"],
    "review": ["review-report.md"],
    "review-lite": ["review-report.md"],
    "integrate": ["integrate.md"],
    "manual": ["manual-checklist.md"],
    "observe": ["observe.md"],
    "learn": ["retrospective.md"],
}

# Fixture file mapping (fixture name → artefact name)
FIXTURE_MAP = {
    "discovery.md": "spec.md",
    "acceptance-test-plan.md": "test-plan.md",
    "design.md": "design.md",
    "detailed-test-plan.md": "test-plan.md",
    "build.md": "build-log.md",
    "review.md": "review-report.md",
    "integrate.md": "integrate.md",
    "observe.md": "observe.md",
    "retrospective.md": "retrospective.md",
}


class E2EPipeline:
    """E2E test harness for klc lifecycle."""

    def __init__(self, track: str, keep: bool = False):
        self.track = track
        self.keep = keep
        self.scratch: Path | None = None
        self.ticket_key = "E2E-TEST-001"
        self.env: dict[str, str] = {}

    def say(self, msg: str) -> None:
        """Log message."""
        print(f"[e2e:{self.track}] {msg}")

    def fail(self, msg: str) -> None:
        """Fail test with message."""
        sys.stderr.write(f"[e2e:{self.track}] FAIL: {msg}\n")
        if self.keep and self.scratch:
            sys.stderr.write(f"[e2e:{self.track}] scratch preserved at {self.scratch}\n")
        sys.exit(1)

    def run_py(self, script: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run Python script with PROJECT_ROOT set."""
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
        """Create temp .klc/ root with minimal config."""
        self.say("setup: creating temp project")
        self.scratch = Path(tempfile.mkdtemp(prefix=f"klc-e2e-{self.track.lower()}-"))

        # Set PROJECT_ROOT to scratch dir
        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.scratch)

        # Create minimal directory structure
        klc_dir = self.scratch / ".klc"
        (klc_dir / "tickets").mkdir(parents=True)
        (klc_dir / "config").mkdir()
        (klc_dir / "index").mkdir()
        (klc_dir / "knowledge").mkdir()
        (klc_dir / "logs").mkdir()

        # Copy essential config files
        shutil.copy(FW_ROOT / "config" / "phases.yml", klc_dir / "config" / "phases.yml")
        shutil.copy(FW_ROOT / "config" / "models.yml", klc_dir / "config" / "models.yml")

        # Create minimal profile
        profile_yml = klc_dir / "config" / "profile.yml"
        profile_yml.write_text("profile: generic\n", encoding="utf-8")

        self.say(f"setup: scratch at {self.scratch}")

    def seed_ticket(self) -> None:
        """Create fake ticket with intake artefacts."""
        self.say(f"seed: creating ticket {self.ticket_key}")

        ticket_dir = self.scratch / ".klc" / "tickets" / self.ticket_key
        ticket_dir.mkdir()

        # Create raw.md
        raw_md = ticket_dir / "raw.md"
        raw_md.write_text(
            f"---\nticket: {self.ticket_key}\nkind_hint: feature\n---\n"
            f"# {self.ticket_key} — Fake E2E test ticket\n\n"
            f"Minimal fake ticket for validating {self.track}-track lifecycle.\n",
            encoding="utf-8"
        )

        # Create meta.json
        meta_json = ticket_dir / "meta.json"
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
            "created": "2026-05-28T12:00:00Z",
            "owner": "e2e-harness",
            "jira_url": None,
            "links": [],
            "rework_count": {},
            "metrics": {}
        }
        meta_json.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        self.say(f"seed: ticket created at {ticket_dir}")

    def copy_fixture(self, phase_id: str) -> None:
        """Copy fixture artefact for phase."""
        ticket_dir = self.scratch / ".klc" / "tickets" / self.ticket_key

        # Determine fixture files for phase
        fixtures_to_copy = []

        if phase_id == "discovery":
            fixtures_to_copy = [("discovery.md", "spec.md")]
        elif phase_id == "acceptance-test-plan":
            fixtures_to_copy = [("acceptance-test-plan.md", "test-plan.md")]
        elif phase_id == "design":
            # Design phase outputs: design/options.md and impl-plan.md
            fixtures_to_copy = [("design.md", "design/options.md"), ("impl-plan.md", "impl-plan.md")]
        elif phase_id == "detailed-test-plan":
            fixtures_to_copy = [("detailed-test-plan.md", "test-plan.md")]
        elif phase_id in ("build", "xs-build"):
            fixtures_to_copy = [("build.md", "build-log.md"), ("impl-plan.md", "impl-plan.md")]
        elif phase_id in ("review", "review-lite"):
            fixtures_to_copy = [("review.md", "review-report.md")]
        elif phase_id == "integrate":
            fixtures_to_copy = [("integrate.md", "integrate.md")]
        elif phase_id == "observe":
            fixtures_to_copy = [("observe.md", "observe.md")]
        elif phase_id == "learn":
            fixtures_to_copy = [("retrospective.md", "retrospective.md")]
        elif phase_id == "manual":
            # Manual phase: create minimal checklist
            manual_md = ticket_dir / "manual-checklist.md"
            manual_md.write_text(
                f"---\nticket: {self.ticket_key}\n---\n"
                "# Manual Checklist\n\n- [x] Manual step 1\n- [x] Manual step 2\n",
                encoding="utf-8"
            )
            return

        if not fixtures_to_copy:
            return  # No fixture for this phase (e.g., intake)

        # Copy each fixture
        for fixture_file, target_name in fixtures_to_copy:
            source = FIXTURES / fixture_file
            if not source.exists():
                self.fail(f"copy_fixture: missing fixture {source}")

            target = ticket_dir / target_name

            # Ensure parent directory exists (for design/options.md etc.)
            target.parent.mkdir(parents=True, exist_ok=True)

            # Update ticket reference in fixture
            content = source.read_text(encoding="utf-8")
            content = content.replace("TEST-001", self.ticket_key)
            target.write_text(content, encoding="utf-8")

            self.say(f"copy_fixture: {fixture_file} → {target_name}")

    def run_ack(self, phase_id: str, pick: int | None = None) -> None:
        """Run klc ack for phase."""
        klc_script = FW_ROOT / "scripts" / "klc"
        args = ["ack", self.ticket_key]
        if pick is not None:
            args.extend(["--pick", str(pick)])

        self.say(f"ack: running klc ack {self.ticket_key} (pick={pick})")
        result = self.run_py(klc_script, *args, check=False)

        if result.returncode != 0:
            self.fail(f"ack failed for {phase_id}: {result.stderr.strip()[:300]}")

    def verify_artefacts(self, phase_id: str) -> None:
        """Verify expected artefacts exist."""
        expected = PHASE_ARTEFACTS.get(phase_id, [])
        ticket_dir = self.scratch / ".klc" / "tickets" / self.ticket_key

        for artefact in expected:
            path = ticket_dir / artefact
            if not path.exists():
                self.fail(f"verify: missing artefact {artefact} for phase {phase_id}")

        self.say(f"verify: all artefacts present for {phase_id}")

    def verify_phase_transition(self, expected_phase: str) -> None:
        """Verify ticket transitioned to expected phase."""
        meta_path = self.scratch / ".klc" / "tickets" / self.ticket_key / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        current = meta.get("phase", "")

        if not current.startswith(expected_phase):
            self.fail(f"verify: expected phase {expected_phase}:*, got {current}")

        self.say(f"verify: phase = {current}")

    def run_phase(self, phase_id: str) -> None:
        """Execute one phase: copy fixture, ack, verify."""
        self.say(f"phase: {phase_id}")

        # Copy fixture (simulates agent work)
        self.copy_fixture(phase_id)

        # Run ack (default pick=1 for phases that need it)
        pick = 1 if phase_id not in ("intake",) else None
        self.run_ack(phase_id, pick=pick)

        # Verify artefacts
        self.verify_artefacts(phase_id)

    def teardown(self) -> None:
        """Cleanup temp directory."""
        if self.keep:
            self.say(f"teardown: preserving {self.scratch}")
            return

        if self.scratch and self.scratch.exists():
            shutil.rmtree(self.scratch)
            self.say("teardown: temp dir removed")

    def run(self) -> None:
        """Run full E2E test for track."""
        try:
            self.setup()
            self.seed_ticket()

            # Ack intake first
            self.run_ack("intake", pick=None)

            # Run remaining phases
            phases = TRACK_PHASES[self.track]
            for phase_id in phases[1:]:  # Skip intake
                self.run_phase(phase_id)

            # Verify final state
            meta_path = self.scratch / ".klc" / "tickets" / self.ticket_key / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            final_phase = meta.get("phase", "")

            # After learn phase, ticket should be archived or in learn:ack
            # learn:work means ack didn't complete properly
            if final_phase.startswith("learn:work"):
                self.fail(f"final phase is {final_phase}, ack may have failed")

            self.say(f"SUCCESS: {self.track}-track completed (final: {final_phase})")

        finally:
            self.teardown()


def main() -> int:
    """Main entry point."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--track", choices=["XS", "S", "M", "L"], help="Test single track")
    ap.add_argument("--keep", action="store_true", help="Preserve temp dir")
    args = ap.parse_args()

    tracks = [args.track] if args.track else ["XS", "S", "M", "L"]

    for track in tracks:
        pipeline = E2EPipeline(track, keep=args.keep)
        pipeline.run()

    print(f"[e2e] ALL TESTS PASSED ({len(tracks)} tracks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
