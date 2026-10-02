"""Split a frozen EF climate answer by controlled and exact project-supply processes."""
from math import isclose, isfinite

from ..analysis.project_background_mfa import project_supply_links
from ..errors import DomainError
from ..hashing import canonical_json_sha256


def project_supply_climate(snapshot, revision, manifest, *, retain_unsupported_paths=False):
    receipt = snapshot.provider_receipt or {}
    basis = receipt.get("calculation_basis") or {}
    pins = basis.get("project_background_pins") or []
    source_rows = receipt.get("project_background_process_receipts") or []
    rules = manifest.get("classification_rules") or {}
    formula = manifest.get("formula_graph") or {}
    optional_supply = rules.get("energy_path_source") == "optional_project_background_process_receipts"
    if ((not pins and not optional_supply) or len(pins) != len(source_rows) or basis.get("mapped_background_process_pins")
            or basis.get("background_process_pins") or snapshot.native_background_climate is not None
            or (pins and receipt.get("provenance", {}).get("project_background_pins_hash") != canonical_json_sha256(pins))):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_SOURCE_INVALID",
                          message="frozen project supply must be exact and exclusive", status_code=422)
    links, issues = project_supply_links({"provider_receipt": receipt,
                                         "internal_transfers": snapshot.internal_transfers})
    if issues or len(links) != len(pins):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_TRANSFER_INVALID",
                          message="project supply transfer does not reconcile", status_code=422)
    sources = {}
    for row in source_rows:
        pin = row["pin"]
        process_id = row.get("source_process_uuid")
        if (not process_id or process_id in sources
                or pin.get("claim_role") != rules.get("accepted_project_claim_role")):
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_IDENTITY_INVALID",
                              message="project supply identity or claim is unsupported", status_code=422)
        sources[process_id] = row
    controlled = {str(node["process_uuid"]) for node in revision.graph_snapshot.get("nodes", [])}
    if not controlled or controlled.intersection(sources):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_OVERLAP",
                          message="project supply overlaps controlled foreground", status_code=422)
    lcia = snapshot.lcia_results or {}
    indicator_key = formula.get("total_indicator_key")
    unit = formula.get("result_unit")
    method = formula.get("lcia_method")
    receipts = lcia.get("indicator_contribution_receipts") or []
    matches = [item for item in receipts if item.get("canonical_indicator_key") == indicator_key]
    results = [item for item in lcia.get("indicator_results") or []
               if item.get("canonical_indicator_key") == indicator_key]
    if (formula.get("source_contract") != "provider.lcia.indicator-contribution-receipt.v1"
            or lcia.get("method") != method or len(matches) != 1 or len(results) != 1
            or lcia.get("contribution_receipts_hash") != canonical_json_sha256(receipts)):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_CLIMATE_INVALID",
                          message="frozen EF climate receipt is missing or ambiguous", status_code=422)
    climate = matches[0]
    terms = climate.get("terms") or []
    if (climate.get("schema_version") != formula["source_contract"]
            or climate.get("content_hash") != canonical_json_sha256({k: v for k, v in climate.items() if k != "content_hash"})
            or climate.get("method") != method or climate.get("indicator_unit") != unit
            or results[0].get("unit") != unit or not terms):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_CLIMATE_INVALID",
                          message="frozen EF climate identity does not match the method", status_code=422)
    foreground_value = background_value = 0.0
    contributions = {process_id: 0.0 for process_id in sources}
    characterized_suppliers = set()
    uncharacterized_terms = []
    allow_no_cf = formula.get("no_cf_policy") == "record_uncharacterized_no_numeric_contribution"
    required_flows = set(formula.get("required_characterized_flow_uuids") or [])
    for term in terms:
        process_id = term.get("process_uuid")
        if process_id not in controlled and process_id not in sources:
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_UNCLASSIFIED",
                              message="climate term belongs to an unclassified process", status_code=422)
        try:
            value = float(term["contribution_value"])
        except (KeyError, TypeError, ValueError):
            value = float("nan")
        if (not isfinite(value) or term.get("contribution_unit") != unit
                or term.get("cf_method") != method
                or term.get("cf_runtime_assets_hash") != lcia.get("runtime_assets_hash")):
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_CF_INVALID",
                              message="climate term lacks an explicit compatible factor", status_code=422)
        presence = term.get("cf_presence")
        if presence not in {"explicit_nonzero", "explicit_zero"}:
            if (allow_no_cf and presence == "implicit_zero" and value == 0
                    and term.get("cf_value") == 0 and term.get("flow_uuid")
                    and term["flow_uuid"] not in required_flows
                    and term.get("exchange_id") and not term.get("cf_source_runtime_ids")):
                # Keep absence distinct from an explicitly characterized zero. The complete
                # frozen inventory and term remain available through this exact receipt.
                uncharacterized_terms.append({"process_uuid": process_id,
                    "exchange_id": term["exchange_id"], "flow_uuid": term["flow_uuid"],
                    "flow_version": term.get("flow_version"), "amount": term.get("amount"),
                    "amount_unit": term.get("amount_unit"), "status": "method_has_no_cf",
                    "numeric_contribution": None})
                continue
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_CF_INVALID",
                              message="climate term lacks an explicit compatible factor", status_code=422)
        if process_id in controlled:
            foreground_value += value
        elif process_id in sources:
            background_value += value
            contributions[process_id] += value
            characterized_suppliers.add(process_id)
        else:
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_UNCLASSIFIED",
                              message="climate term belongs to an unclassified process", status_code=422)
    total = foreground_value + background_value
    try:
        climate_total = float(climate["indicator_value"])
        reported_total = float(results[0]["value"])
        receipt_total = float(climate["contribution_total"])
    except (KeyError, TypeError, ValueError):
        climate_total = reported_total = receipt_total = float("nan")
    if (characterized_suppliers != set(sources)
            or not all(isfinite(value) for value in (total, climate_total, reported_total, receipt_total))
            or not isclose(total, receipt_total, rel_tol=1e-9, abs_tol=1e-9)
            or not isclose(total, climate_total, rel_tol=1e-9, abs_tol=1e-9)
            or not isclose(total, reported_total, rel_tol=1e-9, abs_tol=1e-9)):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_TOTAL_MISMATCH",
                          message="controlled and supplier climate terms do not reconcile", status_code=422)
    climate_method = {"id": method, "version": lcia.get("database_release"),
                      "content_sha256": lcia.get("runtime_assets_hash")}
    climate_source = {"contract": formula["source_contract"], "method": climate_method,
                      "indicator_key": indicator_key, "unit": unit,
                      "receipt_content_hash": climate["content_hash"],
                      "project_background_pins_hash": canonical_json_sha256(pins),
                      "suppliers": [{"consumer_exchange_id": row["pin"]["consumer_exchange_id"],
                                     "project_id": row["pin"]["project_id"], "version": row["pin"]["version"],
                                     "source_graph_hash": row["source_graph_hash"],
                                     "process_uuid": row["source_process_uuid"],
                                     "contribution_value": contributions[row["source_process_uuid"]]}
                                    for row in source_rows]}
    if allow_no_cf:
        climate_source["uncharacterized_terms"] = uncharacterized_terms
    mapped = [pin["consumer_exchange_id"] for pin in pins]
    if retain_unsupported_paths:
        energy_paths = set(rules.get("energy_purchase_exchange_ids") or [])
        unsupported = [row for row in climate_source["suppliers"] if row["consumer_exchange_id"] not in energy_paths]
        if unsupported:
            climate_source["unassigned_suppliers"] = [dict(row, status="method_grouping_not_supported", numeric_contribution=None)
                                                       for row in unsupported]
            # Reconciliation above includes every supplier. Only method-declared energy
            # paths enter group 2; valid but unsupported paths remain visible, unassigned.
            background_value = sum(row["contribution_value"] for row in climate_source["suppliers"]
                                   if row["consumer_exchange_id"] in energy_paths)
            mapped = [exchange_id for exchange_id in mapped if exchange_id in energy_paths]
    return foreground_value, background_value, unit, climate_method, climate_source, mapped
