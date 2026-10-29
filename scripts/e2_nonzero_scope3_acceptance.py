"""E2: a clearly-labelled synthetic foreground must yield three independent NON-ZERO Scope sources
(Scope 1 onsite, Scope 2 purchased electricity, Scope 3 a non-electric supplier material) through the
REAL LCA engine, the REAL organization lifecycle aggregation and the REAL export — never by forcing
onsite emissions into Scope 3 and never read back from the organization result.

Scope 1 and Scope 2 come from the engine's own climate receipt (foreground + a public-grid background
pin, exactly like E1). Scope 3 is a SUPPLIER-SPECIFIC declared activity over a port that the engine
genuinely leaves as an OPEN external input (no background), so the ONLY number is a user-entered factor
— every other identity (the port, its solved activity amount, its reference flow, the pinned EF method)
is the real engine's. This is mechanism evidence over synthetic activity data, NOT an official steel
Scope-3 inventory; the reviewed public steel dataset still has no non-electric material supplier, which
the product honestly reports as a gap.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from json import dumps
import uuid
from hashlib import sha256

import live_user_method_acceptance as L

API = L.API
MODEL_ID = "ad162bd6-c9f5-4eb6-ae3e-1d347f146705"          # seeded steel model (app 90054a93)
APP_ID = "90054a93-596f-5298-aeca-f7fa8c160195"
SUPPLY_PROJECT = "8caee767-d4bc-449b-9451-27d0abe52bfa"     # tiangong-china-grid-2022 leaf (Scope 2)
SUPPLY_VERSION = 1
GRID_PORT = "ore-sintering::grid-electricity-in"            # model structure, not an invented factor
_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ORG = _ROOT / "src/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.10.json"
FACTOR_BOUNDARY = "supplier_cradle_to_gate_excluding_modelled_operations"


def _synthetic_method(port: str, activity_unit: str, version: str) -> dict:
    """Clone the official v2 org method into a clearly-labelled synthetic one that opts the single
    open material port into one Scope-3 category and routes non-energy value through DECLARED ACTIVITIES
    (not engine category receipts, which need a public provider the seed lacks). The version is unique
    per run so a stale registered package never pins a different port."""
    pkg = json.loads(OFFICIAL_ORG.read_text(encoding="utf-8"))
    pkg["package_id"] = "e2.synthetic-organization-lifecycle-carbon.steel-three-source"
    pkg["version"] = version
    rules = pkg["manifest"]["classification_rules"]
    rules["energy_purchase_exchange_ids"] = [GRID_PORT]
    rules["energy_purchase_types"] = {GRID_PORT: "purchased_electricity"}
    rules.pop("energy_path_selection", None)  # default: mapped energy set must exactly equal declared
    rules["non_energy_path_source"] = "declared_activities_v1"  # disable engine category-receipt grouping
    rules["other_value_chain_categories"] = {
        "purchased_material_upstream": {
            "name": "合成外购材料上游 (SYNTHETIC)",
            "direction": "input",
            "eligible_consumer_exchange_ids": [port],
            "factor_boundary": FACTOR_BOUNDARY,
            "boundary_status": "selected",
        },
    }
    pkg["manifest"]["template_profile"] = {"id": "e2-synthetic-three-source", "version": "1.0.0"}
    pkg["manifest"]["assurance_level"] = "synthetic_mechanism_not_official"
    return pkg


def _solve_three_source(base: str, engine: str) -> tuple[dict, str]:
    """Pin the public grid leaf to the energy port, declare a synthetic demand scenario, and solve."""
    revisions = L._request(base, "GET", f"{API}/system-models/{MODEL_ID}/revisions")
    items = revisions if isinstance(revisions, list) else revisions.get("items", [])
    rev0 = items[0]["id"]
    resolved = L._request(base, "POST",
        f"{API}/applications/{APP_ID}/workspace/{rev0}/background/user-project-resolve",
        {"consumer_exchange_id": GRID_PORT, "project_id": SUPPLY_PROJECT, "version": SUPPLY_VERSION})
    pin = resolved["pin"]
    ws = L._request(base, "GET", f"{API}/applications/{APP_ID}/workspace/{rev0}")
    values = {f["key"]: f["value"] for f in ws["fields"]}
    tag = uuid.uuid4().hex[:8]
    saved = L._request(base, "POST", f"{API}/applications/{APP_ID}/workspace/inputs", {
        "revision_id": rev0, "expected_content_sha256": ws["content_sha256"], "amounts": [7],
        "demand_mode": "reference_output", "values": values,
        "source": f"E2 synthetic three-source scenario {tag} (not plant measurements)",
        "project_background_pins": [pin]})
    rev, demand = saved["revision_id"], saved["demand"]
    body = {"demand": demand, "idempotency_key": f"e2-{uuid.uuid4().hex[:12]}",
            "calculation_purpose": "lca", "analysis_task": "pcf",
            "climate_default": True, "project_background_pins": [pin]}
    snap = L._request(base, "POST", f"{API}/applications/{APP_ID}/system-revisions/{rev}/solve", body)
    return snap, rev


def _external_material_port(snap: dict, rev: str, base: str) -> dict:
    """Pick the real OPEN non-energy input port the engine leaves un-supplied (never an energy port,
    never the grid pin, never an internal product link). Its amount/unit/flow are engine-authored."""
    detail = L._request(base, "GET", f"{API}/system-revisions/{rev}")
    internal = set()
    for edge in detail["graph_snapshot"].get("exchanges", []):
        if edge.get("fromNode") and edge.get("sourcePortId"):
            internal.add(f"{edge['fromNode']}::{edge['sourcePortId']}")
        if edge.get("toNode") and edge.get("targetPortId"):
            internal.add(f"{edge['toNode']}::{edge['targetPortId']}")
    energy = {GRID_PORT}
    rows = [r for r in snap["scaled_technosphere_exchanges"]
            if r.get("direction") == "input" and r.get("counterparty_process_id") is None
            and r["exchange_id"] not in energy and r["exchange_id"] not in internal
            and r.get("amount", 0) > 0]
    rows.sort(key=lambda r: r["exchange_id"])
    if not rows:
        raise RuntimeError("no open external non-energy input port on the synthetic foreground solve")
    return rows[0]


def _independent_expected(snap: dict) -> tuple[float, float]:
    indicator, terms = L._climate_terms(snap)
    fg = sum(t["value"] for t in terms if t["attribution_basis"] == "foreground_direct")
    bg = sum(t["value"] for t in terms if t["attribution_basis"] == "background_consumer_path"
             and t["consumer_exchange_id"] == GRID_PORT)
    return fg, bg


def _activity(port: dict, snap: dict, factor_value: float) -> dict:
    lcia = snap["lcia_results"]
    evidence = sha256(dumps({"synthetic": True, "port": port["exchange_id"]},
                            sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "activity_id": "e2-material-activity", "category": "purchased_material_upstream",
        "consumer_exchange_id": port["exchange_id"], "quantity": port["amount"],
        "activity_unit": port["unit"], "factor_value": factor_value,
        "factor_unit": f"kg CO2-Eq/{port['unit']}", "factor_version": "e2-synthetic-v1",
        "factor_source": "E2 synthetic supplier factor (mechanism test, not a verified supplier value)",
        "factor_boundary": FACTOR_BOUNDARY, "evidence_sha256": evidence,
        "evidence_role": "supplier_specific", "outside_model": True,
        "factor_method_id": lcia["method"], "factor_method_version": lcia.get("database_release"),
        "factor_method_sha256": lcia.get("runtime_assets_hash"),
        "factor_reference_product": port["flow_uuid"],
    }


def _create_org(base: str, snap: dict, rev: str, method_ref: str, activities: list[dict]) -> dict:
    period_items = L._request(base, "GET", f"{API}/applications/{APP_ID}/periods")
    periods = period_items if isinstance(period_items, list) else period_items.get("items", [])
    detail = L._request(base, "GET", f"{API}/system-revisions/{rev}")
    controlled = [str(node["id"]) for node in detail["graph_snapshot"]["nodes"]]
    demand = ((snap.get("provider_receipt") or {}).get("calculation_basis") or {}).get("demand") or []
    body = {"solved_snapshot_id": snap["id"], "method_package_ref": method_ref,
            "reporting_period_id": periods[0]["id"],
            "facility": "E2 synthetic three-source facility", "controlled_process_ids": controlled,
            "input_basis": "current_model_total", "period_product_output": float(demand[0]["amount"]),
            "other_activities": activities}
    return L._request(base, "POST", f"{API}/applications/{APP_ID}/organization-lifecycle-inventories", body)


def run(base: str, engine: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: dict | None = None) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    snap, rev = _solve_three_source(base, engine)
    fg_expected, bg_expected = _independent_expected(snap)
    port = _external_material_port(snap, rev, base)
    check("three_source_model_has_open_non_energy_material_port", True,
          {"port": port["exchange_id"], "amount": port["amount"], "unit": port["unit"],
           "flow_uuid": port["flow_uuid"]})

    method = _synthetic_method(port["exchange_id"], port["unit"], f"1.0.0-{uuid.uuid4().hex[:8]}")
    method_ref = f"{method['package_id']}@{method['version']}"
    L._register_and_bind(base, APP_ID, method, method_ref)

    # A non-zero Scope-3 factor is required; the value is a clearly-labelled synthetic declaration.
    activity = _activity(port, snap, factor_value=2.0)
    org = _create_org(base, snap, rev, method_ref, [activity])
    result = org["result"]
    groups = result["groups"]
    scale = result["activity_basis"]["scale_factor"]
    s1 = groups["on_site_direct"]["value"]
    s2 = groups["purchased_energy_lifecycle"]["value"]
    s3 = groups["other_value_chain"]["value"]

    # 1. each of the three sources is independently non-zero
    check("all_three_scopes_nonzero", s1 is not None and s2 is not None and s3 is not None
          and s1 > 0 and s2 > 0 and s3 > 0, {"scope1": s1, "scope2": s2, "scope3": s3})

    # 2. Scope 1 / 2 reconcile to the engine's own receipt (never read back from the org result)
    check("scope1_scope2_reconcile_to_engine_receipt",
          L._isclose(s1, fg_expected * scale, tol=1e-6) and L._isclose(s2, bg_expected * scale, tol=1e-6),
          {"scope1": s1, "fg_expected": fg_expected * scale, "scope2": s2, "bg_expected": bg_expected * scale})

    # 3. Scope 3 equals the synthetic activity quantity * declared factor, once
    check("scope3_equals_activity_quantity_times_factor",
          L._isclose(s3, port["amount"] * activity["factor_value"] * scale, tol=1e-6),
          {"scope3": s3, "expected": port["amount"] * activity["factor_value"] * scale})

    # 4. the combined total is the sum of the three, none double counted
    check("combined_total_is_sum_of_three_sources",
          L._isclose(result["combined_total"], s1 + s2 + s3, tol=1e-6),
          {"combined_total": result["combined_total"], "sum": s1 + s2 + s3})

    # 5. excluding the Scope-3 supplier changes only Scope 3 (and its coverage), not Scope 1 / 2
    org_no_s3 = _create_org(base, snap, rev, method_ref, [])
    g = org_no_s3["result"]["groups"]
    check("excluding_supplier_changes_only_scope3",
          L._isclose(g["on_site_direct"]["value"], s1, tol=1e-9)
          and L._isclose(g["purchased_energy_lifecycle"]["value"], s2, tol=1e-9)
          and (g["other_value_chain"]["value"] in (None, 0.0))
          and "purchased_material_upstream" in org_no_s3["result"]["coverage"]["missing_categories"],
          {"scope1": g["on_site_direct"]["value"], "scope2": g["purchased_energy_lifecycle"]["value"],
           "scope3": g["other_value_chain"]["value"], "missing": org_no_s3["result"]["coverage"]["missing_categories"]})

    # 6. regrouping the SAME included activity under a renamed category preserves the total
    regroup = deepcopy(method)
    cats = regroup["manifest"]["classification_rules"]["other_value_chain_categories"]
    regroup["manifest"]["classification_rules"]["other_value_chain_categories"] = {
        "custom_upstream_group": {**cats["purchased_material_upstream"]}}
    regroup["version"] = f"1.0.1-{uuid.uuid4().hex[:8]}"
    regroup_ref = f"{regroup['package_id']}@{regroup['version']}"
    L._register_and_bind(base, APP_ID, regroup, regroup_ref)
    activity_regrouped = {**activity, "category": "custom_upstream_group"}
    org_regroup = _create_org(base, snap, rev, regroup_ref, [activity_regrouped])
    check("regroup_by_custom_dimension_preserves_total",
          L._isclose(org_regroup["result"]["combined_total"], result["combined_total"], tol=1e-6),
          {"original_total": result["combined_total"], "regrouped_total": org_regroup["result"]["combined_total"]})

    # 7. screen, org API, frozen reference/hash and export all share one identity
    record_id = org["id"]
    readback = L._request(base, "GET", f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}")
    xlsx, _ = L._bytes(base, f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}/export.xlsx")
    report, _ = L._bytes(base, f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}/report-data")
    html, _ = L._bytes(base, f"{API}/applications/{APP_ID}/organization-lifecycle-inventories/{record_id}/full-report.html")
    report_json = json.loads(report.decode("utf-8")) if isinstance(report, bytes) else report
    # The report projection carries no org hash of its own; the shared frozen identity is the same
    # source snapshot and the same recorded combined total across the org result, readback and report.
    check("all_surfaces_share_frozen_identity",
          readback["content_sha256"] == result["content_sha256"]
          and len(xlsx) > 0 and len(html) > 0 and "<html" in html.decode("utf-8", "replace").lower()
          and report_json["snapshot_id"] == result["source_snapshot"]["id"]
          and L._isclose(float(report_json["complete_total"]), float(result["combined_total"]), tol=1e-9),
          {"content_sha256": result["content_sha256"], "report_snapshot": report_json.get("snapshot_id"),
           "report_complete_total": report_json.get("complete_total"), "combined_total": result["combined_total"],
           "xlsx_bytes": len(xlsx), "html_bytes": len(html)})

    payload = {"status": "pass" if all(c["status"] == "pass" for c in checks) else "fail",
               "counts": {"pass": sum(c["status"] == "pass" for c in checks),
                          "fail": sum(c["status"] == "fail" for c in checks)},
               "synthetic": True, "material_port": port["exchange_id"],
               "expected": {"scope1": fg_expected, "scope2": bg_expected},
               "org": org, "checks": checks}
    (out / "e2-nonzero-scope3.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    for c in checks:
        print(("PASS " if c["status"] == "pass" else "FAIL ") + c["name"],
              "" if c["status"] == "pass" else json.dumps(c["detail"], ensure_ascii=False)[:300])
    print("E2 VERDICT:", payload["status"], payload["counts"])
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18960")
    parser.add_argument("--engine-url", default="http://127.0.0.1:18931")
    parser.add_argument("--evidence", type=Path, required=True)
    # Optional identity overrides: the defaults are the DEV seed's uuid5 IDs; the PACKAGED seed
    # installs different (also deterministic) UUIDs. Left unset, every constant is unchanged and
    # the existing dev evidence stays valid.
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--app-id", default=None)
    parser.add_argument("--supply-project", default=None)
    parser.add_argument("--supply-version", type=int, default=None)
    parser.add_argument("--grid-port", default=None)
    args = parser.parse_args()
    for _name, _val in (("MODEL_ID", args.model_id), ("APP_ID", args.app_id),
                        ("SUPPLY_PROJECT", args.supply_project), ("SUPPLY_VERSION", args.supply_version),
                        ("GRID_PORT", args.grid_port)):
        if _val is not None:
            globals()[_name] = _val
    res = run(args.url, args.engine_url, args.evidence)
    raise SystemExit(0 if res["status"] == "pass" else 1)
