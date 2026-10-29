"""E3b: packaged-runtime re-verification for the next-round 0.1.1 desktop build.

Launches the PACKAGED backends (win-unpacked/resources/runtime/backends/*) on isolated
loopback ports with FRESH writable data dirs (never touching the d6 package or the user's
installed instance), then re-runs the real-engine network-organization (E1e) and non-zero
Scope 3 (E2) acceptances against the packaged One, restarts One, and reads persisted state
back. Every child PID is recorded and only those PIDs are terminated.

Usage:
  python scripts/e3_packaged_runtime_verify.py \
      --installation D:/VibeCoding/releases/nebula-one/20261014-0.1.1-e3/win-unpacked \
      --data D:/VibeCoding/releases/nebula-one/20261014-0.1.1-e3/verification/fresh-data \
      --evidence .local-evidence/e3 [--phase discover|verify]
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# desktop/runtime.cjs scrubs these inherited prefixes so a developer's database / API /
# licensed-runtime config can never leak into the packaged sidecars.
_ENV_SCRUB = re.compile(r"^(NEBULA_|DATABASE_URL$|DATA_PLATFORM_|AUTO_BOOTSTRAP_|AUTO_STARTUP_)")


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not _ENV_SCRUB.match(k)}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _EditorServer:
    """Minimal static stand-in for the Electron editor server (e1e/e2 drive the One API and
    the engine directly, so the editor only needs to exist as a live origin)."""

    def __init__(self, editor_dir: Path):
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(editor_dir))
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.origin = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()


def _raw_get(url: str, timeout: float = 10.0):
    """Return (status, body_bytes) via httpx, which auto-decompresses gzip/deflate the way
    the acceptance scripts' client does. urllib does not, and the packaged One gzips."""
    import httpx
    resp = httpx.get(url, timeout=timeout, headers={"Accept": "application/json"}, trust_env=False)
    return resp.status_code, resp.content


def _get(url: str, timeout: float = 10.0):
    status, raw = _raw_get(url, timeout)
    if status >= 400:
        raise RuntimeError(f"HTTP {status} from {url}: {raw[:200]!r}")
    return json.loads(raw.decode("utf-8"))


def _wait_ready(url: str, label: str, deadline_s: float = 240.0) -> bool:
    """Ready once the port answers HTTP at all. Any status (200/404/401) means uvicorn is
    serving; only a refused connection / timeout means the port is not bound yet. The
    packaged LCA seeds its ef31 runtime BEFORE uvicorn.run, so first boot can take a while."""
    import httpx
    end = time.time() + deadline_s
    last = ""
    while time.time() < end:
        try:
            status, _ = _raw_get(url, timeout=4.0)
            print(f"[ready] {label} at {url} (HTTP {status})", flush=True)
            return True
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2.0)
        except Exception as exc:  # noqa: BLE001
            # Any HTTP-level answer (even 4xx/5xx) means the server is up.
            print(f"[ready] {label} at {url} ({type(exc).__name__} = server up)", flush=True)
            return True
    print(f"[NOT ready] {label} at {url}: {last}", flush=True)
    return False


def _launch_lca(installation: Path, data: Path, lca_port: int):
    """Replicate desktop/runtime.cjs's LCA sidecar env exactly. Without the reference
    bootstrap profile + tidas snapshots + startup maintenance, a fresh packaged LCA leaves
    the engine catalog incomplete and One's seed install refuses with
    SEED_VERIFY_PRESENT_OBSERVATION_DRIFT (CO2 flow resolves as tidas_import, unit groups
    lose their source metadata)."""
    runtime = installation / "resources" / "runtime"
    lca_exe = runtime / "backends" / "nebula-lca-api" / "nebula-lca-api.exe"
    lca_data = data / "lca"
    lca_data.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((runtime / "payload-manifest.json").read_text(encoding="utf-8"))
    internal = runtime / "backends" / "nebula-lca-api" / "_internal"
    env = _clean_env()
    env.update({
        "NEBULA_DESKTOP": "1",
        "NEBULA_DATA_DIR": str(lca_data),
        "NEBULA_API_PORT": str(lca_port),
        "AUTO_BOOTSTRAP_REFERENCE_DATA_ON_STARTUP": "false",
        "AUTO_STARTUP_MAINTENANCE_ON_STARTUP": "true",
        "NEBULA_LCA_EF31_DIR": str(internal / "data" / "EF3.1"),
        "NEBULA_PROVIDER_ELEMENTARY_CATALOG_PATH": str(runtime / "config" / "desktop_elementary_catalog.v1.csv"),
        "NEBULA_REFERENCE_BOOTSTRAP_PROFILE": str(runtime / "config" / "desktop_elementary_catalog.v1.provenance.json"),
        "NEBULA_LCA_ENGINE_COMMIT": str(manifest.get("lca_commit", "")),
        "NEBULA_PROVIDER_TIDAS_FLOW_SNAPSHOT_PATH": str(runtime / "config" / "desktop_tiangong_open_flows.v1.json"),
        "NEBULA_PROVIDER_TIDAS_REFERENCE_DEPENDENCY_SNAPSHOT_PATH": str(internal / "data" / "provider_profiles" / "steel_tiangong_open_references.v1.json"),
    })
    log = open(data / "lca-boot.log", "w", encoding="utf-8")
    proc = subprocess.Popen([str(lca_exe)], env=env, cwd=str(lca_exe.parent),
                            stdout=log, stderr=subprocess.STDOUT, text=True)
    return proc, runtime


