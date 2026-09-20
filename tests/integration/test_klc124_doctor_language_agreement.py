"""KLC-124 step-5 — AC-7: `klc doctor` gains a warn-only
`language-map-agreement` check, firing only when `file_scanner.EXT_LANG` and
the active profile's `sgconfig.yml` `languageGlobs` genuinely disagree on a
shared extension (mirroring AC-2/AC-3's own no-false-positive rule)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FW_ROOT / "core" / "skills"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, FW_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_doctor_language_map_check_passes_when_aligned():
    """AC-7: against the REAL, aligned EXT_LANG/sgconfig.yml pair (post
    step-1's fix), the check returns no errors and severity "pass" — never
    "warn" on a clean checkout."""
    doctor = _load("doctor_klc124_pos", "core/phases/doctor.py")
    errs, severity = doctor._language_map_agreement()
    assert errs == [], errs
    assert severity == "pass"


def test_doctor_language_map_check_warns_without_failing_on_disagreement(monkeypatch, capsys):
    """AC-7: a synthetic disagreement warns (severity "warn", never "fail")
    without flipping `klc doctor`'s default (no --strict) exit code, and the
    WARN line is present in --json output; --strict promotes it to FAIL via
    the existing, unchanged `_normalize` mechanism."""
    doctor = _load("doctor_klc124_neg", "core/phases/doctor.py")

    # `doctor._language_map_agreement` does `import file_scanner` at call
    # time, resolved via sys.path (SKILLS was inserted by doctor.py's own
    # module-level code) — importing it here under its real module name
    # ("file_scanner") gets the SAME cached module object, so monkeypatching
    # its EXT_LANG dict is visible inside the check.
    if str(SKILLS) not in sys.path:
        sys.path.insert(0, str(SKILLS))
    import file_scanner
    monkeypatch.setitem(file_scanner.EXT_LANG, "h", "c")  # force a disagreement w/ sgconfig's cpp

    errs, severity = doctor._language_map_agreement()
    assert severity == "warn"
    assert errs and any(".h" in e for e in errs), errs

    # Isolate the check-list to just this one check so the exit-code /
    # --strict-promotion assertions are not at the mercy of this sandbox's
    # OTHER, environment-dependent doctor checks.
    monkeypatch.setattr(doctor, "CHECKS",
                        [("language-map-agreement", doctor._language_map_agreement)])

    rc = doctor.run([])
    out = capsys.readouterr().out
    assert "WARN language-map-agreement" in out
    assert "DOCTOR_OK" in out
    assert rc == 0

    rc_strict = doctor.run(["--json", "--strict"])
    out_strict = capsys.readouterr().out
    data = json.loads(out_strict)
    entry = next(c for c in data["checks"] if c["check"] == "language-map-agreement")
    assert entry["ok"] is False
    assert rc_strict != 0
