#!/usr/bin/env python3
"""smoke.py — end-to-end smoke test for the framework pipeline.

Port of smoke.sh. Runs the full installation, scanner, dep-graph,
module-writer, serena-call, items_verify, scratch and klc-phase-loop
blocks against the tiny-py fixture. Cross-platform: no bash, no
jq, no find/sed/awk. Every subprocess call uses sys.executable so
Windows 'python.exe' works identically.

Usage:   python tests/smoke.py [--keep]
  --keep  leave the scratch dir behind for inspection.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FW_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = FW_ROOT / "tests" / "fixtures" / "tiny-py"

SCRATCH: Path | None = None
KEEP = False


def say(msg: str) -> None:
    print(f"[smoke] {msg}")


def fail(msg: str) -> None:
    sys.stderr.write(f"[smoke] FAIL: {msg}\n")
    if KEEP and SCRATCH:
        sys.stderr.write(f"[smoke] scratch preserved at {SCRATCH}\n")
    sys.exit(1)


def _run(argv: list[str], *, cwd: Path | None = None,
         env: dict[str, str] | None = None,
         input_text: str | None = None,
         check: bool = True,
         capture: bool = True) -> subprocess.CompletedProcess:
    """Thin wrapper around subprocess.run that fails the test on
    non-zero exit when check=True."""
    r = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        input=input_text,
        capture_output=capture,
        text=True,
        timeout=180,
    )
    if check and r.returncode != 0:
        stderr = r.stderr or ""
        fail(f"{argv[:3]}... exited {r.returncode}: {stderr.strip()[:500]}")
    return r


def _py(script: Path, *args: str, cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
        check: bool = True,
        capture: bool = True) -> subprocess.CompletedProcess:
    """Run a Python script via sys.executable."""
    return _run([sys.executable, str(script), *args], cwd=cwd, env=env,
                input_text=input_text, check=check, capture=capture)


# -- blocks -------------------------------------------------------------------

def block_01_file_scanner(scratch: Path, env: dict[str, str]) -> None:
    say("1/4 file_scanner")
    r = _py(FW_ROOT / "core" / "skills" / "file_scanner.py",
            cwd=scratch, env=env)
    struct_path = scratch / ".klc" / "index" / "structural.json"
    struct_path.write_text(r.stdout, encoding="utf-8")
    try:
        json.loads(struct_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        fail("structural.json did not parse")


def block_02_dep_graph(scratch: Path, env: dict[str, str]) -> None:
    say("2/4 dep_graph")
    r = _py(FW_ROOT / "core" / "skills" / "dep_graph.py",
            cwd=scratch, env=env)
    dep_path = scratch / ".klc" / "index" / "depgraph.json"
    dep_path.write_text(r.stdout, encoding="utf-8")
    d = json.loads(dep_path.read_text(encoding="utf-8"))
    ig = d.get("import_graphs", {}).get("python", {})
    if not ig or not ig.get("nodes"):
        fail("depgraph.json lacks python import graph")


def block_03_synthetic_inventory(scratch: Path) -> None:
    """Synthesise inventory.json + modules.json from structural +
    depgraph so downstream skills have enough data to run."""
    say("3/4 synthetic inventory + modules")
    struct = json.loads((scratch / ".klc" / "index" / "structural.json").read_text(encoding="utf-8"))
    dep    = json.loads((scratch / ".klc" / "index" / "depgraph.json").read_text(encoding="utf-8"))

    modules: list[dict] = []
    symbols: list[dict] = []
    for sr in struct.get("source_roots") or []:
        path_rel = sr["path"].rstrip("/") + "/"
        items: list[dict] = []
        for py_path in sorted(Path(scratch / sr["path"]).rglob("*.py")):
            name = py_path.stem
            if name.startswith("_"):
                continue
            items.append({
                "name":      name,
                "kind":      "file",
                "file":      str(py_path).replace("\\", "/"),
                "line":      1,
                "signature": "",
            })
        modules.append({
            "name":         sr["module"],
            "path":         path_rel,
            "language":     "python",
            "entry":        None,
            "source":       "smoke",
            "public_api":   [i["name"] for i in items],
            "symbol_count": len(items),
            "depends_on":   [],
            "depended_by":  [],
        })
        symbols.extend(items)

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inventory = {
        "generated_at":    now,
        "git_sha":         "smoke",
        "root":            struct["root"],
        "profile":         struct["profile"],
        "structural":      struct,
        "depgraph":        dep,
        "source_of_truth": {"python": "regex_fallback"},
        "symbols": {
            "python": {"mode": "detailed", "count": len(symbols), "items": symbols},
        },
        "notes": ["smoke-test synthesized inventory"],
    }
    (scratch / ".klc" / "index" / "inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8")
    (scratch / ".klc" / "index" / "modules.json").write_text(
        json.dumps({
            "generated_at": now, "git_sha": "smoke",
            "modules": modules, "cycles": [], "notes": [],
        }, indent=2), encoding="utf-8")


def block_04_public_api(scratch: Path, env: dict[str, str]) -> None:
    say("4/4 public-api-filter + module-writer --all")
    _py(FW_ROOT / "core" / "skills" / "public-api-filter.py", env=env)
    _py(FW_ROOT / "core" / "skills" / "module-writer.py", "--all", env=env)


def block_05_per_module_hash(scratch: Path, env: dict[str, str]) -> None:
    p = scratch / ".klc" / "index" / "per-module-hash.json"
    if not p.exists():
        fail("per-module-hash.json not materialized")
    r = _py(FW_ROOT / "core" / "skills" / "per_module_hash.py", "diff",
            env=env)
    d = json.loads(r.stdout)
    if d["changed"] or d["added"] or d["removed"]:
        fail(f"steady state reports drift: {d}")

    mods_path = scratch / ".klc" / "index" / "modules.json"
    mods = json.loads(mods_path.read_text(encoding="utf-8"))
    if not mods.get("modules"):
        fail("no modules to perturb")
    target = mods["modules"][0]["name"]
    mods["modules"][0]["public_api"] = list(
        mods["modules"][0].get("public_api", []) or []) + ["__smoke_sentinel__"]
    mods_path.write_text(json.dumps(mods, indent=2), encoding="utf-8")
    r = _py(FW_ROOT / "core" / "skills" / "per_module_hash.py", "diff",
            env=env)
    d = json.loads(r.stdout)
    if target not in d["changed"]:
        fail(f"expected {target} in changed; got {d}")
    _py(FW_ROOT / "core" / "skills" / "module-writer.py", "--only", target,
        env=env)


def block_06_claude_md(scratch: Path) -> None:
    if not (scratch / "CLAUDE.md").exists():
        fail("root CLAUDE.md not written")
    mods = json.loads(
        (scratch / ".klc" / "index" / "modules.json").read_text(encoding="utf-8")
    ).get("modules", [])
    missing: list[str] = []
    for m in mods:
        doc = Path(scratch / m["path"]) / (m.get("doc_filename") or "CLAUDE.md")
        if not doc.exists():
            missing.append(str(doc))
    if missing:
        fail(f"missing module CLAUDE.md files: {missing}")


def block_07_symbols_by_module(scratch: Path) -> None:
    p = scratch / ".klc" / "index" / "symbols_by_module.json"
    if not p.exists():
        fail("symbols_by_module.json not written")
    payload = json.loads(p.read_text(encoding="utf-8"))
    idx = payload.get("modules") or {}
    mods = json.loads(
        (scratch / ".klc" / "index" / "modules.json").read_text(encoding="utf-8")
    ).get("modules", [])
    for m in mods:
        if m["name"] not in idx:
            fail(f"module {m['name']!r} absent from symbols_by_module.json")


def block_08_context_loader(scratch: Path, env: dict[str, str]) -> None:
    inv = scratch / ".klc" / "index" / "inventory.json"
    backup = inv.with_suffix(".bak")
    shutil.move(str(inv), str(backup))
    try:
        mods = json.loads(
            (scratch / ".klc" / "index" / "modules.json").read_text(encoding="utf-8")
        ).get("modules", [])
        if not mods:
            fail("no modules to check")
        names = ",".join(m["name"] for m in mods[:1])
        r = _py(FW_ROOT / "core" / "skills" / "context-loader.py",
                "--modules", names, "--format", "json", env=env)
        out = json.loads(r.stdout)
        if out.get("included_modules") is None:
            fail("context-loader output missing included_modules")
    finally:
        shutil.move(str(backup), str(inv))


def block_09_serena_call(scratch: Path, env: dict[str, str]) -> None:
    ticket = "TICK-serena"
    tdir = scratch / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)

    def _serena(*args: str, expect_ok: bool = True) -> tuple[str, int]:
        r = _py(FW_ROOT / "core" / "skills" / "serena-call.py", *args,
                env=env, check=expect_ok)
        return (r.stdout.strip(), r.returncode)

    (tdir / "meta.json").write_text(json.dumps({
        "ticket": ticket, "track": "M", "phase": "build:work",
    }), encoding="utf-8")

    out, _ = _serena("check", "--ticket", ticket, "--phase", "build",
                     "--op", "get_hover_info", "--subject", "foo")
    if not out.startswith("ALLOWED"):
        fail(f"expected ALLOWED, got: {out}")

    pl = scratch / ".klc" / "tickets" / ticket / "payload.json"
    pl.write_text(json.dumps({"signature": "foo(x: int) -> bool"}),
                  encoding="utf-8")
    _serena("save", "--ticket", ticket, "--op", "get_hover_info",
            "--subject", "foo", "--payload", str(pl))
    out, _ = _serena("check", "--ticket", ticket, "--phase", "build",
                     "--op", "get_hover_info", "--subject", "foo")
    if not out.startswith("CACHED "):
        fail(f"expected CACHED, got: {out}")

    (tdir / "meta.json").write_text(json.dumps({
        "ticket": ticket, "track": "XS", "phase": "build:work",
    }), encoding="utf-8")
    out, _ = _serena("check", "--ticket", ticket, "--phase", "build",
                     "--op", "get_hover_info", "--subject", "foo")
    if not out.startswith("DENIED "):
        fail(f"expected DENIED for XS, got: {out}")

    (tdir / "meta.json").write_text(json.dumps({
        "ticket": ticket, "track": "S", "phase": "design:work",
    }), encoding="utf-8")
    out, _ = _serena("check", "--ticket", ticket, "--phase", "design",
                     "--op", "get_hover_info", "--subject", "foo")
    if not out.startswith("DENIED "):
        fail(f"expected DENIED for S/design, got: {out}")

    (tdir / "meta.json").write_text(json.dumps({
        "ticket": ticket, "track": "M", "phase": "build:work",
    }), encoding="utf-8")
    out, _ = _serena("check", "--ticket", ticket,
                     "--op", "get_hover_info", "--subject", "foo")
    if not (out.startswith("ALLOWED") or out.startswith("CACHED")):
        fail(f"expected ALLOWED/CACHED via fallback, got: {out}")

    # legacy fallback
    (tdir / "meta.json").write_text(json.dumps({
        "ticket": ticket, "track": "M", "phase": "build-pending",
    }), encoding="utf-8")
    out, _ = _serena("check", "--ticket", ticket,
                     "--op", "get_hover_info", "--subject", "foo")
    if not (out.startswith("ALLOWED") or out.startswith("CACHED")):
        fail(f"expected ALLOWED/CACHED via legacy fallback, got: {out}")

    out, _ = _serena("status", "--ticket", ticket)
    data = json.loads(out)
    if data.get("cache_files", 0) < 1 or data.get("denied-track", 0) < 1:
        fail(f"status counts off: {data}")


def block_10_serena_deny(scratch: Path, env: dict[str, str]) -> None:
    for t in ("TICK-a", "TICK-b", "TICK-c"):
        d = scratch / ".klc" / "tickets" / t
        d.mkdir(parents=True, exist_ok=True)
        rec = {"t": "2026-05-12T00:00:00Z", "event": "allowed",
               "op": "find_symbol", "subject": "AActor",
               "file": None, "line": None, "detail": ""}
        (d / "serena-calls.log").write_text(json.dumps(rec) + "\n",
                                              encoding="utf-8")

    def _sd(*args: str, expect_ok: bool = True) -> tuple[str, int]:
        r = _py(FW_ROOT / "core" / "skills" / "serena_deny.py", *args,
                env=env, check=expect_ok)
        return (r.stdout, r.returncode)

    out, _ = _sd("propose", "--min-tickets", "2")
    if "AActor" not in out:
        fail(f"propose did not surface AActor: {out}")

    _sd("add", "--pattern", r"find_symbol\s+AActor",
        "--reason", "engine type")
    out, _ = _sd("list")
    if "AActor" not in out:
        fail(f"list missing newly added pattern: {out}")

    _, code = _sd("add", "--pattern", r"find_symbol\s+AActor",
                  "--reason", "engine type", expect_ok=False)
    if code == 0:
        fail("duplicate pattern accepted")

    _, code = _sd("add", "--pattern", "(bad",
                  "--reason", "x", expect_ok=False)
    if code == 0:
        fail("invalid regex accepted")

    out, _ = _sd("propose", "--min-tickets", "2")
    if "AActor" in out:
        fail(f"propose still lists covered entry: {out}")


def block_11_items_verify(scratch: Path, env: dict[str, str]) -> None:
    tdir = scratch / ".klc" / "tickets" / "TICK-fact"
    tdir.mkdir(parents=True, exist_ok=True)

    src = scratch / "src-fact"
    src.mkdir(exist_ok=True)
    stable = src / "stable.py"; stable.write_text("X = 1\n", encoding="utf-8")
    drift  = src / "drift.py";  drift.write_text("Y = 1\n", encoding="utf-8")

    if not (scratch / ".git").exists():
        _run(["git", "init", "-q"], cwd=scratch, env=env)
        _run(["git", "config", "user.email", "t@t"], cwd=scratch, env=env)
        _run(["git", "config", "user.name",  "t"], cwd=scratch, env=env)

    e = {**env,
         "GIT_AUTHOR_DATE":    "2026-05-01T00:00:00Z",
         "GIT_COMMITTER_DATE": "2026-05-01T00:00:00Z"}
    _run(["git", "add", "src-fact"], cwd=scratch, env=e)
    _run(["git", "commit", "-q", "-m", "seed"], cwd=scratch, env=e)

    (tdir / "spec.md").write_text("""
