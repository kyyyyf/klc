"""tests/integration/test_klc_doctor_profile.py — KLC-122 step-5 (AC-2, AC-9).

Proves `klc doctor`'s pre-existing profile-manifest check degrades cleanly
(no traceback) for a stale per-project `.klc/config/profile.yml: profile: ue`
override now that the removed UE profile's directory is gone, and reports
green against the new `generic` default when no per-project override is
set. Neither case
needed a code change in `core/phases/doctor.py::_profile_manifest()` — it
already resolves the active profile generically and already returns a clean
error string for any unresolvable manifest path. This file only closes the
coverage gap AC-9 calls out.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "core" / "phases"))
sys.path.insert(0, str(REPO_ROOT / "core" / "skills"))

import doctor  # noqa: E402


def test_doctor_profile_manifest_check_passes_on_generic_default():
    errors = doctor._profile_manifest()
    assert errors == []


def test_doctor_reports_missing_profile_manifest_for_stale_ue_override(
        tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / ".klc" / "config").mkdir(parents=True)
    (proj / ".klc" / "config" / "profile.yml").write_text(
        "profile: ue\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(proj))
    errors = doctor._profile_manifest()
    assert any("ue" in e and "missing" in e for e in errors), errors