def _launch_one(runtime: Path, data: Path, one_port: int, lca_origin: str, editor_origin: str):
    one_exe = runtime / "backends" / "nebula-one-api" / "nebula-one-api.exe"
    one_data = data / "one"
    one_data.mkdir(parents=True, exist_ok=True)
    env = _clean_env()
    env.update({
        "NEBULA_ONE_PORT": str(one_port),
        "NEBULA_ONE_DESKTOP_RESOURCES": str(runtime),
        "NEBULA_ONE_DESKTOP_DATA": str(one_data),
        "NEBULA_ONE_DESKTOP_ENGINE_ENDPOINT": lca_origin,
        "NEBULA_LCA_EDITOR_URL": editor_origin,
        "NEBULA_LCA_TRUSTED_SOURCE_URLS": lca_origin,
    })
    log = open(data / "one-boot.log", "w", encoding="utf-8")
    proc = subprocess.Popen([str(one_exe)], env=env, cwd=str(one_exe.parent),
                            stdout=log, stderr=subprocess.STDOUT, text=True)
    return proc


def _items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("items") or []
    return []


def _find_grid_port(graph: dict) -> str | None:
    """Locate the steel model's purchased-electricity input port. The consumer-exchange identity is
    `{node_id}::{port_id}` (see services/flow_display.py). Prefer the ore-sintering node so the
    discovered port matches the E1e/E2 default; fall back to any grid-electricity-in input."""
    fallback = None
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        for port in node.get("inputs") or []:
            if isinstance(port, dict) and port.get("id") == "grid-electricity-in":
                candidate = f"{nid}::grid-electricity-in"
                if nid == "ore-sintering":
                    return candidate
                fallback = fallback or candidate
    return fallback


def _discover(one_url: str, lca_url: str) -> dict:
    """Discover the packaged seed's live identities over HTTP (never from the boot log alone).

    One side: walk /api/v1/applications -> system-models -> revisions[0] -> system-revisions/{rev}
    and pick the steel demo model that exposes a grid-electricity-in input port.
    Engine side: walk /api/projects and pick the supply project whose snapshot graph contains the
    tiangong-grid-2022 leaf node (the public grid leaf E1e/E2 pin as the Scope-2 background)."""
    out: dict = {"one_url": one_url, "lca_url": lca_url}

    apps = _items(_get(f"{one_url}/api/v1/applications"))
    out["applications"] = [{"id": a.get("id"), "name": a.get("name"),
                            "display_name": a.get("display_name")} for a in apps if isinstance(a, dict)]
    demo = None
    for app in apps:
        if not isinstance(app, dict):
            continue
        aid = app.get("id")
        try:
            models = _items(_get(f"{one_url}/api/v1/applications/{aid}/system-models"))
        except Exception as exc:  # noqa: BLE001
            out.setdefault("model_scan_errors", []).append(f"{aid}: {type(exc).__name__}: {exc}")
            continue
        for model in models:
            if not isinstance(model, dict):
                continue
            mid = model.get("id")
            try:
                revs = _items(_get(f"{one_url}/api/v1/system-models/{mid}/revisions"))
            except Exception:  # noqa: BLE001
                continue
            if not revs:
                continue
            rev0 = revs[0].get("id")
            try:
                detail = _get(f"{one_url}/api/v1/system-revisions/{rev0}")
            except Exception:  # noqa: BLE001
                continue
            port = _find_grid_port(detail.get("graph_snapshot") or {})
            if port:
                demo = {"app_id": aid, "model_id": mid, "rev0": rev0, "consumer_port": port,
                        "app_name": app.get("name"), "model_name": model.get("name"),
                        "revision_count": len(revs)}
                break
        if demo:
            break
    out["demo"] = demo

    supply = None
    engine_scan = []
    try:
        # include_resources=True is required: the public grid-leaf supply project is installed with
        # status="resource" (see services/public_supply_seed.py) and the bare /api/projects list
        # hides it. This mirrors NebulaLCAClient.list_provider_projects.
        projects = _items(_get(f"{lca_url}/api/projects?page=1&page_size=100&include_resources=true"))
        out["engine_project_count"] = len(projects)
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            pid = proj.get("project_id") or proj.get("id")
            version = proj.get("latest_version") or 1
            entry = {"project_id": pid, "name": proj.get("name"), "latest_version": version}
            try:
                snap = _get(f"{lca_url}/api/provider/v1/models/{pid}/versions/{version}/snapshot")
                nodes = (snap.get("graph") or {}).get("nodes") or []
                entry["node_ids"] = [n.get("id") for n in nodes if isinstance(n, dict)]
                if any(isinstance(n, dict) and n.get("id") == "tiangong-grid-2022" for n in nodes):
                    supply = {"supply_project": pid, "supply_version": version,
                              "supply_leaf_node": "tiangong-grid-2022", "name": proj.get("name")}
            except Exception as exc:  # noqa: BLE001
                entry["snapshot_error"] = f"{type(exc).__name__}: {exc}"
            engine_scan.append(entry)
    except Exception as exc:  # noqa: BLE001
        out["engine_error"] = f"{type(exc).__name__}: {exc}"
    out["engine_scan"] = engine_scan
    out["supply"] = supply
    return out