> [!FACT F-001] src=src-fact/stable.py:1 verified=2026-05-02
> Stable.

> [!FACT F-002] src=src-fact/drift.py:1 verified=2026-05-02
> Will drift.

> [!FACT F-003] verified=2026-05-02
> No src.
""", encoding="utf-8")

    e2 = {**e,
          "GIT_AUTHOR_DATE":    "2026-05-02T00:00:00Z",
          "GIT_COMMITTER_DATE": "2026-05-02T00:00:00Z"}
    _run(["git", "add", ".klc"], cwd=scratch, env=e2)
    _run(["git", "commit", "-q", "-m", "spec"], cwd=scratch, env=e2)

    drift.write_text("Y = 99\n", encoding="utf-8")
    e3 = {**e,
          "GIT_AUTHOR_DATE":    "2026-05-10T00:00:00Z",
          "GIT_COMMITTER_DATE": "2026-05-10T00:00:00Z"}
    _run(["git", "add", "src-fact/drift.py"], cwd=scratch, env=e3)
    _run(["git", "commit", "-q", "-m", "drift"], cwd=scratch, env=e3)

    r = _py(FW_ROOT / "core" / "skills" / "items_verify.py",
            "scan", "--top", "10", env=env)
    summary = json.loads(r.stdout)
    expected = {"confirmed": 1, "needs-review": 1, "undecidable": 1}
    if summary.get("counts") != expected:
        fail(f"expected counts {expected}, got {summary}")

    today = _dt.date.today().isoformat()
    text = (tdir / "spec.md").read_text(encoding="utf-8")
    if f"F-001] src=src-fact/stable.py:1 verified={today}" not in text:
        fail("F-001 not refreshed to today")
    if f"F-002] src=src-fact/drift.py:1 verified=stale-{today}" not in text:
        fail("F-002 not marked stale")
    if "F-003] verified=2026-05-02" not in text:
        fail("F-003 header was unexpectedly modified")

    log = scratch / ".klc" / "knowledge" / "verification-log.jsonl"
    if not log.exists():
        fail("verification-log.jsonl missing")
    records = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x]
    if len([r for r in records if r["id"] in {"F-001","F-002","F-003"}]) < 3:
        fail(f"expected >= 3 records, got {records}")


def block_12_scratch(scratch: Path, env: dict[str, str]) -> None:
    ticket = "TICK-smoke"

    def _s(*args: str) -> str:
        r = _py(FW_ROOT / "core" / "skills" / "scratch.py", *args, env=env)
        return r.stdout

    out = _s("new", "--ticket", ticket, "--agent", "smoke",
             "--phase", "build", "--purpose", "verify scratch round-trip")
    if not out.startswith("SCRATCH_NEW "):
        fail(f"expected SCRATCH_NEW, got: {out}")
    first = out.strip().split(" ", 1)[1]
    if "001-" not in first:
        fail(f"session numbering wrong: {first}")

    listed = _s("list", "--ticket", ticket).strip().splitlines()
    if not any(first in line for line in listed):
        fail(f"list missing new session: {listed}")

    read = _s("read", "--ticket", ticket)
    if "BEGIN SESSION 001-" not in read or "END SESSION 001-" not in read:
        fail("read-back envelope missing")

    arc = _s("archive", "--ticket", ticket).strip()
    if not arc.startswith("SCRATCH_ARCHIVED "):
        fail(f"archive did not run: {arc}")
    live = scratch / ".klc" / "tickets" / ticket / "scratch"
    if live.exists():
        fail(f"scratch/ still present after archive: {live}")
    arc_dir = Path(arc.split(" ", 1)[1])
    if not any(p.name.startswith("001-") for p in arc_dir.iterdir()):
        fail("archived session not preserved")


def block_13_phase_loop(scratch: Path, env: dict[str, str]) -> None:
    """XS phase loop: intake → build → review → integrate → learn → archive."""
    say("phase loop (XS): intake → build → review → integrate → learn → archive")
    klc = scratch / ".klc" / "bin" / "klc"

    if not (scratch / ".git").exists():
        _run(["git", "init", "-q"], cwd=scratch, env=env)
        _run(["git", "config", "user.email", "t@t"], cwd=scratch, env=env)
        _run(["git", "config", "user.name",  "t"], cwd=scratch, env=env)

    # best-effort commit; scratch may have items created by earlier blocks
    _run(["git", "add", "-A"], cwd=scratch, env=env, check=False)
    _run(["git", "commit", "-q", "-m", "scratch init"],
         cwd=scratch, env=env, check=False)

    _klc(klc, ["intake", "SMK-1", "--kind", "feature",
               "Verify phase loop end-to-end"], env)
    tdir = scratch / ".klc" / "tickets" / "SMK-1"

    meta_path = tdir / "meta.json"
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    m["track"] = "XS"
    meta_path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    _klc(klc, ["ack", "SMK-1", "--pick", "1"], env)
    (tdir / "spec.md").write_text(
        "# SMK-1\n## AC\n1. AC-1: package builds.\n",
        encoding="utf-8",
    )
    _set_state(scratch, "SMK-1", "build", "ack-needed")
    _klc(klc, ["ack", "SMK-1", "--pick", "1"], env)

    (tdir / "review-report.md").write_text("# review\nAPPROVED.\n", encoding="utf-8")
    _set_state(scratch, "SMK-1", "review", "ack-needed")
    _klc(klc, ["ack", "SMK-1", "--pick", "1"], env)

    _set_state(scratch, "SMK-1", "integrate", "ack-needed")
    _klc(klc, ["ack", "SMK-1", "--pick", "1"], env)

    (tdir / "retrospective.md").write_text(
        "# retrospective\nsmoke loop succeeded.\n", encoding="utf-8",
    )
    _set_state(scratch, "SMK-1", "learn", "ack-needed")
    _klc(klc, ["ack", "SMK-1", "--pick", "1"], env)

    m = json.loads(meta_path.read_text(encoding="utf-8"))
    if m.get("phase") != "archived":
        fail(f"expected phase=archived, got {m.get('phase')}")
    say("phase loop OK")


def block_14_ops_commands(scratch: Path, env: dict[str, str]) -> None:
    say("exercising: status / next / abort / jump")
    klc = scratch / ".klc" / "bin" / "klc"
    _klc(klc, ["intake", "SMK-2", "--kind", "feature", "jump/abort exercise"], env)
    tdir = scratch / ".klc" / "tickets" / "SMK-2"
    meta_path = tdir / "meta.json"
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    m["track"] = "M"
    meta_path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    r = _run_klc(klc, ["status", "SMK-2"], env)
    out = r.stdout
    for needle in ("discovery", "detailed-test-plan", "ack-needed"):
        if needle not in out:
            fail(f"status output missing {needle!r}")

    _klc(klc, ["ack", "SMK-2", "--pick", "1"], env)

    _klc(klc, ["abort", "SMK-2"], env)
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    if m["phase"] != "intake:ack":
        fail(f"expected intake:ack, got {m['phase']}")

    r = _run_klc(klc, ["jump", "build", "SMK-2"], env)
    if "jump plan" not in r.stdout:
        fail("jump dry-run missing plan")
    _klc(klc, ["jump", "build", "SMK-2", "--yes"], env)
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    if m["phase"] != "build:work":
        fail(f"expected build:work, got {m['phase']}")
    say("ops commands OK")


# -- klc shim helpers ---------------------------------------------------------

def _klc(klc: Path, args: list[str], env: dict[str, str]) -> None:
    """Run the bash shim on POSIX, python dispatcher directly on
    Windows. Either way, same subprocess contract."""
    if sys.platform == "win32":
        argv = [sys.executable, str(FW_ROOT / "scripts" / "klc"), *args]
    else:
        argv = [str(klc), *args]
    _run(argv, env=env)


def _run_klc(klc: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    if sys.platform == "win32":
        argv = [sys.executable, str(FW_ROOT / "scripts" / "klc"), *args]
    else:
        argv = [str(klc), *args]
    return _run(argv, env=env)


def _set_state(scratch: Path, ticket: str, phase_id: str, state: str) -> None:
    """Write meta.json:phase via lifecycle.set_state() — bypasses the
    agent step to exercise the ack/integrate/learn transitions."""
    env = {**os.environ, "PROJECT_ROOT": str(scratch)}
    _run([
        sys.executable, "-c",
        "import sys, os; "
        f"sys.path.insert(0, {str(FW_ROOT / 'core' / 'skills')!r}); "
        "import lifecycle; "
        f"lifecycle.set_state({ticket!r}, {phase_id!r}, {state!r}, event='smoke')",
    ], env=env)


# -- harness ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true",
                    help="leave the scratch dir behind on exit.")
    args = ap.parse_args()
    global SCRATCH, KEEP
    KEEP = args.keep

    if not FIXTURE.is_dir():
        sys.stderr.write(f"smoke: fixture missing at {FIXTURE}\n")
        return 2

    SCRATCH = Path(tempfile.mkdtemp())
    try:
        # copy fixture
        for item in FIXTURE.iterdir():
            dst = SCRATCH / item.name
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        # install framework shims
        _py(FW_ROOT / "scripts" / "klc", "install", str(SCRATCH), capture=True)

        env = {**os.environ, "PROJECT_ROOT": str(SCRATCH),
               "KLC_FW": str(FW_ROOT)}

        say(f"scratch: {SCRATCH}")

        block_01_file_scanner(SCRATCH, env)
        block_02_dep_graph(SCRATCH, env)
        block_03_synthetic_inventory(SCRATCH)
        block_04_public_api(SCRATCH, env)
        block_05_per_module_hash(SCRATCH, env)
        block_06_claude_md(SCRATCH)
        block_07_symbols_by_module(SCRATCH)
        block_08_context_loader(SCRATCH, env)
        block_09_serena_call(SCRATCH, env)
        block_10_serena_deny(SCRATCH, env)
        block_11_items_verify(SCRATCH, env)
        block_12_scratch(SCRATCH, env)
        block_13_phase_loop(SCRATCH, env)
        block_14_ops_commands(SCRATCH, env)

        say("OK")
        return 0
    finally:
        if SCRATCH and not KEEP:
            shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
