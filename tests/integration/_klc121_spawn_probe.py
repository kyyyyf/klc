"""_klc121_spawn_probe.py — shared scaffolding for KLC-121's spawn-counting
tests (AC-3's whole-run counter, AC-4's per-builder zero-spawn clause).

NOT a test module itself — no ``test_`` prefix, so pytest never collects it.

The technique mirrors spec.md F-002/F-013's own evidence collection: "a
counting wrapper substituted for profile-resolve.py in a scratchpad copy of
the repo, logging argv ... per spawn". Building a REAL (not symlinked) copy
of ``core/`` matters: every module that self-locates its framework root via
``Path(__file__).resolve().parent...`` would otherwise have that resolve()
call chase a symlink straight back to the live repo, silently defeating the
substitution.
"""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
REAL_PROFILE_RESOLVE = FRAMEWORK_ROOT / "core" / "skills" / "profile-resolve.py"

ENV_LOG = "KLC121_SPAWN_LOG"
ENV_REAL_RESOLVER = "KLC121_REAL_RESOLVER"

_STUB = textwrap.dedent('''\
    #!/usr/bin/env python3
    """Counting stub for profile-resolve.py (KLC-121 test scaffolding, not
    shipped). Logs one line per invocation to $KLC121_SPAWN_LOG, then
    delegates to the REAL resolver at $KLC121_REAL_RESOLVER by path, so
    every functional answer stays byte-identical to production."""
    import importlib.util
    import os
    import sys
    from pathlib import Path

    log = Path(os.environ["KLC121_SPAWN_LOG"])
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(" ".join(sys.argv[1:]) + "\\n")

    real = Path(os.environ["KLC121_REAL_RESOLVER"])
    spec = importlib.util.spec_from_file_location("_klc121_real_resolver", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.exit(mod.main())
''')


def build_core_mirror(dest: Path) -> Path:
    """A real (non-symlinked) copy of ``core/``, ``config/``, ``profiles/``
    and ``scripts/`` under *dest*, with ``core/skills/profile-resolve.py``
    replaced by the counting stub. Cheap (~5 MB total); callers set
    ``KLC121_SPAWN_LOG``/``KLC121_REAL_RESOLVER`` in the child's
    environment via `spawn_env()`. Returns *dest* (the directory a
    mirrored builder OR entry-point script's own FRAMEWORK_ROOT resolves
    to — `scripts/init.py`/`scripts/update.py` included, for the AC-3
    whole-run spawn counter).

    ``config/`` and ``profiles/`` are needed too, not just ``core/``:
    every module under ``core/skills`` that self-locates its framework
    root via ``Path(__file__).resolve().parent...`` resolves to the
    MIRROR once it is a real (non-symlinked) file there — including
    ``core/shared/paths.framework_root()``, which ``settings.py`` (a
    sibling `core/skills` module every profile-resolve.py invocation
    imports) uses to find ``config/settings.yml``. Without a mirrored
    ``config/``, `settings.profile()` silently resolves to nothing and
    `profile-resolve.py` fails with "no profile with a `profile:` key
    found", even though the real repo has one."""
    for name in ("core", "config", "profiles", "scripts"):
        src = FRAMEWORK_ROOT / name
        if not src.exists():
            continue
        dst = dest / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    stub_path = dest / "core" / "skills" / "profile-resolve.py"
    stub_path.write_text(_STUB, encoding="utf-8")
    stub_path.chmod(0o755)
    return dest


def spawn_env(base_env: dict, log_path: Path) -> dict:
    """The child environment for a mirrored builder invocation: the real
    env plus the two variables the stub needs, pointed at *log_path*."""
    env = dict(base_env)
    env[ENV_LOG] = str(log_path)
    env[ENV_REAL_RESOLVER] = str(REAL_PROFILE_RESOLVE)
    return env


def count_spawns(log_path: Path) -> int:
    """Non-blank lines in *log_path* — one per profile-resolve.py spawn.
    Missing file (no spawn happened at all) counts as zero."""
    if not log_path.exists():
        return 0
    return sum(1 for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip())
