"""E1e: real-engine closed multi-node network organization aggregation acceptance.

Drives the full chain on a live Nebula One (running the E1 fix) against the real LCA engine:
build a two-stage closed supply network on the public Tiangong grid leaf, bind it as a network
background pin, solve the real steel foreground through the engine, then run the ORGANIZATION
lifecycle inventory (the project_supply_climate path) and export.

Expected values are computed INDEPENDENTLY from the engine's own climate receipts, never read
back from the organization result. The discriminating pair:
  * the unmodified official leaf-only steel method must REJECT the network pin (IDENTITY_INVALID);
  * a copy that opts into the network claim role must AGGREGATE the multi-node network into ONE
    supplier per consumer path, summing node contributions exactly once.
Nothing is fabricated: the network uses real public factors resolved by the engine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from copy import deepcopy
import uuid

import live_user_method_acceptance as L

API = L.API
MODEL_ID = "ad162bd6-c9f5-4eb6-ae3e-1d347f146705"          # seeded steel model (app 90054a93)
APP_ID = "90054a93-596f-5298-aeca-f7fa8c160195"
SUPPLY_PROJECT = "8caee767-d4bc-449b-9451-27d0abe52bfa"     # tiangong-china-grid-2022 leaf
SUPPLY_VERSION = 1
SUPPLY_LEAF_NODE = "tiangong-grid-2022"
CONSUMER_PORT = "ore-sintering::grid-electricity-in"        # model structure, not an invented factor
_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ORG = _ROOT / "src/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.10.json"


def _build_network_supply(engine: str) -> dict:
    """Append a lossless delivery stage to the public grid leaf, making a two-node closed network."""
    snapshot = L._request(engine, "GET",
        f"/api/provider/v1/models/{SUPPLY_PROJECT}/versions/{SUPPLY_VERSION}/snapshot")
    source = deepcopy(snapshot["graph"])
    leaf = next(node for node in source["nodes"] if node["id"] == SUPPLY_LEAF_NODE)
    products = [p for p in leaf["outputs"] if p.get("type") == "technosphere" and p.get("isProduct")]
    assert len(products) == 1, "grid leaf must expose exactly one reference product"
    reference = products[0]
    delivery = deepcopy(leaf)
    tag = uuid.uuid4().hex[:8]
    delivery.update(id="e1e-delivery-" + tag, process_uuid=str(uuid.uuid4()),
                    name="E1e delivery stage " + tag)
    delivery["outputs"] = [deepcopy(reference)]
    input_port = deepcopy(reference)
    input_port.update(id="supply-input", direction="input", isProduct=False)
    delivery["inputs"] = [input_port]
    source["nodes"].append(delivery)
    source["exchanges"] = list(source.get("exchanges") or []) + [{
        "id": "e1e-supply-link", "fromNode": leaf["id"], "toNode": delivery["id"],
        "sourcePortId": reference["id"], "targetPortId": input_port["id"],
        "sourceHandle": "out:" + reference["id"], "targetHandle": "in:" + input_port["id"],
        "flowUuid": reference["flowUuid"], "flowName": reference["name"], "unit": reference["unit"],
        "amount": reference["amount"], "quantityMode": "single", "type": "technosphere"}]
    created = L._request(engine, "POST", "/api/projects", {
        "name": f"E1e closed network {tag}", "reference_product": reference["name"],
        "functional_unit": source.get("functionalUnit") or "one supply unit"})
    project_id = created["project_id"]
    version = L._request(engine, "POST", f"/api/projects/{project_id}/versions", {"graph": source})["version"]
    return {"project_id": project_id, "version": version, "entry_node": delivery["id"],
            "node_count": len(source["nodes"])}


def _solve_network(base: str, pin: dict, demand: list, rev: str) -> dict:
    body = {"demand": demand, "idempotency_key": f"e1e-{uuid.uuid4().hex[:12]}",
            "calculation_purpose": "lca", "analysis_task": "pcf",
            "climate_default": True, "project_background_pins": [pin]}
    return L._request(base, "POST", f"{API}/applications/{APP_ID}/system-revisions/{rev}/solve", body)


def _org_expect_error(base: str, snap_id: str, method_ref: str) -> str | None:
    try:
        L._request(base, "POST", f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/current-model",
                   {"solved_snapshot_id": snap_id, "method_package_ref": method_ref})
        return None
    except RuntimeError as exc:
        return str(exc)


def run(base: str, engine: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: dict | None = None) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    # 1. revision + network supply + resolve network pin
    revisions = L._request(base, "GET", f"{API}/system-models/{MODEL_ID}/revisions")
    items = revisions if isinstance(revisions, list) else revisions.get("items", [])
    rev0 = items[0]["id"]  # seeded base revision (no background pins attached)
    network = _build_network_supply(engine)
    resolved = L._request(base, "POST",
        f"{API}/applications/{APP_ID}/workspace/{rev0}/background/user-project-resolve",
        {"consumer_exchange_id": CONSUMER_PORT, "project_id": network["project_id"],
         "version": network["version"]})
    pin = resolved["pin"]
    check("network_pin_is_multi_node_claim", pin["claim_role"] == "user_declared_partial_background_network"
          and pin["source_node_id"] == network["entry_node"],
          {"claim_role": pin["claim_role"], "source_node_id": pin["source_node_id"]})

    # 2. save workspace inputs with the network pin and solve through the real engine
    ws = L._request(base, "GET", f"{API}/applications/{APP_ID}/workspace/{rev0}")
    values = {f["key"]: f["value"] for f in ws["fields"]}
    saved = L._request(base, "POST", f"{API}/applications/{APP_ID}/workspace/inputs", {
        "revision_id": rev0, "expected_content_sha256": ws["content_sha256"], "amounts": [7],
        "demand_mode": "reference_output", "values": values, "source": "E1e network acceptance",
        "project_background_pins": [pin]})
    rev, demand = saved["revision_id"], saved["demand"]
    snap = _solve_network(base, pin, demand, rev)

    # 3. the engine really emitted multiple closed_network node rows for the one pin
    receipts = snap["provider_receipt"]["project_background_process_receipts"]
    net_rows = [r for r in receipts if (r.get("pin") or {}).get("consumer_exchange_id") == CONSUMER_PORT]
    check("engine_emits_per_node_network_receipts", len(net_rows) >= 2
          and {r["expansion_mode"] for r in net_rows} == {"closed_network"}
          and len({r["source_process_uuid"] for r in net_rows}) == len(net_rows),
          {"row_count": len(net_rows), "modes": sorted({r["expansion_mode"] for r in net_rows}),
           "distinct_processes": len({r["source_process_uuid"] for r in net_rows})})

    # 4. independent expected values from the engine climate receipts
    indicator, terms = L._climate_terms(snap)
    bg_sum = sum(t["value"] for t in terms if t["attribution_basis"] == "background_consumer_path"
                 and t["consumer_exchange_id"] == CONSUMER_PORT)
    fg_sum = sum(t["value"] for t in terms if t["attribution_basis"] == "foreground_direct")
    check("engine_background_network_nonzero", bg_sum > 0,
          {"indicator": indicator, "network_background_sum": bg_sum, "foreground_sum": fg_sum})

    # 5. discriminating negative: the unmodified official leaf-only method must refuse the network
    official = json.loads(OFFICIAL_ORG.read_text(encoding="utf-8"))
    official_ref = f"{official['package_id']}@{official['version']}"
    L._register_and_bind(base, APP_ID, official, official_ref)
    reject = _org_expect_error(base, snap["id"], official_ref)
    check("official_leaf_only_method_rejects_network",
          reject is not None and "IDENTITY_INVALID" in reject, {"error": (reject or "")[:200]})

    # 6. an opt-in method aggregates the network correctly
    custom = deepcopy(official)
    custom["package_id"] = "e1e.organization-lifecycle-carbon.steel-network"
    custom["version"] = "1.0.0"
    custom["manifest"]["classification_rules"]["accepted_project_claim_roles"] = [
        "user_declared_partial_background_leaf", "user_declared_partial_background_network"]
    custom_ref = f"{custom['package_id']}@{custom['version']}"
    L._register_and_bind(base, APP_ID, custom, custom_ref)
    org = L._request(base, "POST", f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/current-model",
                     {"solved_snapshot_id": snap["id"], "method_package_ref": custom_ref})
    result = org["result"] if "result" in org else org
    scale = result["activity_basis"]["scale_factor"]
    suppliers = result["climate_source"]["suppliers"]
    network_suppliers = [s for s in suppliers if s["consumer_exchange_id"] == CONSUMER_PORT]
    check("network_collapsed_to_one_supplier_per_path", len(network_suppliers) == 1,
          {"count": len(network_suppliers), "exchange_ids": [s["consumer_exchange_id"] for s in suppliers]})
    agg = network_suppliers[0]
    # The engine omits a climate term for a lossless internal node (engine-confirmed zero, not a
    # missing factor), so a network path may honestly be partial_characterization. The no-double-
    # count discriminator is: the collapsed value equals the independent sum of present engine
    # node terms once, every node row is in the breakdown, and no node is counted twice.
    check("network_contribution_summed_once_no_double_count",
          agg["status"] in {"calculated", "partial_characterization"} and agg["contribution_value"] is not None
          and L._isclose(agg["contribution_value"], bg_sum, tol=1e-6)
          and len(agg.get("network_nodes", [])) == len(net_rows),
          {"aggregate": agg["contribution_value"], "engine_bg": bg_sum,
           "status": agg["status"], "node_breakdown": len(agg.get("network_nodes", []))})
    node_vals = [n["contribution_value"] for n in agg.get("network_nodes", []) if n["contribution_value"] is not None]
    check("node_breakdown_disjoint_and_matches_aggregate",
          L._isclose(sum(node_vals), agg["contribution_value"], tol=1e-6)
          and len({n["process_uuid"] for n in agg.get("network_nodes", [])}) == len(agg.get("network_nodes", [])),
          {"node_sum": sum(node_vals), "aggregate": agg["contribution_value"]})

    # 7. Scope buckets: network path lands in Scope 2, foreground unchanged in Scope 1
    groups = result["groups"]
    s1 = groups["on_site_direct"]["value"]
    s2 = groups["purchased_energy_lifecycle"]["value"]
    check("network_lands_in_scope2_and_foreground_unchanged_in_scope1",
          L._isclose(s2, bg_sum * scale, tol=1e-6) and L._isclose(s1, fg_sum * scale, tol=1e-6)
          and CONSUMER_PORT in groups["purchased_energy_lifecycle"]["exchange_ids"],
          {"scope1": s1, "scope2": s2, "scale": scale, "expected_s2": bg_sum * scale,
           "expected_s1": fg_sum * scale})

    # 8. export and readback share the frozen identity
    record_id = org["id"] if "id" in org else org.get("record_id")
    readback = L._request(base, "GET", f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}")
    xlsx, _ = L._bytes(base, f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}/export.xlsx")
    html, _ = L._bytes(base, f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}/report.html")
    html_text = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html)
    check("export_and_readback_same_frozen_identity",
          readback["content_sha256"] == result["content_sha256"]
          and len(xlsx) > 0 and "<html" in html_text.lower(),
          {"record_id": record_id, "content_sha256": result["content_sha256"],
           "xlsx_bytes": len(xlsx), "html_bytes": len(html_text), "readback_sha": readback["content_sha256"]})

    report = {"status": "pass" if all(c["status"] == "pass" for c in checks) else "fail",
              "counts": {"pass": sum(c["status"] == "pass" for c in checks),
                         "fail": sum(c["status"] == "fail" for c in checks)},
              "network": network, "pin": pin, "snapshot_id": snap["id"], "record_id": record_id,
              "indicator": indicator, "engine_background_sum": bg_sum, "foreground_sum": fg_sum,
              "org": result, "checks": checks}
    (out / "e1e-network-org.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in checks:
        print(("PASS" if c["status"] == "pass" else "FAIL"), c["name"],
              "" if c["status"] == "pass" else json.dumps(c["detail"], ensure_ascii=False)[:200])
    print("E1E VERDICT:", report["status"], report["counts"])
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18960")
    parser.add_argument("--engine-url", default="http://127.0.0.1:18931")
    parser.add_argument("--evidence", type=Path, required=True)
    # Optional identity overrides. The defaults above are the DEV seed's uuid5 IDs; a PACKAGED
    # seed installs different (also deterministic) UUIDs, so the packaged-runtime harness passes
    # the discovered packaged IDs here. Left unset, every constant is unchanged and the existing
    # dev evidence stays valid byte-for-byte.
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--app-id", default=None)
    parser.add_argument("--supply-project", default=None)
    parser.add_argument("--supply-version", type=int, default=None)
    parser.add_argument("--supply-leaf-node", default=None)
    parser.add_argument("--consumer-port", default=None)
    args = parser.parse_args()
    for _name, _val in (("MODEL_ID", args.model_id), ("APP_ID", args.app_id),
                        ("SUPPLY_PROJECT", args.supply_project), ("SUPPLY_VERSION", args.supply_version),
                        ("SUPPLY_LEAF_NODE", args.supply_leaf_node), ("CONSUMER_PORT", args.consumer_port)):
        if _val is not None:
            globals()[_name] = _val
    run(args.url, args.engine_url, args.evidence)