def _ids_from_discovery(discovery: dict) -> dict:
    demo = discovery.get("demo") or {}
    supply = discovery.get("supply") or {}
    return {
        "app_id": demo.get("app_id"),
        "model_id": demo.get("model_id"),
        "consumer_port": demo.get("consumer_port"),
        "supply_project": supply.get("supply_project"),
        "supply_version": supply.get("supply_version"),
        "supply_leaf_node": supply.get("supply_leaf_node"),
    }


def _run_acceptance(script: str, one_url: str, lca_url: str, ids: dict, evidence: Path,
                    port_flag: str) -> dict:
    """Run an acceptance script as a subprocess against the packaged stack with the DISCOVERED
    packaged IDs. Defaults inside the scripts are the dev seed's UUIDs, so every identity is
    overridden explicitly here. Returns rc + parsed verdict from the script's evidence JSON."""
    cmd = [sys.executable, str(REPO / "scripts" / script),
           "--url", one_url, "--engine-url", lca_url, "--evidence", str(evidence),
           "--model-id", ids["model_id"], "--app-id", ids["app_id"],
           "--supply-project", ids["supply_project"], "--supply-version", str(ids["supply_version"]),
           port_flag, ids["consumer_port"]]
    if script.startswith("e1e"):
        cmd += ["--supply-leaf-node", ids["supply_leaf_node"]]
    log_name = ("e1e-stdout.log" if script.startswith("e1e") else "e2-stdout.log")
    log = open(evidence / log_name, "w", encoding="utf-8")
    log.write("$ " + " ".join(cmd) + "\n\n")
    log.flush()
    proc = subprocess.run(cmd, cwd=str(REPO / "scripts"), stdout=log, stderr=subprocess.STDOUT, text=True)
    log.close()
    return {"script": script, "rc": proc.returncode, "stdout_log": str(evidence / log_name)}


def _verdict(evidence: Path, filename: str) -> dict:
    path = evidence / filename
    if not path.exists():
        return {"present": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"present": True, "status": data.get("status"), "counts": data.get("counts")}


