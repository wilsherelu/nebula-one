"""Split a frozen EF climate answer by controlled and exact project-supply processes."""
from math import isclose, isfinite

from ..analysis.project_background_mfa import (
    _group_rows_by_pin, _network_boundary_row, is_network_claim, project_supply_links)
from ..errors import DomainError
from ..hashing import canonical_json_sha256


def project_supply_climate(snapshot, revision, manifest, *, retain_unsupported_paths=False, user_network_paths=()):
    receipt = snapshot.provider_receipt or {}
    basis = receipt.get("calculation_basis") or {}
    pins = basis.get("project_background_pins") or []
    source_rows = receipt.get("project_background_process_receipts") or []
    rules = manifest.get("classification_rules") or {}
    category_receipts = rules.get("non_energy_path_source") == "project_background_category_receipts_v1"
    formula = manifest.get("formula_graph") or {}
    optional_supply = rules.get("energy_path_source") == "optional_project_background_process_receipts"
    accepted_roles_value = rules.get("accepted_project_claim_roles")
    accepted_roles = set(accepted_roles_value) if accepted_roles_value is not None else {rules.get("accepted_project_claim_role")}
    if ((not pins and not optional_supply) or basis.get("mapped_background_process_pins")
            or basis.get("background_process_pins") or snapshot.native_background_climate is not None
            or (pins and receipt.get("provenance", {}).get("project_background_pins_hash") != canonical_json_sha256(pins))):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_SOURCE_INVALID",
                          message="frozen project supply must be exact and exclusive", status_code=422)
    groups = _group_rows_by_pin(pins, source_rows)
    if groups is None:
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_SOURCE_INVALID",
                          message="frozen project supply must be exact and exclusive", status_code=422)
    for pin, rows in groups:
        user_network = is_network_claim(pin) and pin['consumer_exchange_id'] in user_network_paths
        if pin.get("claim_role") not in accepted_roles and not user_network:
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_IDENTITY_INVALID",
                              message="project supply identity or claim is unsupported", status_code=422)
        if is_network_claim(pin):
            if _network_boundary_row(pin, rows) is None:
                raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_NETWORK_MAPPING_INVALID",
                                  message="closed network node mapping is missing or ambiguous", status_code=422)
        elif len(rows) != 1:
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_SOURCE_INVALID",
                              message="single-process supply must have exactly one receipt row", status_code=422)
    links, issues = project_supply_links({"provider_receipt": receipt,
                                         "internal_transfers": snapshot.internal_transfers})
    if issues or len(links) != len(pins):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_TRANSFER_INVALID",
                          message="project supply transfer does not reconcile", status_code=422)
    path_of: dict[str, int] = {}
    for group_index, (pin, rows) in enumerate(groups):
        for row in rows:
            process_id = row.get("source_process_uuid")
            if not process_id or process_id in path_of:
                raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_IDENTITY_INVALID",
                                  message="project supply process identity is missing or duplicated", status_code=422)
            path_of[process_id] = group_index
    controlled = {str(node["process_uuid"]) for node in revision.graph_snapshot.get("nodes", [])}
    if not controlled or controlled.intersection(path_of):
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
    contributions = {process_id: 0.0 for process_id in path_of}
    characterized_suppliers = set()
    uncharacterized_terms = []
    allow_no_cf = formula.get("no_cf_policy") == "record_uncharacterized_no_numeric_contribution"
    required_flows = set(formula.get("required_characterized_flow_uuids") or [])
    coverage = climate.get("characterization_coverage")
    if coverage is not None:
        if coverage.get("schema_version") != "provider.lcia.characterization-coverage.v1":
            raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_CF_INVALID",
                              message="unsupported characterization coverage", status_code=422)
        for gap in coverage.get("uncharacterized_exchanges", []):
            if (gap.get("process_uuid") not in controlled | set(path_of)
                    or gap.get("flow_uuid") in required_flows
                    or gap.get("numeric_contribution") is not None):
                raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_CF_INVALID",
                                  message="invalid or required missing factor", status_code=422)
            uncharacterized_terms.append({**gap, "status": "method_has_no_cf"})
    for term in terms:
        process_id = term.get("process_uuid")
        if process_id not in controlled and process_id not in path_of:
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
        elif process_id in path_of:
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
    if ((not category_receipts and {path_of[process_id] for process_id in characterized_suppliers}
                 != set(range(len(groups))))
            or not all(isfinite(value) for value in (total, climate_total, reported_total, receipt_total))
            or not isclose(total, receipt_total, rel_tol=1e-9, abs_tol=1e-9)
            or not isclose(total, climate_total, rel_tol=1e-9, abs_tol=1e-9)
            or not isclose(total, reported_total, rel_tol=1e-9, abs_tol=1e-9)):
        raise DomainError(code="ORGANIZATION_PROJECT_SUPPLY_TOTAL_MISMATCH",
                          message="controlled and supplier climate terms do not reconcile", status_code=422)
    climate_method = {"id": method, "version": lcia.get("database_release"),
                      "content_sha256": lcia.get("runtime_assets_hash")}
    no_cf_processes = {term["process_uuid"] for term in uncharacterized_terms}

    def _node_status_and_value(process_id):
        # Reproduces the exact leaf formula per process, so a single-node path is unchanged.
        if process_id not in characterized_suppliers:
            return ("method_has_no_cf" if process_id in no_cf_processes else "contribution_terms_missing"), None
        return ("partial_characterization" if process_id in no_cf_processes else "calculated"), contributions[process_id]

    def _aggregate_network_path(details):
        # The engine returns one background contribution term per emitting node; a network node
        # with no term for this indicator (e.g. a lossless internal transport) is engine-confirmed
        # zero, not a missing factor, so it must not null the whole path. Sum the characterized
        # nodes and flag the path as partial only when some node carried no numeric term.
        characterized = [item for item in details if item["contribution_value"] is not None]
        if not characterized:
            statuses = {item["status"] for item in details}
            return ("method_has_no_cf" if "method_has_no_cf" in statuses else "contribution_terms_missing"), None
        value = sum(item["contribution_value"] for item in characterized)
        statuses = {item["status"] for item in characterized}
        if len(characterized) == len(details) and statuses == {"calculated"}:
            return "calculated", value
        return "partial_characterization", value

    suppliers = []
    for pin, rows in groups:
        network = is_network_claim(pin)
        details = []
        for row in rows:
            process_id = row["source_process_uuid"]
            status, value = _node_status_and_value(process_id)
            details.append({"process_uuid": process_id, "expanded_node_id": row.get("expanded_node_id"),
                            "source_graph_hash": row["source_graph_hash"],
                            "status": status, "contribution_value": value})
        if network:
            boundary = _network_boundary_row(pin, rows)
            status, contribution_value = _aggregate_network_path(details)
        else:
            boundary = rows[0]
            status, contribution_value = details[0]["status"], details[0]["contribution_value"]
        supplier = {"consumer_exchange_id": pin["consumer_exchange_id"], "project_id": pin["project_id"],
                    "version": pin["version"], "source_graph_hash": boundary["source_graph_hash"],
                    "process_uuid": boundary["source_process_uuid"], "contribution_value": contribution_value,
                    "status": status}
        if network:
            supplier["claim_role"] = pin["claim_role"]
            supplier["network_nodes"] = details
        suppliers.append(supplier)
    climate_source = {"contract": formula["source_contract"], "method": climate_method,
                      "indicator_key": indicator_key, "unit": unit,
                      "receipt_content_hash": climate["content_hash"],
                      "project_background_pins_hash": canonical_json_sha256(pins),
                      "suppliers": suppliers}
    if user_network_paths:
        climate_source['user_rule_network_paths'] = sorted(set(user_network_paths).intersection(
            pin['consumer_exchange_id'] for pin in pins if is_network_claim(pin)))
    if allow_no_cf or coverage is not None:
        climate_source["uncharacterized_terms"] = uncharacterized_terms
    if coverage is not None:
        climate_source["characterization_coverage"] = coverage
    mapped = [pin["consumer_exchange_id"] for pin in pins]
    if category_receipts:
        energy_paths = set(rules.get("energy_purchase_exchange_ids") or [])
        categories = rules.get("other_value_chain_categories") or {}
        assignments = {}
        for category, rule in categories.items():
            for exchange_id in rule.get("eligible_consumer_exchange_ids") or []:
                if exchange_id in energy_paths or exchange_id in assignments:
                    raise DomainError(code="ORGANIZATION_LIFECYCLE_OVERLAP", message="method assigns one supply port to multiple groups", status_code=422)
                assignments[exchange_id] = category
        category_rows, unassigned, energy_rows = [], [], []
        for row in suppliers:
            exchange_id = row["consumer_exchange_id"]
            if exchange_id in energy_paths:
                energy_rows.append(row)
            elif exchange_id in assignments and categories[assignments[exchange_id]].get("boundary_status") == "selected":
                category_rows.append({**row, "category": assignments[exchange_id]})
            else:
                unassigned.append(dict(row, status="method_grouping_not_supported", numeric_contribution=None))
        climate_source["category_suppliers"] = category_rows
        climate_source["energy_suppliers"] = energy_rows
        if unassigned:
            climate_source["unassigned_suppliers"] = unassigned
        background_value = sum(row["contribution_value"] for row in energy_rows if row["contribution_value"] is not None)
        mapped = [row["consumer_exchange_id"] for row in energy_rows if row["contribution_value"] is not None]
    elif retain_unsupported_paths:
        energy_paths = set(rules.get("energy_purchase_exchange_ids") or [])
        unsupported = [row for row in suppliers if row["consumer_exchange_id"] not in energy_paths]
        if unsupported:
            climate_source["unassigned_suppliers"] = [dict(row, status="method_grouping_not_supported", numeric_contribution=None)
                                                       for row in unsupported]
            # Reconciliation above includes every supplier. Only method-declared energy
            # paths enter group 2; valid but unsupported paths remain visible, unassigned.
            background_value = sum(row["contribution_value"] for row in suppliers
                                   if row["consumer_exchange_id"] in energy_paths)
            mapped = [exchange_id for exchange_id in mapped if exchange_id in energy_paths]
    return foreground_value, background_value, unit, climate_method, climate_source, mapped
