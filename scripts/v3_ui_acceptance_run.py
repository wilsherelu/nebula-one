"""Isolated bring-up that drives the REAL built web UI through the v3 acceptance harnesses.

Boots the Nebula LCA engine and the source One (serving web/dist) on isolated loopback ports with a
fresh writable SQLite + data dir (never touching the shared stack, the user's installed instance on
6616, or any existing database). Creates a real characterised steel PCF snapshot via the same live
EF3.1 mechanism used by verify_pcf_basis_reconciliation, then runs real headless Chrome against the
served UI and terminates ONLY the child PIDs it recorded:
  - scripts/ui_result_basis_acceptance.mjs  (v3 结果口径 toggle, req #2/#4)
  - scripts/ui_scope_editor_acceptance.mjs  (v3 逐流调整 + Scope 分类, req #4)
  - scripts/ui_v3_labels_acceptance.mjs     (v3 UI 文案/口径/缺口分行, req 二)

--engine-source boots the engine from uvicorn instead of the packaged exe and then REFUSES (exit 6)
unless /api/desktop/status shows the solver merged exactly the one --ef31-dir requested, so the UI
numbers stay attributable to the license-clean characterization assets instead of silently inheriting
the exe-bundled ecoinvent runtime (which wins merge order).

Usage (from the nebula-one repo, after `cd web && npm run build`):
  python scripts/v3_ui_acceptance_run.py \
      --engine-source \
      --engine-dir D:/VibeCoding/nebula-lca \
      --ef31-dir D:/VibeCoding/nebula-lca/nebula-lca-solver/data/EF3.1-public \
      --output .local-evidence/v3-ui-acceptance
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
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
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
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2.0)
    print(f"[NOT ready] {label} at {url}: {last}", flush=True)
    return False


def _terminate(proc: subprocess.Popen, label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    print(f"[cleanup] terminated {label} pid={proc.pid}", flush=True)


def _make_pcf_snapshot(one: str, lca: str, out: Path) -> dict:
    """Create a real EF3.1 characterised PCF snapshot and return {application_id, snapshot_id}.

    Reuses the exact synthetic single-process mechanism builder already proven in
    verify_pcf_basis_reconciliation: CO2 10 kg + CH4 0.1 kg from the live catalog, solved at demand
    1000 kg so the total and a per-kg intensity genuinely differ (the toggle is observable).
    """
    from verify_pcf_basis_reconciliation import _build_graph, _solve, _pcf, API, digest  # noqa: E402
    from live_user_method_acceptance import _request  # noqa: E402

    graph, product = _build_graph(lca)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    application = _request(one, "POST", f"{API}/applications", {
        "name": f"v3 UI result-basis {tag}", "application_type": "system_analysis",
        "description": "Artificial single-process mechanism UI acceptance; not a facility or regulatory result",
        "context": {}})
    app_id = application["id"]
    model = _request(one, "POST", f"{API}/applications/{app_id}/system-models/inline", {
        "name": "v3 UI result-basis process", "provider": "nebula_lca",
        "source_id": f"acceptance:v3-ui:{tag}", "source_version": 1,
        "expected_graph_sha256": digest(graph), "graph": graph})
    model_id = model["id"]
    rev_id = model["upstream_receipt"]["base_revision_id"]
    snap = _solve(one, app_id, rev_id, product, 1000.0, f"{tag}-ui1000")
    method_ref = "pcf.product.ef31.foreground@1.0.4"
    total = _pcf(one, snap["id"], method_ref)
    print(f"[ui-setup] total T={total['total_footprint']['value']} snapshot={snap['id']}", flush=True)
    # A user method bound to the exact revision drives the 逐流 Scope editor: its rows come from the
    # frozen graph_snapshot (two biosphere emissions = contributions, one product output = non-contribution).
    method = _request(one, "POST", f"{API}/applications/{app_id}/calculation-methods", {
        "name": f"v3 Scope editor {tag}", "purpose": "organization",
        "description": "Artificial per-flow Scope editor acceptance method; not a regulatory result",
        "model_revision_id": rev_id, "rules": []})
    method_id = method["method"]["id"]
    print(f"[ui-setup] scope method={method_id} model={model_id} revision={rev_id}", flush=True)
    return {"application_id": app_id, "system_revision_id": rev_id, "model_id": model_id,
            "method_id": method_id, "snapshot_id": snap["id"],
            "method_package_ref": method_ref, "total_footprint": total["total_footprint"]}


def _climate_indicator_row(ef31: Path) -> str:
    """The indicator_index row of the climate indicator, read from the loaded runtime."""
    import csv
    with (ef31 / "indicator_index.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            if "climate change" in (row.get("indicator_en") or "").casefold():
                return row["indicator_index"]
    raise RuntimeError(f"no climate-change indicator in {ef31 / 'indicator_index.csv'}")


def _uncharacterized_catalog_flow(ef31: Path, snapshot_path: Path) -> dict | None:
    """A catalog elementary flow the climate indicator gives NO factor for.

    Chosen from the characterization runtime this run actually loaded, from the provider catalog the
    engine resolves against, and from the TIDAS flow snapshot that supplies the exact version -- never
    hardcoded -- so the 未匹配因子 gap row has genuine content and the four separated gap reasons are
    exercised against a real solve instead of a fixture that happens to be clean.
    """
    import csv
    climate_row = _climate_indicator_row(ef31)
    flow_index: dict[str, int] = {}
    with (ef31 / "flow_index.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            flow_index[row["FlowUUID"]] = int(row["flow_index"])
    characterized: set[int] = set()
    with (ef31 / "lcia_factors.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            if row["row"] == climate_row:
                characterized.add(int(row["column"]))
    # The resolver matches an EXACT flow version, so the version has to come from the snapshot the
    # engine was pointed at; guessing one yields EXACT_FLOW_VERSION_NOT_FOUND.
    versions = {record["source_object_id"]: record["source_version"]
                for record in json.loads(snapshot_path.read_text(encoding="utf-8"))["records"]
                if record.get("dataset_kind") == "flow"}
    catalog = REPO / "desktop/resources/config/desktop_elementary_catalog.v1.csv"
    with catalog.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            index = flow_index.get(row["flow_uuid"])
            # A zero coefficient is a real zero (implicit_zero), not a missing factor, so only a
            # flow with no climate row at all can drive the 未匹配因子 bucket.
            if index is not None and index not in characterized and row["flow_uuid"] in versions:
                return {"exchange": "uncharacterized", "flow_uuid": row["flow_uuid"],
                        "version": versions[row["flow_uuid"]], "name_en": row["flow_name_en"],
                        "amount": 1.0}
    return None


def _make_labels_fixture(one: str, lca: str, app_id: str, ef31: Path, flow_snapshot: Path,
                         out: Path, method_ref: str) -> dict:
    """A second real snapshot whose PCF carries non-empty, SEPARATED coverage-gap buckets.

    Only the CO2 emission gets a rule, so CH4 stays 尚未设置规则 on its own row. Whether a catalog flow
    with no climate factor can also enter the model (and so fill 未匹配因子) is the engine's call, not
    ours: the resolver is asked first and its answer is recorded as `uncharacterized_probe`, so the
    harness reports that bucket as notRun with the engine's own refusal instead of inventing it.
    """
    import verify_pcf_basis_reconciliation as recon
    from verify_pcf_basis_reconciliation import _build_graph, _pcf, API, digest
    from live_user_method_acceptance import _create_validate_method, _request, _rule

    extra = _uncharacterized_catalog_flow(ef31, flow_snapshot)
    # Whether that flow can actually enter a model is the engine's call, not ours: ask it, and keep
    # the answer as the ground truth for why the 未匹配因子 bucket is or is not reachable here.
    probe = None
    if extra is not None:
        resolution = _request(lca, "POST", "/api/provider/v1/catalog/resolve", {
            "flows": [dict(source_namespace="tiangong_open_data", flow_uuid=extra["flow_uuid"],
                           version=extra["version"])]})
        item = (resolution.get("items") or [{}])[0]
        probe = {"flow": extra, "status": item.get("status"), "code": item.get("code"),
                 "message": item.get("message")}
        print(f"[ui-setup] uncharacterized-flow probe: {item.get('status')} {item.get('code')}", flush=True)
    original = list(recon.GASES)
    try:
        # _build_graph reads the module-level GASES; restore it so the numeric gate's own fixture
        # (CO2 10 kg + CH4 0.1 kg => T=12.98) is never affected by this labels-only addition.
        if probe and probe["status"] == "resolved":
            recon.GASES.append(dict(extra))
        graph, product = _build_graph(lca)
    finally:
        recon.GASES[:] = original
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    model = _request(one, "POST", f"{API}/applications/{app_id}/system-models/inline", {
        "name": "v3 UI gap-row process", "provider": "nebula_lca",
        "source_id": f"acceptance:v3-labels:{tag}", "source_version": 1,
        "expected_graph_sha256": digest(graph), "graph": graph})
    rev_id = model["upstream_receipt"]["base_revision_id"]
    method = _create_validate_method(one, app_id, rev_id, f"v3 labels {tag}", "pcf",
                                     [_rule("unit-process::co2", boundary_status="selected",
                                            scope="scope_1")])
    demand = [{"reference_flow_uuid": product["flowUuid"], "amount": 1000.0, "unit": product["unit"],
               "unit_group_uuid": product["unitGroupUuid"],
               "unit_group_version": product["unitGroupVersion"]}]
    # A BARE solve: no calculation_purpose. Naming one would make One derive the reviewed template's
    # rule package (MODEL_PROCESSING_TEMPLATE_UNBOUND for an inline model, which records no template),
    # and the grouping this fixture needs comes from the cited user method alone, which analysis_task
    # + calculation_method_ref already bind into the frozen receipt.
    snapshot = _request(one, "POST", f"{API}/applications/{app_id}/system-revisions/{rev_id}/solve", {
        "demand": demand, "idempotency_key": f"v3-labels-{tag}", "analysis_task": "pcf",
        "climate_default": True,
        "calculation_method_ref": {"method_id": method["method_id"], "version": method["version"],
                                   "content_sha256": method["content_sha256"]}})
    pcf = _pcf(one, snapshot["id"], method_ref)
    grouping = (pcf.get("contribution_analysis") or {}).get("user_method_grouping") or {}
    fixture = {"uncharacterized_probe": probe, "model_id": model["id"],
               "system_revision_id": rev_id, "method": method, "snapshot_id": snapshot["id"],
               "execution_status": grouping.get("execution_status"),
               "coverage": grouping.get("coverage"),
               "total_footprint": pcf.get("total_footprint")}
    (out / "labels-fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    nonempty = {k: v for k, v in (grouping.get("coverage") or {}).items()
                if isinstance(v, list) and v}
    print(f"[ui-setup] labels snapshot={snapshot['id']} nonempty_gap_buckets={sorted(nonempty)}",
          flush=True)
    return fixture


def _make_template_project(one: str, tag: str) -> dict:
    """Create one template-locked project and return its identities.

    The 核算 dialog this harness has to read only exists on the 模型与数据 workbench, and
    ProjectWorkspacePage routes an application that is not template_locked to 情景比较 instead -- so the
    synthetic inline-model application this runner builds can never open it. Two ordinary user paths do
    get one: instantiating an installed project template, or materializing a case pack. Both are tried
    in that order rather than setting template_locked here, which only the seed/materialize/handoff
    services may write.
    """
    from live_user_method_acceptance import _request

    refusals: list[str] = []
    templates = (_request(one, "GET", "/api/v1/project-templates?lang=zh") or {}).get("items") or []
    for item in templates:
        sha = item.get("template_sha256")
        if not sha:
            refusals.append(f"template {item.get('id')}: no template_sha256 in the catalog item")
            continue
        try:
            project = _request(one, "POST", f"/api/v1/project-templates/{item['id']}/projects", {
                "name": f"v3 UI dialog {tag}", "project_key": str(uuid.uuid4()),
                "expected_template_sha256": sha})
        except Exception as exc:
            refusals.append(f"template {item.get('id')}: {type(exc).__name__}: {exc}")
            print(f"[ui-setup] project from template {item['id']} refused: {exc}", flush=True)
            continue
        app_id = project.get("application_id") or (project.get("application") or {}).get("id")
        model_id = project.get("system_model_id") or (project.get("system_model") or {}).get("id")
        rev_id = project.get("revision_id") or (project.get("base_revision") or {}).get("id")
        if app_id and not model_id:
            models = _request(one, "GET", f"/api/v1/applications/{app_id}/system-models")
            model_id = (models[0]["id"] if models else None)
        if model_id and not rev_id:
            revisions = _request(one, "GET", f"/api/v1/system-models/{model_id}/revisions")
            rev_id = (revisions[-1]["id"] if revisions else None)
        if not (app_id and model_id and rev_id):
            refusals.append(f"template {item.get('id')}: created project reported no model/revision")
            continue
        print(f"[ui-setup] dialog project={app_id} template={item['id']}", flush=True)
        # The dialog only renders its 计算所用方法 selector once the revision has a user method of the
        # selected purpose; without one there is no option list to read 内置方案（默认） from.
        method_error = None
        dialog_method_id = None
        try:
            created = _request(one, "POST", f"/api/v1/applications/{app_id}/calculation-methods", {
                "name": f"v3 UI dialog {tag}", "purpose": "pcf",
                "description": "Artificial method so the calculation dialog offers a choice; "
                               "not a regulatory result",
                "model_revision_id": rev_id, "rules": []})
            dialog_method_id = (created.get("method") or {}).get("id")
        except Exception as exc:
            method_error = f"{type(exc).__name__}: {exc}"
            print(f"[ui-setup] dialog project method refused: {method_error}", flush=True)
        return {"source": "project-template", "template_id": item["id"], "application_id": app_id,
                "model_id": model_id, "revision_id": rev_id, "method_id": dialog_method_id,
                "status": project.get("status"), "method_error": method_error}

    catalog = _request(one, "GET", "/api/v1/casepacks")
    for pack in catalog.get("items") or []:
        for case in pack.get("applications") or []:
            try:
                result = _request(
                    one, "POST",
                    f"/api/v1/casepacks/{pack['id']}/versions/{pack['version']}"
                    f"/application-cases/{case['id']}/versions/{case['version']}/materialize",
                    {"project_name": f"v3 UI dialog {tag}", "project_key": str(uuid.uuid4()),
                     "expected_case_pack_sha256": pack["case_pack_sha256"],
                     "expected_resolved_case_sha256": case["resolved_case_sha256"]})
            except Exception as exc:
                refusals.append(f"{pack['id']}/{case['id']}: {type(exc).__name__}: {exc}")
                print(f"[ui-setup] materialize {pack['id']}/{case['id']} refused: {exc}", flush=True)
                continue
            print(f"[ui-setup] dialog project={result['application']['id']} "
                  f"case_pack={pack['id']}", flush=True)
            return {"source": "casepack", "case_pack_id": pack["id"],
                    "application_case_id": case["id"],
                    "application_id": result["application"]["id"],
                    "model_id": result["system_model"]["id"],
                    "revision_id": result["base_revision"]["id"],
                    "project_name": result["application"].get("name"),
                    "status": result.get("status")}
    return {"skipped": "neither an installed project template nor an installed case pack could create "
                       "a template-locked project (pass --seed-demo to install the staged steel seed)",
            "refusals": refusals, "template_count": len(templates),
            "case_pack_count": len(catalog.get("items") or [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-dir", type=Path, default=Path("D:/VibeCoding/nebula-lca"))
    parser.add_argument("--ef31-dir", type=Path, default=None,
                        help="characterization runtime dir; defaults to the source build's solver-data/EF3.1")
    parser.add_argument("--output", type=Path, default=REPO / ".local-evidence/v3-ui-acceptance")
    parser.add_argument("--engine-source", action="store_true",
                        help="boot the engine from source (uvicorn) instead of the packaged exe, so the "
                             "exe-bundled characterization runtime cannot be merged into the solve")
    parser.add_argument("--skip-build-check", action="store_true")
    parser.add_argument("--seed-demo", action="store_true",
                        help="autoload the staged steel demo seed, so an installed project template "
                             "exists and the 核算 dialog checks can run on a template-locked project")
    parser.add_argument("--harness", action="append", default=None,
                        choices=["result-basis", "scope-editor", "labels"],
                        help="run only the named UI harness(es); default is all three")
    args = parser.parse_args()

    python = sys.executable
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Absolute: the engine child runs with cwd=its own dist dir, so a relative --output would put
    # the isolated data dir (and this run's evidence) inside the engine checkout.
    run = args.output.resolve() / f"run-{tag}"
    lca_data, one_data = run / "lca", run / "one"
    lca_data.mkdir(parents=True, exist_ok=True)
    one_data.mkdir(parents=True, exist_ok=True)

    web_dist = REPO / "web/dist"
    if not (web_dist / "index.html").is_file() and not args.skip_build_check:
        print(json.dumps({"refused": "web/dist/index.html missing; run `cd web && npm run build` first"}),
              file=sys.stderr)
        return 2

    lca_port, one_port = _free_port(), _free_port()
    lca_origin, one_origin = f"http://127.0.0.1:{lca_port}", f"http://127.0.0.1:{one_port}"

    api_dir = args.engine_dir / "nebula-lca-api"
    lca_exe = api_dir / "dist/nebula-lca-api/nebula-lca-api.exe"
    if not args.engine_source and not lca_exe.is_file():
        print(json.dumps({"refused": f"engine exe not found: {lca_exe}"}), file=sys.stderr)
        return 2
    if args.ef31_dir is not None:
        ef31 = args.ef31_dir.resolve()
    elif args.engine_source:
        # A source boot has no bundled default; refusing keeps the run's characterization assets
        # explicit instead of whatever the checkout happens to contain.
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
    flow_snapshot = config / "desktop_tiangong_open_flows.v1.json"

    lca_env = _clean_env()
    lca_env.update({
        "NEBULA_DESKTOP": "1", "NEBULA_DATA_DIR": str(lca_data), "NEBULA_API_PORT": str(lca_port),
        "AUTO_BOOTSTRAP_REFERENCE_DATA_ON_STARTUP": "false", "AUTO_STARTUP_MAINTENANCE_ON_STARTUP": "true",
        "NEBULA_LCA_EF31_DIR": str(ef31),
        "NEBULA_PROVIDER_ELEMENTARY_CATALOG_PATH": str(config / "desktop_elementary_catalog.v1.csv"),
        "NEBULA_REFERENCE_BOOTSTRAP_PROFILE": str(config / "desktop_elementary_catalog.v1.provenance.json"),
        "NEBULA_PROVIDER_TIDAS_FLOW_SNAPSHOT_PATH": str(config / "desktop_tiangong_open_flows.v1.json"),
        "NEBULA_PROVIDER_TIDAS_REFERENCE_DEPENDENCY_SNAPSHOT_PATH": str(steel_refs),
    })
    if args.engine_source:
        # Mirror desktop_entry.main() env defaults without calling it: desktop_entry would seed the
        # data dir from the checkout's runtime/ tree, which is exactly the bundled ecoinvent
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
    print(f"[boot] engine pid={lca_proc.pid} at {lca_origin} "
          f"({'source' if args.engine_source else 'exe'})", flush=True)

    one_proc = None
    rc = 0
    try:
        if not _wait_http(f"{lca_origin}/openapi.json", "engine", 300.0):
            return 3

        # Mechanism evidence: /api/desktop/status reports the characterization dirs the solver
        # actually merged. Without it a rendered UI number only shows SOME EF3.1 dir was used.
        status = httpx.get(f"{lca_origin}/api/desktop/status", timeout=20.0,
                           headers={"Accept": "application/json"}, trust_env=False).json()
        runtime = status.get("runtime") or {}
        sources = runtime.get("ef31_runtime_sources") or []
        (run / "engine-ef31-runtime-sources.json").write_text(
            json.dumps({"requested_ef31_dir": str(ef31), "runtime": runtime},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        for item in sources:
            print(f"[ef31-source] {item.get('flows_count')} flows: {item.get('path')}", flush=True)
        merged = {str(Path(str(item.get("path"))).resolve()) for item in sources}
        if str(ef31) not in merged:
            print(json.dumps({"refused": f"engine did not load the requested EF3.1 dir {ef31}; "
                                         f"merged sources: {sorted(merged)}"}), file=sys.stderr)
            return 5
        if args.engine_source and merged != {str(ef31)}:
            # A source run must characterize from the stated dir alone; any extra source means the
            # UI numbers are not attributable to the license-clean assets under test.
            print(json.dumps({"refused": f"engine-source run merged more than the requested dir: "
                                         f"{sorted(merged)}"}), file=sys.stderr)
            return 6

        one_env = _clean_env()
        one_env.update({
            "PYTHONPATH": str(REPO / "src"), "NEBULA_ONE_HOST": "127.0.0.1",
            "NEBULA_ONE_PORT": str(one_port),
            "NEBULA_ONE_DATABASE_URL": "sqlite:///" + (one_data / "nebula-one.db").as_posix(),
            "NEBULA_ONE_WEB_ROOT": str(web_dist), "NEBULA_ONE_CASEPACK_ROOTS": str(REPO / "cases"),
            "NEBULA_LCA_BASE_URL": lca_origin, "NEBULA_LCA_EDITOR_URL": "",
            "NEBULA_ONE_SEED_AUTOLOAD_FILE": (
                str(REPO / "desktop/resources/config/steel-demo.json") if args.seed_demo else ""),
        })
        if args.seed_demo:
            # desktop_entry.main() runs this BEFORE serving; skipping it is what made the seed install
            # refuse with SEED_VERIFY_PRESENT_OBSERVATION_DRIFT on a fresh engine library, because the
            # two seed-owned prerequisite flows it imports would then be absent. Mirroring the product's
            # own bootstrap keeps the guard intact instead of working around it.
            prep_log = open(run / "steel-catalog-prepare.log", "w", encoding="utf-8")
            prep = subprocess.run(
                [python, "-B", "-c",
                 "from nebula_one.seeds.prepare_steel_catalog import main; raise SystemExit(main())"],
                env=one_env, cwd=str(REPO), stdout=prep_log, stderr=subprocess.STDOUT, text=True)
            prep_log.close()
            print(f"[seed] prepare_steel_catalog exit={prep.returncode}", flush=True)
            if prep.returncode != 0:
                return 7

        one_log = open(run / "one-boot.log", "w", encoding="utf-8")
        one_proc = subprocess.Popen([python, "-B", "-m", "nebula_one"], env=one_env, cwd=str(REPO),
                                    stdout=one_log, stderr=subprocess.STDOUT, text=True)
        print(f"[boot] one pid={one_proc.pid} at {one_origin} (serving {web_dist})", flush=True)

        if not _wait_http(f"{one_origin}/api/v1/applications", "one", 120.0):
            return 4

        setup = _make_pcf_snapshot(one_origin, lca_origin, run)
        try:
            labels = _make_labels_fixture(one_origin, lca_origin, setup["application_id"], ef31,
                                          flow_snapshot, run, setup["method_package_ref"])
        except Exception as exc:  # a missing labels fixture must not destroy the other harnesses
            labels = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[ui-setup] labels fixture FAILED: {labels['error']}", flush=True)
        setup["labels_snapshot_id"] = labels.get("snapshot_id")
        setup["labels_model_id"] = labels.get("model_id")
        setup["labels_revision_id"] = labels.get("system_revision_id")
        setup["labels_skipped"] = labels.get("skipped") or labels.get("error")
        try:
            project = _make_template_project(one_origin, tag)
        except Exception as exc:  # a missing dialog project must not destroy the other harnesses
            project = {"skipped": f"{type(exc).__name__}: {exc}"}
            print(f"[ui-setup] dialog project FAILED: {project['skipped']}", flush=True)
        setup["dialog_application_id"] = project.get("application_id")
        setup["dialog_model_id"] = project.get("model_id")
        setup["dialog_revision_id"] = project.get("revision_id")
        setup["dialog_method_id"] = project.get("method_id")
        setup["dialog_skipped"] = project.get("skipped")
        setup["dialog_method_error"] = project.get("method_error")
        (run / "ui-dialog-project.json").write_text(
            json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
        (run / "ui-setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2), encoding="utf-8")

        harnesses = args.harness or ["result-basis", "scope-editor", "labels"]
        harness = {
            "result-basis": ("ui_result_basis_acceptance.mjs",
                             [setup["application_id"], setup["snapshot_id"], setup["method_package_ref"]]),
            "scope-editor": ("ui_scope_editor_acceptance.mjs",
                             [setup["application_id"], setup["model_id"], setup["system_revision_id"],
                              setup["method_id"]]),
            "labels": ("ui_v3_labels_acceptance.mjs",
                       [setup["application_id"], setup["snapshot_id"],
                        setup.get("labels_snapshot_id") or "", setup["method_id"],
                        setup["model_id"], setup["system_revision_id"],
                        setup["method_package_ref"], setup.get("labels_skipped") or "",
                        setup.get("dialog_application_id") or "",
                        setup.get("dialog_model_id") or "",
                        setup.get("dialog_revision_id") or "",
                        setup.get("dialog_skipped") or "",
                        setup.get("dialog_method_id") or ""]),
        }
        rc = 0
        for name in harnesses:
            script, extra = harness[name]
            stem = f"ui-{name}-acceptance"
            proc = subprocess.run(
                ["node", str(REPO / "scripts" / script), one_origin, str(_free_port()), str(run), *extra],
                cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(proc.stdout or "", flush=True)
            if (proc.stderr or "").strip():
                print(proc.stderr, flush=True)
            (run / f"{stem}-stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
            (run / f"{stem}-stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
            print(f"[{stem}] exit={proc.returncode}", flush=True)
            rc = rc or proc.returncode
    finally:
        _terminate(one_proc, "one")
        _terminate(lca_proc, "engine")

    print(f"[done] evidence in {run}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
