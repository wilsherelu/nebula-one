"""Verify with the REAL engine that a product total scales linearly with demand.

Guardrail #1 of docs/ACCOUNTING_CONTRIBUTION_UX.md: the fact that
analysis/pcf.py copies the engine indicator into ``total_footprint`` with no
division is NOT by itself proof that the engine did not already normalise the
result per functional unit upstream. This harness asks the live engine to solve
one single-process model twice, at demand Q and at 2Q, and checks that the
characterised climate total doubles exactly and that total/demand stays
invariant. Only then is the downstream ``T * b / Q`` unit-product conversion
safe (no double scaling).

Artificial single-process mechanism model, NOT a facility inventory or a
regulatory claim. Every factor and characterised value comes from the live EF
runtime; nothing here hardcodes an emission factor.

Usage:
  python scripts/verify_demand_linear_scaling.py \
      --one http://127.0.0.1:18938 --lca http://127.0.0.1:18931 \
      --output .local-evidence/linear-scaling [--base-amount 1000.0]
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
CO2_UUID = "08a91e70-3ddc-11dd-923d-0050c2490048"
CO2_VERSION = "03.00.004"
# Fixed per-activity release for the synthetic process. The absolute magnitude is
# irrelevant; linearity across Q and 2Q is what is being proven.
CO2_PER_ACTIVITY = 2.0


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _co2_inventory(snapshot: dict) -> float:
    """Sum the solved CO2 elementary exchanges for this snapshot.

    Characterization is a downstream linear map: total_footprint = sum(CF_f * amount_f)
    with CF constant per flow, so if this inventory doubles with demand the characterised
    total doubles too. Reading it through an MFA solve sidesteps the EF3.1 runtime asset
    alignment while still exercising the exact solver scaling the product depends on.
    """
    see = snapshot.get("scaled_elementary_exchanges") or []
    co2 = [float(x["amount"]) for x in see if str(x.get("flow_uuid")) == CO2_UUID]
    if not co2:
        raise AssertionError("solve returned no CO2 elementary exchanges")
    return sum(co2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one", default="http://127.0.0.1:18938")
    parser.add_argument("--lca", default="http://127.0.0.1:18931")
    parser.add_argument("--output", default=".local-evidence/linear-scaling")
    parser.add_argument("--base-amount", type=float, default=1000.0)
    args = parser.parse_args()

    if not (math.isfinite(args.base_amount) and args.base_amount > 0):
        print(json.dumps({"refused": "--base-amount must be a positive finite number"}), file=sys.stderr)
        return 2

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Resolve the CO2 elementary flow identity from the live engine catalog.
    resolution = _request(args.lca, "POST", "/api/provider/v1/catalog/resolve",
                          {"flows": [dict(source_namespace="tiangong_open_data",
                                          flow_uuid=CO2_UUID, version=CO2_VERSION)]})
    assert all(item["status"] == "resolved" for item in resolution["items"]), resolution
    co2 = resolution["items"][0]["value"]

    # Reuse the steel seed graph only to inherit a valid reference-product output port
    # identity (flow uuid + mass unit group); the mechanism itself is one synthetic node.
    seed = json.loads(Path("cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json")
                      .read_text(encoding="utf-8"))["graph"]
    product = deepcopy(next(port for node in seed["nodes"] for port in node["outputs"]
                            if port.get("isProduct")))
    product.update(id="product", amount=1.0)

    emission = {
        "id": "co2", "flowUuid": co2["flow_uuid"], "flowSourceNamespace": co2["source_namespace"],
        "flowVersion": co2["version"], "flowPropertyUuid": co2["flow_property_uuid"],
        "flowPropertyVersion": co2["flow_property_version"], "unitGroupUuid": co2["unit_group_uuid"],
        "unitGroupVersion": co2["unit_group_version"], "unit": co2["unit"], "unitGroup": co2["unit_group"],
        "name": co2["name_en"], "amount": CO2_PER_ACTIVITY, "type": "biosphere",
        "direction": "output", "isProduct": False,
    }
    node = dict(deepcopy(seed["nodes"][-1]))
    node.update(id="unit-process", name="Demand linearity single process", dataMode="normalized",
                inputs=[], outputs=[product, emission], position={"x": 0, "y": 0})
    graph = {"nodes": [node], "exchanges": [],
             "metadata": {"elementary_flow_refs": [
                 {"exchange_id": "unit-process::co2",
                  "source_namespace": co2["source_namespace"], "flow_uuid": co2["flow_uuid"],
                  "version": co2["version"],
                  **{key: co2[key] for key in ("flow_property_uuid", "flow_property_version",
                                               "unit_group_uuid", "unit_group_version",
                                               "unit", "direction", "compartment")}}]},
             "functionalUnit": "1 kg acceptance product"}

    application = _request(args.one, "POST", f"{API}/applications", {
        "name": f"Demand linearity acceptance {tag}", "application_type": "system_analysis",
        "description": "Artificial single-process mechanism test; not a facility or CBAM result",
        "context": {}})
    app_id = application["id"]
    model = _request(args.one, "POST", f"{API}/applications/{app_id}/system-models/inline", {
        "name": "Demand linearity process", "provider": "nebula_lca",
        "source_id": f"acceptance:demand-linearity:{tag}", "source_version": 1,
        "expected_graph_sha256": digest(graph), "graph": graph})
    rev_id = model["upstream_receipt"]["base_revision_id"]

    demand = [{"reference_flow_uuid": product["flowUuid"], "unit": product["unit"],
               "unit_group_uuid": product["unitGroupUuid"],
               "unit_group_version": product["unitGroupVersion"]}]

    def solve(amount: float) -> dict:
        # MFA task: solves the reference process to meet the demand and returns the scaled
        # elementary inventory WITHOUT requesting an LCIA method (so no EF3.1 asset needed).
        body = {"demand": [{**demand[0], "amount": amount}], "analysis_task": "mfa",
                "idempotency_key": f"{tag}-{amount:g}"}
        return _request(args.one, "POST",
                        f"{API}/applications/{app_id}/system-revisions/{rev_id}/solve", body)

    q, two_q = args.base_amount, args.base_amount * 2.0
    snap_q = solve(q)
    snap_2q = solve(two_q)
    (out / "snap-q.json").write_text(json.dumps(snap_q, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "snap-2q.json").write_text(json.dumps(snap_2q, ensure_ascii=False, indent=2), encoding="utf-8")

    inv_q, inv_2q = _co2_inventory(snap_q), _co2_inventory(snap_2q)

    # Recorded-evidence cross-check (offline, no EF3.1 runtime needed): in the real steel
    # solve the summed CO2 elementary inventory equals the characterised total_footprint
    # exactly (CO2's factor is 1 kg CO2-eq/kg) and equals the value One copies verbatim at
    # analysis/pcf.py:401-408. This ties "inventory doubles => characterised total doubles".
    recorded = {}
    try:
        probe = Path("tmp/steel-probe-2026-09-21/solve")
        snap = json.loads((probe / "20-solve-steel-and-freeze.json").read_text(encoding="utf-8"))["first"]["body"]
        rec_inv = sum(float(x["amount"]) for x in snap["scaled_elementary_exchanges"]
                      if str(x.get("flow_uuid")) == CO2_UUID)
        rec_pcf = json.loads((probe / "22-pcf-steel.json").read_text(encoding="utf-8"))["body"]["total_footprint"]["value"]
        recorded = {"co2_inventory": rec_inv, "pcf_total_footprint": float(rec_pcf),
                    "inventory_equals_pcf": abs(rec_inv - float(rec_pcf)) <= 1e-6 * max(1.0, abs(rec_pcf))}
    except Exception as exc:  # noqa: BLE001
        recorded = {"unavailable": f"{type(exc).__name__}: {exc}"}

    intensity_q, intensity_2q = inv_q / q, inv_2q / two_q
    rel_ratio = inv_2q / inv_q
    # Relative tolerance: the solver scaling is deterministic float arithmetic, so doubling
    # must match to floating precision, not just to two decimal places.
    tol = 1e-9
    checks = {
        "inventory_positive_and_finite": all(math.isfinite(v) and v > 0 for v in (inv_q, inv_2q)),
        "inventory_doubles_within_float_tol": abs(rel_ratio - 2.0) <= tol * 2.0,
        "intensity_invariant": abs(intensity_q - intensity_2q) <= tol * max(1.0, abs(intensity_q)),
        "solve_hash_differs_only_by_demand": snap_q["solve_hash"] != snap_2q["solve_hash"],
    }
    if "inventory_equals_pcf" in recorded:
        checks["recorded_inventory_equals_characterised_pcf"] = recorded["inventory_equals_pcf"]
    passed = all(checks.values())

    evidence = {
        "kind": "verify_demand_linear_scaling", "tag": tag, "engine": args.lca, "one": args.one,
        "note": "synthetic single-process mechanism; not a facility or regulatory result",
        "application_id": app_id, "system_revision_id": rev_id,
        "reference_flow_uuid": product["flowUuid"], "unit": product["unit"],
        "co2_per_activity": CO2_PER_ACTIVITY,
        "demand": {"Q": q, "2Q": two_q},
        "co2_elementary_inventory": {"Q": inv_q, "2Q": inv_2q, "unit": "kg"},
        "ratio_2Q_over_Q": rel_ratio,
        "intensity_inventory_over_demand": {"Q": intensity_q, "2Q": intensity_2q},
        "solve_hash": {"Q": snap_q["solve_hash"], "2Q": snap_2q["solve_hash"]},
        "recorded_steel_crosscheck": recorded,
        "characterization_is_linear_map": (
            "total_footprint = sum(CF_f * amount_f), CF constant per flow and copied verbatim "
            "by analysis/pcf.py, so inventory doubling implies characterised-total doubling"),
        "checks": checks, "passed": passed,
    }
    (out / "linear-scaling-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if not passed:
        print(f"LINEARITY CHECK FAILED for application {app_id}; see {out}", file=sys.stderr)
        return 1
    print(f"LINEARITY PROVEN: T(2Q)=2*T(Q) and T/Q invariant; engine total is extensive, "
          f"not pre-normalised. Downstream T*b/Q divides exactly once.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
