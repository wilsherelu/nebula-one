"""Reconcile the backend T*b/Q result-basis projection against the REAL EF3.1 engine.

Guardrail #2/#3 numeric closure for docs/ACCOUNTING_CONTRIBUTION_UX.md. It proves that
``project_result_basis`` (``per_reference_output``) divides EXACTLY once against a genuinely
characterised snapshot -- not a raw mass fixture -- by an INDEPENDENT cross-check: the engine is
asked to characterise the same model at demand 1 kg and at demand 1000 kg, and the server-side
projection of the 1000 kg solve onto a 1 kg base must equal the engine's OWN 1 kg characterised
total. That equality never uses the projection's own arithmetic as its reference, so it cannot
degrade into "the projection agrees with itself".

Artificial single-process mechanism model, NOT a facility inventory or regulatory claim. Every
factor and characterised value comes from the live EF3.1 runtime; nothing here hardcodes a factor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_user_method_acceptance import _request  # noqa: E402

API = "/api/v1"
# CO2 (GWP) and CH4 (GWP) elementary identities resolved from the live catalog; the two gases give
# the characterised total a non-unit factor so linearity is not trivially mass equality.
GASES = [
    {"exchange": "co2", "flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048", "version": "03.00.004",
     "amount": 10.0},
    {"exchange": "ch4", "flow_uuid": "08a91e70-3ddc-11dd-9610-0050c2490048", "version": "03.00.004",
     "amount": 0.1},
]


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _build_graph(lca: str) -> tuple[dict, dict]:
    refs = [dict(source_namespace="tiangong_open_data", flow_uuid=g["flow_uuid"], version=g["version"])
            for g in GASES]
    resolution = _request(lca, "POST", "/api/provider/v1/catalog/resolve", {"flows": refs})
    assert all(item["status"] == "resolved" for item in resolution["items"]), resolution
    identities = {item["value"]["flow_uuid"]: item["value"] for item in resolution["items"]}

    seed = json.loads(Path("cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json")
                      .read_text(encoding="utf-8"))["graph"]
    product = deepcopy(next(port for node in seed["nodes"] for port in node["outputs"]
                            if port.get("isProduct")))
    product.update(id="product", amount=1.0)

    emissions, elementary_refs = [], []
    for gas in GASES:
        flow = identities[gas["flow_uuid"]]
        emissions.append({"id": gas["exchange"], "flowUuid": flow["flow_uuid"],
            "flowSourceNamespace": flow["source_namespace"], "flowVersion": flow["version"],
            "flowPropertyUuid": flow["flow_property_uuid"], "flowPropertyVersion": flow["flow_property_version"],
            "unitGroupUuid": flow["unit_group_uuid"], "unitGroupVersion": flow["unit_group_version"],
            "unit": flow["unit"], "unitGroup": flow["unit_group"], "name": flow["name_en"],
            "amount": gas["amount"], "type": "biosphere", "direction": "output", "isProduct": False})
        elementary_refs.append({"exchange_id": "unit-process::" + gas["exchange"], **{
            "source_namespace": flow["source_namespace"], "flow_uuid": flow["flow_uuid"],
            "version": flow["version"]},
            **{key: flow[key] for key in ("flow_property_uuid", "flow_property_version",
                "unit_group_uuid", "unit_group_version", "unit", "direction", "compartment")}})

    node = deepcopy(seed["nodes"][-1])
    node.update(id="unit-process", name="Result-basis reconciliation single process", dataMode="normalized",
                inputs=[], outputs=[product, *emissions], position={"x": 0, "y": 0})
    graph = {"nodes": [node], "exchanges": [], "metadata": {"elementary_flow_refs": elementary_refs},
             "functionalUnit": "1 kg acceptance product"}
    return graph, product


def _solve(one: str, app_id: str, rev_id: str, product: dict, amount: float, key: str) -> dict:
    demand = [{"reference_flow_uuid": product["flowUuid"], "amount": amount, "unit": product["unit"],
               "unit_group_uuid": product["unitGroupUuid"], "unit_group_version": product["unitGroupVersion"]}]
    return _request(one, "POST", f"{API}/applications/{app_id}/system-revisions/{rev_id}/solve", {
        "demand": demand, "analysis_task": "pcf", "climate_default": True, "idempotency_key": key})


def _pcf(one: str, snap_id: str, method_ref: str, *, basis: str | None = None,
         base_amount=None, base_unit=None) -> dict:
    body: dict = {"method_package_ref": method_ref}
    if basis is not None:
        body["result_basis"] = basis
        body["base_amount"] = base_amount
        body["base_unit"] = base_unit
    return _request(one, "POST", f"{API}/solved-system-snapshots/{snap_id}/product-carbon-footprint", body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one", default="http://127.0.0.1:18938")
    parser.add_argument("--lca", default="http://127.0.0.1:18931")
    parser.add_argument("--output", default=".local-evidence/pcf-basis-reconciliation")
    args = parser.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    graph, product = _build_graph(args.lca)
    application = _request(args.one, "POST", f"{API}/applications", {
        "name": f"Result-basis reconciliation {tag}", "application_type": "system_analysis",
        "description": "Artificial single-process mechanism test; not a facility or CBAM result", "context": {}})
    app_id = application["id"]
    model = _request(args.one, "POST", f"{API}/applications/{app_id}/system-models/inline", {
        "name": "Result-basis reconciliation process", "provider": "nebula_lca",
        "source_id": f"acceptance:pcf-basis:{tag}", "source_version": 1,
        "expected_graph_sha256": digest(graph), "graph": graph})
    rev_id = model["upstream_receipt"]["base_revision_id"]

    # Two INDEPENDENT engine characterisations of the same model at two demands. The 1 kg solve is
    # the engine's own per-unit; the 1000 kg solve is the batch the server-side projection must
    # reproduce per-unit -- without the projection being its own reference.
    snap_1 = _solve(args.one, app_id, rev_id, product, 1.0, f"{tag}-q1")
    snap_1000 = _solve(args.one, app_id, rev_id, product, 1000.0, f"{tag}-q1000")
    (out / "snap-1-raw.json").write_text(json.dumps(snap_1, ensure_ascii=False, indent=2), encoding="utf-8")

    def _find_keys(node, acc):
        if isinstance(node, dict):
            if "canonical_indicator_key" in node:
                acc.append(str(node.get("canonical_indicator_key")))
            for value in node.values():
                _find_keys(value, acc)
        elif isinstance(node, list):
            for value in node:
                _find_keys(value, acc)
        return acc

    climate_keys = sorted(set(k for k in _find_keys(snap_1, []) if "climate" in k.casefold()))
    (out / "snap-1-canonical-indicator-keys.json").write_text(
        json.dumps(climate_keys, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[engine canonical climate keys] {climate_keys}", flush=True)
    # The default LCIA climate indicator applied straight to a characterised snapshot's
    # lcia_results (no model-boundary rule); this is the shipped foreground method package,
    # not a model-specific frozen default, which the synthetic mechanism model does not carry.
    method_ref = "pcf.product.ef31.foreground@1.0.4"

    total_1 = _pcf(args.one, snap_1["id"], method_ref)
    total_1000 = _pcf(args.one, snap_1000["id"], method_ref)
    t1 = float(total_1["total_footprint"]["value"])
    t1000 = float(total_1000["total_footprint"]["value"])

    # The server-side read-only projection over the SAME frozen 1000 kg snapshot.
    per_kg = _pcf(args.one, snap_1000["id"], method_ref, basis="per_reference_output", base_amount=1, base_unit="kg")
    per_t = _pcf(args.one, snap_1000["id"], method_ref, basis="per_reference_output", base_amount=1, base_unit="t")
    # And a 1 kg solve projected onto a tonne base (1000 * its own per-kg).
    one_kg_on_tonne = _pcf(args.one, snap_1["id"], method_ref, basis="per_reference_output", base_amount=1, base_unit="t")

    for name, payload in (("q1", total_1), ("q1000", total_1000), ("per-kg", per_kg), ("per-t", per_t)):
        (out / f"pcf-{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    pk = float(per_kg["total_footprint"]["value"])
    pt = float(per_t["total_footprint"]["value"])
    okg = float(one_kg_on_tonne["total_footprint"]["value"])

    def close(actual, expected, name):
        assert math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-9), (name, actual, expected)

    checks = {}
    # (1) the engine characterises linearly over a real multi-gas total: T(1000 kg) == 1000 * T(1 kg)
    close(t1000, t1 * 1000.0, "engine_characterised_scales_linearly")
    checks["engine_characterised_scales_linearly"] = True
    # (2) THE reconciliation: the server projection of the 1000 kg solve onto 1 kg equals the engine's
    #     own independent 1 kg characterisation -- proof that T*b/Q divides exactly once on real EF3.1.
    close(pk, t1, "projection_matches_independent_engine_per_unit")
    checks["projection_matches_independent_engine_per_unit"] = True
    # (3) base unit conversion is exact: per-tonne == per-kg * 1000; 1 kg solve on a tonne base == the 1000 kg total.
    close(pt, pk * 1000.0, "per_tonne_is_per_kg_times_1000")
    close(okg, t1000, "one_kg_on_tonne_equals_batch_total")
    checks["base_unit_conversion_exact"] = True
    # (4) switching the display basis is NOT a re-solve: the projected snapshots reuse the frozen solve hash.
    assert per_kg["source_snapshot"]["content_sha256"] == total_1000["source_snapshot"]["content_sha256"]
    assert per_kg["result_basis"]["source"]["solve_hash"] == total_1000["source_snapshot"]["content_sha256"]
    checks["display_toggle_reuses_frozen_solve"] = True
    # (5) the raw total is untouched and byte-identical; the projected content hash is the only change.
    assert total_1000["content_sha256"] != per_kg["content_sha256"]
    assert per_kg["total_footprint"]["unit"] == "kg CO2-Eq/1 kg"
    checks["projection_is_a_view_not_a_recompute"] = True
    # (6) guardrail #3: the projection binds an exact reference-output identity with the model version.
    ref = per_kg["result_basis"]["reference_output"]
    assert ref["selector"] == "reference_flow_uuid" and ref["value"] == product["flowUuid"]
    assert ref["model_version"]["system_revision_id"] == rev_id
    checks["reference_output_identity_bound"] = True
    # (6b) guardrail #3 uniqueness: filling one selector is not the same as hitting one output. The
    #      projection must resolve the bound reference flow against the frozen solve's actual producing
    #      outputs and, because the synthetic model emits it from exactly one process, freeze that
    #      unique hit's process and exchange identities (and make them the denominator identity).
    producers = [row for row in (snap_1000.get("scaled_technosphere_exchanges") or [])
                 if row.get("direction") == "output" and row.get("flow_uuid") == product["flowUuid"]]
    assert len(producers) == 1, ("expected one producing output for the reference flow", producers)
    assert ref["producing_process_uuid"] == producers[0]["process_id"]
    assert ref["producing_exchange_id"] == producers[0]["exchange_id"]
    assert ref["identity"] == producers[0]["exchange_id"]
    checks["reference_output_uniquely_resolved_and_frozen"] = True

    # (7) negative control: an incompatible base is refused (422) rather than silently accepted.
    refused = False
    try:
        _pcf(args.one, snap_1000["id"], method_ref, basis="per_reference_output", base_amount=1, base_unit="kWh")
    except Exception as exc:  # noqa: BLE001
        refused = "422" in str(exc) or "UNIT_PRODUCT_INCOMPATIBLE" in str(exc) or "incompatible" in str(exc).lower()
    checks["incompatible_base_unit_refused"] = bool(refused)

    evidence = {
        "kind": "verify_pcf_basis_reconciliation", "tag": tag, "engine": args.lca, "one": args.one,
        "note": "synthetic single-process mechanism; not a facility or regulatory result",
        "application_id": app_id, "system_revision_id": rev_id, "graph_sha256": digest(graph),
        "method_package_ref": method_ref,
        "characterised_totals": {"T_at_1kg": t1, "T_at_1000kg": t1000,
                                  "unit": total_1000["total_footprint"]["unit"]},
        "projection": {"per_kg": pk, "per_t": pt, "one_kg_on_tonne": okg,
                       "per_kg_unit": per_kg["total_footprint"]["unit"],
                       "reference_output": ref},
        "factor_source": "live EF 3.1 characterised contribution receipt; not user-defined factors",
        "checks": checks, "passed": all(checks.values()),
    }
    (out / "pcf-basis-reconciliation-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if not evidence["passed"]:
        print(f"RECONCILIATION FAILED for application {app_id}; see {out}", file=sys.stderr)
        return 1
    print("RECONCILED: server T*b/Q projection equals the engine's own independent 1 kg characterisation; "
          "the display toggle reuses the frozen solve.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
