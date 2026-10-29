"""Isolated bring-up that proves real-engine demand linearity (guardrail #1).

Boots the source-built Nebula LCA engine and source Nebula One on isolated
loopback ports with fresh writable data directories (never touching the shared
stack, the user's installed instance on 6616, or any existing database), runs
scripts/verify_demand_linear_scaling.py against them, then terminates ONLY the
two child PIDs it recorded.

Usage (from the nebula-one repo):
  python scripts/linear_scaling_run.py \
      --engine-dir D:/VibeCoding/nebula-lca \
      --output .local-evidence/linear-scaling
"""
from __future__ import annotations

import argparse
import httpx
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Scrub inherited One/engine config so a developer environment can never leak into the
# isolated children (mirrors desktop/runtime.cjs and e3_packaged_runtime_verify).
_ENV_SCRUB = re.compile(r"^(NEBULA_|DATABASE_URL$|DATA_PLATFORM_|AUTO_BOOTSTRAP_|AUTO_STARTUP_)")


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not _ENV_SCRUB.match(k)}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, label: str, deadline_s: float) -> bool:
    end = time.time() + deadline_s
    last = ""
    while time.time() < end:
        try:
            resp = httpx.get(url, timeout=4.0, headers={"Accept": "application/json"}, trust_env=False)
            print(f"[ready] {label} at {url} (HTTP {resp.status_code})", flush=True)
            return True
        except (httpx.HTTPError,) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2.0)
    print(f"[NOT ready] {label} at {url}: {last}", flush=True)
    return False