def _frozen_record(evidence: Path, filename: str, kind: str) -> dict | None:
    """Extract the persisted record id + frozen content_sha256 an acceptance run produced, so the
    restart readback can prove the packaged One stored it durably (not just returned it once)."""
    path = evidence / filename
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if kind == "e1e":
        record_id = data.get("record_id")
        sha = (data.get("org") or {}).get("content_sha256")
    else:
        org = data.get("org") or {}
        record_id = org.get("id")
        sha = (org.get("result") or {}).get("content_sha256")
    if not record_id:
        return None
    return {"record_id": record_id, "content_sha256": sha}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--installation", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--phase", choices=["discover", "verify"], default="discover")
    args = ap.parse_args()

    installation = args.installation.resolve()
    data = args.data.resolve()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)

    lca_port = _free_port()
    one_port = _free_port()
    print(f"[launch] LCA port={lca_port} One port={one_port} phase={args.phase}", flush=True)
    one_url = f"http://127.0.0.1:{one_port}"
    lca_url = f"http://127.0.0.1:{lca_port}"
    report: dict = {"installation": str(installation), "data": str(data), "phase": args.phase,
                    "one_url": one_url, "lca_url": lca_url}
    lca_proc = one_proc = None
    editor = None
    runtime = None
    evidence_name = "packaged-verify.json" if args.phase == "verify" else "packaged-discovery.json"
    try:
        lca_proc, runtime = _launch_lca(installation, data, lca_port)
        report.setdefault("pids", {})["lca"] = lca_proc.pid
        if not _wait_ready(lca_url, "packaged LCA", 300.0):
            report["status"] = "lca_launch_failed"
            return 2
        report["lca_ready"] = True
        editor = _EditorServer(runtime / "editor").start()
        report["editor_origin"] = editor.origin
        # One's startup prepare_steel_catalog calls the engine, so LCA must be serving first.
        one_proc = _launch_one(runtime, data, one_port, lca_url, editor.origin)
        report["pids"]["one"] = one_proc.pid
        if not _wait_ready(f"{one_url}/api/v1/applications", "packaged One", 300.0):
            report["status"] = "one_launch_failed"
            return 2
        report["one_ready"] = True

        discovery = _discover(one_url, lca_url)
        report["discovery"] = discovery
        print(json.dumps(discovery, ensure_ascii=False, indent=2), flush=True)

        if args.phase == "discover":
            report["status"] = "discovered" if (discovery.get("demo") and discovery.get("supply")) \
                else "discovery_incomplete"
            return 0 if report["status"] == "discovered" else 2

        ids = _ids_from_discovery(discovery)
        report["ids"] = ids
        if not all(ids.get(k) for k in ("app_id", "model_id", "consumer_port",
                                        "supply_project", "supply_version", "supply_leaf_node")):
            report["status"] = "discovery_incomplete"
            return 2

        report["e1e_run"] = _run_acceptance("e1e_network_org_acceptance.py", one_url, lca_url,
                                            ids, evidence, "--consumer-port")
        report["e1e_verdict"] = _verdict(evidence, "e1e-network-org.json")
        report["e2_run"] = _run_acceptance("e2_nonzero_scope3_acceptance.py", one_url, lca_url,
                                           ids, evidence, "--grid-port")
        report["e2_verdict"] = _verdict(evidence, "e2-nonzero-scope3.json")
        print("[e1e]", report["e1e_run"]["rc"], report["e1e_verdict"], flush=True)
        print("[e2]", report["e2_run"]["rc"], report["e2_verdict"], flush=True)

        # Restart ONLY the packaged One against the SAME writable data dir (LCA + editor stay up so
        # One's engine-dependent startup succeeds), then read the persisted records back.
        report["restart"] = {}
        if one_proc is not None and one_proc.poll() is None:
            one_proc.terminate()
            try:
                one_proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                one_proc.kill()
        restart_port = _free_port()
        restart_url = f"http://127.0.0.1:{restart_port}"
        one_proc = _launch_one(runtime, data, restart_port, lca_url, editor.origin)
        report["pids"]["one_restarted"] = one_proc.pid
        report["restart"]["one_url"] = restart_url
        report["restart"]["ready"] = _wait_ready(f"{restart_url}/api/v1/applications", "restarted One", 300.0)
        if not report["restart"]["ready"]:
            report["status"] = "restart_failed"
            return 2

        readback = []
        for kind, filename in (("e1e", "e1e-network-org.json"), ("e2", "e2-nonzero-scope3.json")):
            frozen = _frozen_record(evidence, filename, kind)
            if not frozen:
                readback.append({"kind": kind, "status": "no_record"})
                continue
            try:
                got = _get(f"{restart_url}/api/v1/applications/{ids['app_id']}"
                           f"/organization-lifecycle-inventories/{frozen['record_id']}")
                same = got.get("content_sha256") == frozen["content_sha256"]
                readback.append({"kind": kind, "record_id": frozen["record_id"],
                                 "status": "pass" if same else "sha_mismatch",
                                 "frozen_sha256": frozen["content_sha256"],
                                 "readback_sha256": got.get("content_sha256")})
            except Exception as exc:  # noqa: BLE001
                readback.append({"kind": kind, "record_id": frozen["record_id"],
                                 "status": "readback_error", "error": f"{type(exc).__name__}: {exc}"})
        report["readback"] = readback
        print("[readback]", json.dumps(readback, ensure_ascii=False), flush=True)

        e1e_ok = report["e1e_run"]["rc"] == 0 and report["e1e_verdict"].get("status") == "pass"
        e2_ok = report["e2_run"]["rc"] == 0 and report["e2_verdict"].get("status") == "pass"
        rb_ok = all(r.get("status") == "pass" for r in readback) and len(readback) == 2
        report["status"] = "verified" if (e1e_ok and e2_ok and rb_ok) else "verify_failed"
        report["verdict"] = {"e1e": e1e_ok, "e2": e2_ok, "restart_readback": rb_ok}
        return 0 if report["status"] == "verified" else 2
    finally:
        for name, proc in (("one", one_proc), ("lca", lca_proc)):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if proc is not None:
                print(f"[stopped] {name} pid={proc.pid} rc={proc.returncode}", flush=True)
        if editor is not None:
            editor.stop()
        (evidence / evidence_name).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
