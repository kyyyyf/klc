#!/usr/bin/env python3
"""`klc doctor` — install-level health check.

Not ticket-scoped. Walks the framework itself:
  - executables have correct shebang + permissions
  - templates parse
  - active profile manifest + reviewer-allowlist are valid
  - MCP servers respond (if .mcp.json is present — best-effort)
  - git is installed and the project root is a repo
  - Python deps (jinja2) are present

Prints PASS/FAIL per check; exit 0 only if every check passes.
Safe on CI.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
CONFIG = Path(__file__).resolve().parent.parent.parent / "config"
sys.path.insert(0, str(SKILLS))
from _paths import framework_root, project_root, klc_index_dir as _index_dir  # noqa: E402


CHECKS: list[tuple[str, callable]] = []


def check(name: str):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("skills-executable")
def _skills_executable() -> list[str]:
    errs: list[str] = []
    # Shared helper modules (underscore-prefixed) are imported, not
    # executed; skip the shebang / +x check for them.
    for p in SKILLS.glob("*.py"):
        if p.name.startswith("_"):
            continue
        if not os.access(p, os.X_OK):
            errs.append(f"{p.relative_to(framework_root())} not executable (chmod +x)")
        first = p.read_text(encoding="utf-8", errors="ignore").splitlines()[:1]
        if first and not first[0].startswith("#!"):
            errs.append(f"{p.relative_to(framework_root())} missing shebang")
    return errs


@check("phase-scripts-executable")
def _phases_executable() -> list[str]:
    errs: list[str] = []
    phases_dir = Path(__file__).resolve().parent
    for p in phases_dir.glob("*.py"):
        if p.name == "__init__.py":
            continue
        if not os.access(p, os.X_OK):
            errs.append(f"{p.relative_to(framework_root())} not executable")
    return errs


@check("templates-parse")
def _templates_parse() -> list[str]:
    errs: list[str] = []
    try:
        from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
    except ImportError:
        return ["jinja2 not installed (pip install jinja2)"]
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    for tmpl in TEMPLATES.glob("*.j2"):
        try:
            env.get_template(tmpl.name)
        except TemplateSyntaxError as exc:
            errs.append(f"{tmpl.name}: {exc}")
    return errs


@check("profile-manifest")
def _profile_manifest() -> list[str]:
    errs: list[str] = []
    try:
        import yaml
    except ImportError:
        return ["pyyaml not installed (pip install pyyaml)"]
    import settings as _settings  # KLC-100: resolve the ACTIVE profile via the loader

    name = _settings.profile()  # settings.yml → project/framework profile.yml → None
    if not name:
        # F-5: keep an explicit no-profile error rather than defaulting to "generic".
        return [f"{CONFIG / 'settings.yml'} / profile.yml: no profile set"]
    manifest = framework_root() / "profiles" / name / "manifest.yml"
    if not manifest.exists():
        return [f"profile {name!r}: {manifest} missing"]
    try:
        yaml.safe_load(manifest.read_text())
    except yaml.YAMLError as exc:
        errs.append(f"{manifest}: {exc}")
    return errs


@check("language-map-agreement")
def _language_map_agreement() -> tuple[list[str], str]:
    """KLC-124 AC-7: `file_scanner.EXT_LANG` (the single extension-to-language
    source of truth) cross-checked against the active profile's `sgconfig.yml`
    `languageGlobs` override, via the ONE shared comparator
    (`file_scanner.ext_lang_sgconfig_disagreements`) AC-2/AC-3's own guard
    test uses — same rule, defined once. Warn-only by construction (never
    flips doctor's default exit code, exactly like index-degraded/index-hook):
    returns ("pass") whenever nothing to report, and only returns ("warn")
    when a genuine disagreement is found, mirroring `index_health.degraded`'s
    own pass/warn convention so --strict's WARN->FAIL promotion never fires on
    an empty result."""
    import file_scanner
    try:
        import yaml
    except ImportError:
        return ([], "pass")  # can't parse sgconfig without pyyaml; not a hard failure
    import settings as _settings

    name = _settings.profile()
    if not name:
        return ([], "pass")
    manifest_path = framework_root() / "profiles" / name / "manifest.yml"
    if not manifest_path.exists():
        return ([], "pass")
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ([], "pass")
    sgconfig_rel = manifest.get("sgconfig")
    if not sgconfig_rel:
        return ([], "pass")
    sg_path = framework_root() / sgconfig_rel
    if not sg_path.exists():
        return ([], "pass")
    try:
        sg = yaml.safe_load(sg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ([], "pass")
    disagreements = file_scanner.ext_lang_sgconfig_disagreements(sg.get("languageGlobs") or {})
    if disagreements:
        return (disagreements, "warn")
    return ([], "pass")


@check("reviewer-allowlist")
def _reviewer_allowlist() -> list[str]:
    cfg = CONFIG / "reviewer-allowlist.yml"
    if not cfg.exists():
        return []  # seed is optional
    try:
        import yaml
        yaml.safe_load(cfg.read_text())
    except Exception as exc:
        return [f"{cfg}: {exc}"]
    return []


@check("git-available")
def _git() -> list[str]:
    if not shutil.which("git"):
        return ["git not on PATH"]
    r = subprocess.run(["git", "-C", str(project_root()), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"project root {project_root()} is not a git repository"]
    return []


@check("klc-dispatcher")
def _klc() -> list[str]:
    klc = framework_root() / "scripts" / "klc"
    if not klc.exists():
        return ["scripts/klc missing"]
    if not os.access(klc, os.X_OK):
        return ["scripts/klc not executable"]
    return []


@check("jira-sync-queue")
def _jira_sync_queue() -> list[str]:
    errs: list[str] = []
    try:
        import jira_sync
        size = jira_sync.queue_size()
        if size == 0:
            return []
        p = jira_sync._queue_path()
        import json
        import datetime as _dt
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        oldest_at = None
        for line in lines:
            try:
                e = json.loads(line)
                at_str = e.get("at", "")
                if at_str:
                    at = _dt.datetime.fromisoformat(at_str.replace("Z", "+00:00"))
                    if oldest_at is None or at < oldest_at:
                        oldest_at = at
            except Exception:
                pass
        age_msg = ""
        if oldest_at:
            age = _dt.datetime.now(_dt.timezone.utc) - oldest_at
            days = age.days
            age_msg = f", oldest {days}d ago"
            if days >= 7:
                errs.append(
                    f"jira-sync queue has {size} pending entries{age_msg} — "
                    f"run `klc jira-sync` to flush"
                )
                return errs
        if size >= 100:
            errs.append(
                f"jira-sync queue has {size} pending entries{age_msg} — "
                f"run `klc jira-sync` to flush"
            )
    except Exception as exc:
        errs.append(f"jira-sync queue check failed: {exc}")
    return errs


@check("config-validation")
def _config_validation() -> list[str]:
    """Validate config files for unknown keys."""
    errs: list[str] = []
    try:
        # Import validate_config skill
        validate_config_path = SKILLS / "validate_config.py"
        if not validate_config_path.exists():
            errs.append("validate_config.py not found in core/skills/")
            return errs

        # Import and run validation
        spec = importlib.util.spec_from_file_location("validate_config", validate_config_path)
        if spec and spec.loader:
            validate_config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(validate_config)

            warnings = validate_config.validate_all()
            # Convert warnings to errors for doctor output
            errs.extend(warnings)

    except Exception as exc:
        errs.append(f"config validation failed: {exc}")

    return errs


@check("external-reviewer-key")
def _external_reviewer_key() -> list[str]:
    """Warn when the resolved external-reviewer route needs something this
    host doesn't have (KLC-120 AC-12/D-011): an unset API key when the
    route resolves to `openai`/`google`, or a missing `claude` CLI when it
    resolves to `anthropic`. Stays silent otherwise — this check is
    warn-only (_WARN_ONLY below), never a doctor FAIL."""
    errs: list[str] = []
    try:
        from _yaml import parse as _yml_parse
        rv_cfg_path = CONFIG / "reviewers.yml"
        if not rv_cfg_path.exists():
            return errs
        cfg = _yml_parse(rv_cfg_path.read_text(encoding="utf-8")) or {}
        ext = cfg.get("external_reviewer") or {}
        if not ext.get("enabled"):
            return errs
        import review_plan
        route = review_plan.external_route(ext, None)
        provider = route.get("provider")
        if provider in review_plan.KEYED_PROVIDERS:
            key_env = route.get("api_key_env")
            if key_env and not os.environ.get(key_env):
                errs.append(
                    f"external_reviewer resolves to {provider} but "
                    f"${key_env} is not set — external review will be "
                    "skipped at runtime"
                )
        elif provider == "anthropic" and not shutil.which(
                os.environ.get("CLAUDE_CLI", "claude")):
            errs.append(
                "external_reviewer resolves to anthropic but the claude "
                "CLI is not on PATH — external review will be skipped at "
                "runtime"
            )
    except Exception as exc:
        errs.append(f"external-reviewer-key check failed: {exc}")
    return errs


@check("index-freshness")
def _index_freshness() -> tuple[list[str], str]:
    import index_health
    return index_health.freshness(_index_dir(), project_root())


@check("index-views")
def _index_views() -> tuple[list[str], str]:
    import index_health
    return index_health.views(_index_dir())


@check("index-degraded")
def _index_degraded() -> tuple[list[str], str]:
    import index_health
    return index_health.degraded(_index_dir())


@check("index-hook")
def _index_hook() -> tuple[list[str], str]:
    import index_health
    import settings as _settings
    return index_health.hook(project_root(), _settings.hook_mode(), _settings.hook_location())


@check("project-tools")
def _project_tools() -> tuple[list[str], str]:
    """INFORMATIONAL (KLC-178 AC-9): print the detected languages and the
    tool requirements `klc setup` recorded in project-deps.json. Never a
    warning or failure, not even under --strict. Language servers are a
    convenience for the agent; they are not part of the framework's health.
    (ast-grep is a real check of its own, `ast-grep`, because the indexer needs it.)
    """
    info: list[str] = []
    try:
        import detect_languages

        langs = sorted(detect_languages.detect())
        info.append("languages: " + (", ".join(langs) if langs else "none detected"))

        deps_file = _index_dir() / "project-deps.json"
        if not deps_file.exists():
            info.append("project-deps.json absent — language tool requirements "
                        "were never detected (informational)")
            return (info, "pass")
        deps = json.loads(deps_file.read_text(encoding="utf-8"))
        for lang, tools in (deps.get("required") or {}).items():
            for tool in tools:
                if (deps.get("detected") or {}).get(tool) is None:
                    info.append(f"{tool} (for {lang}) — not found (informational)")
    except Exception as exc:
        info.append(f"project-tools info unavailable: {exc}")
    return (info, "pass")


@check("ast-grep")
def _ast_grep() -> tuple[list[str], str]:
    """The indexer shells out to ast-grep (binary `ast-grep` or its alias `sg`).
    Missing is a WARN: plain `klc doctor` stays green, `--strict` turns it into a failure."""
    if shutil.which("ast-grep") or shutil.which("sg"):
        return ([], "pass")
    return (["ast-grep not found on PATH (the indexer needs it; binary `ast-grep` or `sg`)"],
            "warn")


@check("jira-sync-conflicts")
def _jira_sync_conflicts() -> list[str]:
    """Scan live tickets for unresolved meta.jira_sync.conflicts.

    Warn-only by default (same as project-tools) — won't fail doctor
    unless --strict is passed. Managed-mode conflicts accumulate here.
    """
    errs: list[str] = []
    try:
        from _paths import klc_tickets_dir
        import json as _json
        tickets_dir = klc_tickets_dir()
        if not tickets_dir.exists():
            return []
        for meta_file in sorted(tickets_dir.glob("*/meta.json")):
            try:
                meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            jira_sync = meta.get("jira_sync") or {}
            conflicts = jira_sync.get("conflicts") or []
            if conflicts:
                ticket = meta.get("ticket", meta_file.parent.name)
                for c in conflicts:
                    errs.append(
                        f"{ticket}: {c.get('type','unknown')} — {c.get('detail','')}"
                        + (f" [{c.get('suggested','')}]" if c.get("suggested") else "")
                    )
    except Exception as exc:
        errs.append(f"jira-sync-conflicts check failed: {exc}")
    return errs


# Warn-only checks: don't fail doctor without --strict.
_WARN_ONLY = {"jira-sync-conflicts", "external-reviewer-key"}


def _normalize(result):
    """Accept the legacy bare list a check used to return, and the KLC-107
    ``(messages, severity)`` tuple form. Every existing check keeps its exact
    meaning — this is the only harness change (spec AC-1..AC-6)."""
    if isinstance(result, tuple):
        msgs, severity = result
        return list(msgs), severity
    return list(result), ("fail" if result else "pass")


_FW_TESTS = str(Path(__file__).resolve().parents[2] / "tests")
_FW_FIXTURES = str(Path(__file__).resolve().parents[2] / "tests" / "fixtures")


def _run_tests(path: str = _FW_TESTS) -> int:
    return subprocess.call([sys.executable, "-m", "pytest", path,
                            "-q", f"--ignore={_FW_FIXTURES}"])


# ---- KLC-178: bootstrap verbs folded into doctor ---------------------------

FW = Path(__file__).resolve().parent.parent.parent
_PHASES = str(Path(__file__).resolve().parent)


def _has_jinja2() -> bool:
    return importlib.util.find_spec("jinja2") is not None


def _bootstrap_check() -> int:
    """`install_deps.py --bootstrap` (Python, git, jinja2) as a subprocess."""
    return subprocess.call([sys.executable, str(FW / "scripts" / "install_deps.py"),
                            "--bootstrap"])


def install_project(root: Path, force: bool = False) -> int:
    """`doctor --install <root>`: bootstrap check (only when jinja2 is missing),
    install, a first scan when the index is absent, `setup` (records project-deps.json), then `state init` when <root>
    is a git repo. Safe to run twice:
    an installed root is reported and left untouched unless `force` re-runs
    install with --force (regenerates configs and re-records the hook mode)."""
    if not root.is_dir():
        sys.stderr.write(f"klc doctor: {root} is not a directory\n")
        return 2
    if not _has_jinja2():
        rc = _bootstrap_check()
        if rc != 0:
            sys.stderr.write("klc doctor: bootstrap dependency check failed; "
                             "nothing was installed\n")
            return 1
    if _PHASES not in sys.path:
        sys.path.insert(0, _PHASES)
    import install as _install
    import state as _state

    klc = root / ".klc"
    installed = (klc / "bin" / "klc").exists() and (klc / "config" / "profile.yml").exists()
    if force:
        rc = _install.run([str(root), "--force"])
        if rc != 0:
            return rc
    elif installed:
        print(f"klc doctor: already installed at {root}; nothing to change")
    else:
        rc = _install.run([str(root)])
        if rc != 0:
            return rc
    # setup reads structural.json, so a fresh root is scanned first (scan-only).
    if not (root / ".klc" / "index" / "structural.json").exists():
        refresh_index(root)
    old = os.environ.get("PROJECT_ROOT")
    os.environ["PROJECT_ROOT"] = str(root)
    try:
        # Record the language-tool requirements (project-deps.json). The detection
        # output is informational; a failure here never blocks the bootstrap.
        import setup as _setup
        _setup.run([])
        if (root / ".git").exists():
            return _state.run(["init"])
        print("klc doctor: not a git repository; `state init` skipped")
        return 0
    finally:
        if old is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = old


def refresh_index(root: Path, scan: bool = True) -> int:
    """`doctor --index` (scan=False: only the verdict): `init --scan-only` when `.last-run` is absent, else
    `update`; then print the freshness verdict. A stale index is a failure."""
    import index_health

    idx = root / ".klc" / "index"
    script = "init.py" if not (idx / ".last-run").exists() else "update.py"
    args = ["--scan-only"] if script == "init.py" else []
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    rc = 0
    if scan:
        rc = subprocess.call([sys.executable, str(FW / "scripts" / script), *args], env=env)
    errs, sev = index_health.freshness(idx, root)
    if sev == "pass":
        print("index: fresh")
    else:
        last = ""
        lr = idx / ".last-run"
        if lr.exists():
            last = lr.read_text(encoding="utf-8").strip()[:8]
        print(f"index: stale: HEAD moved since {last}" if last else "index: stale")
        for e in errs:
            print(f"  FAIL index-freshness - {e}")
    return rc if rc else (1 if sev != "pass" else 0)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc doctor")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    ap.add_argument("--strict", action="store_true",
                    help="Promote warnings to failures (language tools stay informational)")
    ap.add_argument("--install", metavar="ROOT", default=None,
                    help="Bootstrap ROOT: install the shims/config, then `state init` "
                         "when ROOT is a git repo. Idempotent.")
    ap.add_argument("--force", action="store_true",
                    help="With --install: re-run install even when ROOT is already "
                         "installed (regenerates configs, re-records the hook decision)")
    ap.add_argument("--index", action="store_true",
                    help="Refresh the index (full scan when never built, else update) "
                         "and report its freshness")
    ap.add_argument("--tests", action="store_true",
                    help="Run the test suite as a gate; exit 0 only if all tests pass")
    ap.add_argument("--tests-path", default=_FW_TESTS,
                    help="Path to pass to pytest (default: framework tests/); useful in tests")
    args = ap.parse_args(argv)

    if args.force and args.install is None:
        ap.error("--force only applies together with --install <root>")
    if args.json and (args.install is not None or args.index):
        ap.error("--json is only for the health checks; --install/--index print text")

    # --install / --index are actions with their own verdict; they do not fall
    # through to the health checks (run plain `klc doctor` for those).
    if args.install is not None or args.index:
        rc = 0
        target = Path(args.install).resolve() if args.install is not None else None
        # install_project scans a fresh root itself (setup needs the scan), so
        # --index then only reports the verdict instead of scanning twice.
        scanned = target is not None and not (target / ".klc" / "index" / "structural.json").exists()
        if target is not None:
            rc = install_project(target, force=args.force)
        if rc == 0 and args.index:
            rc = refresh_index(target if target is not None else project_root(), scan=not scanned)
        return rc

    if args.tests:
        rc = _run_tests(args.tests_path)
        print("doctor --tests: PASS" if rc == 0 else "doctor --tests: FAIL")
        return 0 if rc == 0 else 1

    results = []
    overall_ok = True
    for name, fn in CHECKS:
        errs, severity = _normalize(fn())

        # Warn-only checks: don't fail doctor without --strict. A check that
        # returns its OWN "warn" severity (the KLC-107 tuple form) is already
        # warn-only by construction; _WARN_ONLY additionally downgrades the
        # legacy bare-list checks that used to fail silently.
        if name in _WARN_ONLY and not args.strict:
            severity = "warn" if errs else "pass"
        if severity == "warn" and args.strict:
            severity = "fail"
        ok = severity != "fail"
        overall_ok = overall_ok and ok
        entry = {"check": name, "ok": ok, "errors": errs}
        if severity == "warn":
            entry["warn"] = True
        results.append(entry)

    if args.json:
        print(json.dumps({"ok": overall_ok, "checks": results}, indent=2))
    else:
        for r in results:
            if r.get("warn"):
                tag = "WARN"
            else:
                tag = "PASS" if r["ok"] else "FAIL"
            print(f"  {tag} {r['check']}")
            for e in r["errors"]:
                print(f"       - {e}")
        print()
        print("DOCTOR_OK" if overall_ok else "DOCTOR_FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