def _terminate(proc: subprocess.Popen, label: str) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    print(f"[cleanup] terminated {label} pid={proc.pid}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-dir", type=Path,
                        default=Path("D:/VibeCoding/nebula-lca"), help="read-only Nebula LCA checkout")
    parser.add_argument("--ef31-dir", type=Path, default=None,
                        help="characterization runtime dir; defaults to the source build's solver-data/EF3.1")
    parser.add_argument("--engine-source", action="store_true",
                        help="boot the engine from source (uvicorn) instead of the packaged exe, so the "
                             "exe-bundled characterization runtime cannot be merged into the solve")
    parser.add_argument("--output", type=Path, default=REPO / ".local-evidence/linear-scaling")
    parser.add_argument("--base-amount", type=float, default=1000.0)
    parser.add_argument("--verifier", type=Path, default=REPO / "scripts/verify_demand_linear_scaling.py",
                        help="isolated acceptance script to run against the booted stack")
    args = parser.parse_args()

    python = sys.executable
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Absolute: the engine child runs with cwd=its own dist dir, so a relative NEBULA_DATA_DIR
    # would silently write the isolated data dir inside the engine checkout instead of the
    # evidence directory this run claims to own.
    run = args.output.resolve() / f"run-{tag}"
    lca_data = run / "lca"
    one_data = run / "one"
    lca_data.mkdir(parents=True, exist_ok=True)
    one_data.mkdir(parents=True, exist_ok=True)

    lca_port = _free_port()
    one_port = _free_port()
    lca_origin = f"http://127.0.0.1:{lca_port}"
    one_origin = f"http://127.0.0.1:{one_port}"

    api_dir = args.engine_dir / "nebula-lca-api"
    lca_exe = api_dir / "dist/nebula-lca-api/nebula-lca-api.exe"
    if not args.engine_source and not lca_exe.is_file():
        print(json.dumps({"refused": f"engine exe not found: {lca_exe}"}), file=sys.stderr)
        return 2
    # Point the runtime EF3.1 dir at the ecoinvent_category-bearing characterization
    # projection, not the LCIA-unit metadata dir (_internal/data/EF3.1); forcing the
    # latter as a runtime trips the engine's legacy indicator tie-out guard.
    if args.ef31_dir is not None:
        ef31 = args.ef31_dir.resolve()
    elif args.engine_source:
        # A source boot has no bundled default; refusing keeps the run's characterization
        # assets explicit instead of whatever the checkout happens to contain.
        print(json.dumps({"refused": "--engine-source requires --ef31-dir"}), file=sys.stderr)
        return 2
    else:
        ef31 = (lca_exe.parent / "_internal/solver-data/EF3.1").resolve()
    if not (ef31 / "flow_index.csv").is_file() or not (ef31 / "lcia_factors.csv").is_file():
        # Refuse rather than let the engine resolve some other dir: an acceptance run must state
        # which characterization assets produced its numbers.
        print(json.dumps({"refused": f"EF3.1 characterization runtime dir has no flow_index/lcia_factors: {ef31}"}),
              file=sys.stderr)
        return 2
    config = REPO / "desktop/resources/config"
    steel_refs = api_dir / "data/provider_profiles/steel_tiangong_open_references.v1.json"

    children: list[tuple[subprocess.Popen, str]] = []

    # 1. Engine (read-only source build, isolated data dir + port).
    lca_env = _clean_env()
    lca_env.update({
        "NEBULA_DESKTOP": "1",
        "NEBULA_DATA_DIR": str(lca_data),
        "NEBULA_API_PORT": str(lca_port),
        "AUTO_BOOTSTRAP_REFERENCE_DATA_ON_STARTUP": "false",
        "AUTO_STARTUP_MAINTENANCE_ON_STARTUP": "true",
        "NEBULA_LCA_EF31_DIR": str(ef31),
        "NEBULA_PROVIDER_ELEMENTARY_CATALOG_PATH": str(config / "desktop_elementary_catalog.v1.csv"),
        "NEBULA_REFERENCE_BOOTSTRAP_PROFILE": str(config / "desktop_elementary_catalog.v1.provenance.json"),
        "NEBULA_PROVIDER_TIDAS_FLOW_SNAPSHOT_PATH": str(config / "desktop_tiangong_open_flows.v1.json"),
        "NEBULA_PROVIDER_TIDAS_REFERENCE_DEPENDENCY_SNAPSHOT_PATH": str(steel_refs),
    })
    if args.engine_source:
        # Mirror desktop_entry.main() env defaults without calling it: desktop_entry would seed
        # the data dir from the checkout's runtime/ tree, which is exactly the bundled
        # characterization source this mode exists to keep out of the solve.
        lca_env.update({
            "PYTHONPATH": str(api_dir),
            "NEBULA_DB_PATH": str(lca_data / "nebula-lca.db"),
            "DATABASE_URL": "sqlite:///" + (lca_data / "nebula-lca.db").as_posix(),
            "NEBULA_LCA_RUNTIME_ROOT": str(lca_data / "runtime"),
            "NEBULA_IMPORT_CACHE_DIR": str(lca_data / "import-cache"),
        })
        lca_cmd = [python, "-B", "-m", "uvicorn", "app.main:app",
                   "--host", "127.0.0.1", "--port", str(lca_port), "--log-level", "info"]
        lca_cwd = api_dir
    else:
        lca_cmd = [str(lca_exe)]
        lca_cwd = lca_exe.parent
    lca_log = open(run / "lca-boot.log", "w", encoding="utf-8")
    lca_proc = subprocess.Popen(lca_cmd, env=lca_env, cwd=str(lca_cwd),
                                stdout=lca_log, stderr=subprocess.STDOUT, text=True)
    children.append((lca_proc, "engine"))
    print(f"[boot] engine pid={lca_proc.pid} at {lca_origin} "
          f"({'source' if args.engine_source else 'exe'})", flush=True)

    rc = 0
    try:
        if not _wait_http(f"{lca_origin}/openapi.json", "engine", 300.0):
            return 3

        # Mechanism evidence: /api/desktop/status reports the runtime CSV dirs the solver actually
        # merged (app/solver_adapter._resolve_embedded_ef31_dirs). Without it a passing number only
        # shows some characterization dir was used, not the one this run claims.
        status = httpx.get(f"{lca_origin}/api/desktop/status", timeout=20.0, trust_env=False).json()
        runtime = status.get("runtime") or {}
        sources = runtime.get("ef31_runtime_sources") or []
        (run / "engine-ef31-runtime-sources.json").write_text(
            json.dumps({"requested_ef31_dir": str(ef31), "runtime": runtime}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        for item in sources:
            print(f"[ef31-source] {item.get('flows_count')} flows: {item.get('path')}", flush=True)
        requested = str(ef31.resolve())
        merged = {str(Path(str(item.get("path"))).resolve()) for item in sources}
        if requested not in merged:
            print(json.dumps({"refused": f"engine did not load the requested EF3.1 dir {requested}; "
                                         f"merged sources: {sources}"}), file=sys.stderr)
            return 5
        if args.engine_source and merged != {requested}:
            # A source boot must characterize from the stated dir alone; any extra source means
            # the numbers are not attributable to the license-clean assets under test.
            print(json.dumps({"refused": f"engine-source run merged more than the requested dir: "
                                         f"{sorted(merged)}"}), file=sys.stderr)
            return 6

        # 2. One (source app, isolated DB + port, pointed at the isolated engine).
        one_env = _clean_env()
        one_env.update({
            "PYTHONPATH": str(REPO / "src"),
            "NEBULA_ONE_HOST": "127.0.0.1",
            "NEBULA_ONE_PORT": str(one_port),
            "NEBULA_ONE_DATABASE_URL": "sqlite:///" + (one_data / "nebula-one.db").as_posix(),
            "NEBULA_ONE_CASEPACK_ROOTS": str(REPO / "cases"),
            "NEBULA_LCA_BASE_URL": lca_origin,
            "NEBULA_LCA_EDITOR_URL": "",
            "NEBULA_ONE_SEED_AUTOLOAD_FILE": "",
        })
        one_log = open(run / "one-boot.log", "w", encoding="utf-8")
        one_proc = subprocess.Popen([python, "-B", "-m", "nebula_one"], env=one_env, cwd=str(REPO),
                                    stdout=one_log, stderr=subprocess.STDOUT, text=True)
        children.append((one_proc, "one"))
        print(f"[boot] one pid={one_proc.pid} at {one_origin}", flush=True)

        if not _wait_http(f"{one_origin}/api/v1/applications", "one", 120.0):
            return 4

        # 3. Run the verifier.
        verifier_args = [python, "-B", str(args.verifier),
                         "--one", one_origin, "--lca", lca_origin, "--output", str(run)]
        if args.verifier.name == "verify_demand_linear_scaling.py":
            verifier_args += ["--base-amount", str(args.base_amount)]
        verifier = subprocess.run(
            verifier_args, cwd=str(REPO), capture_output=True, text=True)
        print(verifier.stdout, flush=True)
        if verifier.stderr.strip():
            print(verifier.stderr, flush=True)
        (run / "verifier-stdout.txt").write_text(verifier.stdout, encoding="utf-8")
        (run / "verifier-stderr.txt").write_text(verifier.stderr, encoding="utf-8")
        rc = verifier.returncode
        print(f"[verifier] exit={rc}", flush=True)
    finally:
        for proc, label in children:
            _terminate(proc, label)

    print(f"[done] evidence in {run}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
