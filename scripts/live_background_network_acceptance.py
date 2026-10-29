"""Exercise a saved two-stage supply network through real LCA and One HTTP APIs.

Uses an existing lawful user supply inventory unchanged behind a lossless delivery
stage. No emission factor, new empirical inventory or commercial dataset is embedded.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import uuid

from live_user_method_acceptance import _request, _climate_terms, _isclose, _create_validate_method, _rule, _pcf, _final_output_field


def run(base, engine, evidence):
    report = json.loads((evidence / "full-report.json").read_text(encoding="utf-8"))
    original = json.loads((evidence / "background_solve.json").read_text(encoding="utf-8"))
    app, revision = report["application_id"], report["revision_r1"]
    supplier = _request(engine, "GET", f"/api/provider/v1/models/{original['project_id']}/versions/{original['version']}/snapshot")
    source = deepcopy(supplier["graph"])
    root_id = original["provenance"][0]["pin"]["source_node_id"]
    leaf = next(node for node in source["nodes"] if node["id"] == root_id)
    products = [p for p in leaf["outputs"] if p.get("type") == "technosphere" and p.get("isProduct")]
    assert len(products) == 1
    reference = products[0]
    delivery = deepcopy(leaf)
    delivery_tag = uuid.uuid4().hex[:8]
    delivery.update(id="acceptance-delivery-" + delivery_tag, process_uuid=str(uuid.uuid4()), name="Background delivery acceptance " + delivery_tag)
    delivery["outputs"] = [deepcopy(reference)]
    input_port = deepcopy(reference)
    input_port.update(id="supply-input", direction="input", isProduct=False)
    delivery["inputs"] = [input_port]
    source["nodes"].append(delivery)
    source["exchanges"] = list(source.get("exchanges") or []) + [{"id": "acceptance-supply-link", "fromNode": leaf["id"], "toNode": delivery["id"],
        "sourcePortId": reference["id"], "targetPortId": input_port["id"],
        "sourceHandle": "out:" + reference["id"], "targetHandle": "in:" + input_port["id"],
        "flowUuid": reference["flowUuid"], "flowName": reference["name"], "unit": reference["unit"],
        "amount": reference["amount"], "quantityMode": "single", "type": "technosphere"}]
    tag = uuid.uuid4().hex[:10]
    created = _request(engine, "POST", "/api/projects", {"name": f"Closed network acceptance {tag}",
        "reference_product": reference["name"], "functional_unit": source.get("functionalUnit") or "one supply unit"})
    project_id = created["project_id"]
    version = _request(engine, "POST", f"/api/projects/{project_id}/versions", {"graph": source})["version"]
    prefix = f"/api/v1/applications/{app}/workspace/{revision}"
    resolved = _request(base, "POST", prefix + "/background/user-project-resolve", {
        "consumer_exchange_id": original["consumer_port"], "project_id": project_id, "version": version})
    pin = resolved["pin"]
    assert pin["source_node_id"] == delivery["id"]
    assert pin["claim_role"] == "user_declared_partial_background_network"
    ws = _request(base, "GET", prefix)
    saved = _request(base, "POST", f"/api/v1/applications/{app}/workspace/inputs", {
        "revision_id": revision, "expected_content_sha256": ws["content_sha256"], "amounts": [7],
        "demand_mode": "reference_output", "values": {f["key"]: f["value"] for f in ws["fields"]},
        "source": f"Closed network acceptance {tag}", "project_background_pins": [pin]})
    rev, demand = saved["revision_id"], saved["demand"]
    def solve(amounts, method=None, target_revision=None):
        payload = {"demand": amounts, "calculation_purpose": "lca", "analysis_task": "pcf",
                   "climate_default": True, "project_background_pins": [pin]}
        if method:
            payload["calculation_method_ref"] = {k: method[k] for k in ("method_id", "version", "content_sha256")}
        return _request(base, "POST", f"/api/v1/applications/{app}/system-revisions/{target_revision or rev}/solve", payload)
    snap = solve(demand)
    _, terms = _climate_terms(snap)
    bg = [t for t in terms if t["attribution_basis"] == "background_consumer_path"]
    fg = [t for t in terms if t["attribution_basis"] == "foreground_direct"]
    bg_total = sum(t["value"] for t in bg)
    assert bg_total > 0 and _isclose(bg_total, original["background_sum"])
    assert _isclose(sum(t["value"] for t in fg), report["counted_a"])
    assert {t["consumer_exchange_id"] for t in bg} == {pin["consumer_exchange_id"]}
    receipts = snap["provider_receipt"]["project_background_process_receipts"]
    assert len(receipts) == len(source["nodes"]) and {r["expansion_mode"] for r in receipts} == {"closed_network"}
    doubled_ws = _request(base, "GET", f"/api/v1/applications/{app}/workspace/{rev}")
    doubled_values = {f["key"]: f["value"] for f in doubled_ws["fields"]}
    output = _final_output_field(doubled_ws)
    doubled_values[output["key"]] = output["value"] * 2
    consumer = next(field for field in doubled_ws["fields"]
                    if f"{field['process_id']}::{field['port_id']}" == pin["consumer_exchange_id"])
    # Quantities are saved batch inventory, not coefficients: double the actual
    # purchased input too. Changing product yield alone must NOT invent more power.
    doubled_values[consumer["key"]] = consumer["value"] * 2
    doubled_revision = _request(base, "POST", f"/api/v1/applications/{app}/workspace/inputs", {
        "revision_id": rev, "expected_content_sha256": doubled_ws["content_sha256"], "amounts": [7],
        "demand_mode": "reference_output", "values": doubled_values,
        "source": f"Closed network doubled demand {tag}", "project_background_pins": [pin]})
    twice = solve(doubled_revision["demand"], target_revision=doubled_revision["revision_id"])
    _, doubled = _climate_terms(twice)
    assert _isclose(sum(t["value"] for t in doubled if t["attribution_basis"] == "background_consumer_path"), 2 * bg_total)
    rules = [_rule(t["exchange_id"], boundary_status="selected", scope="scope_1") for t in fg]
    rules.append(_rule(pin["consumer_exchange_id"], boundary_status="selected", scope="scope_2",
                       location_role="purchased_energy", direction="input"))
    method = _create_validate_method(base, app, rev, f"Closed network Scope2 {tag}", "pcf", rules)
    grouped = solve(demand, method)
    pcf = _pcf(base, grouped["id"], report["pcf_method_package_ref"])
    grouping = pcf["contribution_analysis"]["user_method_grouping"]
    assert grouping["grouping_mode"] == "path_weighted"
    assert _isclose(grouping["grouping"]["scopes"]["scope_2"]["value"], bg_total)
    assert grouping["grouping"]["reconciled"] is True
    assert solve(demand, method)["content_sha256"] == grouped["content_sha256"]
    result = {"status": "pass", "project_id": project_id, "version": version, "revision_id": rev,
              "snapshot_id": grouped["id"], "background_total": bg_total, "grouping": grouping,
              "receipts": receipts, "source_project_id": original["project_id"],
              "source_version": original["version"], "source_graph_hash": supplier["graph_hash"]}
    (evidence / "closed-network-acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18938")
    parser.add_argument("--engine-url", default="http://127.0.0.1:18931")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    run(args.url, args.engine_url, args.evidence)
