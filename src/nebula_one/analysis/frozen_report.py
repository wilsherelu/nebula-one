"""Report projections of frozen answers, never emission factors or a second solve."""
from collections import defaultdict
from math import isclose

from ..errors import DomainError
from .solved_mfa import _exchange_catalog, _process_catalog


def names(graph, workspace):
    processes, node_to_process = _process_catalog(graph)
    exchanges = _exchange_catalog(graph)
    for field in workspace.get("fields", []):
        # A linked input shares its quantity key with the supplier output, but retains
        # its own exchange identity for report labels.
        exchange_id = (f"{field['process_id']}::{field['port_id']}"
                       if field.get('process_id') and field.get('port_id') else field['key'])
        exchanges.setdefault(exchange_id, {})["name"] = field["label"]
        if field.get('description'):
            exchanges[exchange_id]['name'] += ' — ' + field['description']
        process = node_to_process.get(field.get('process_id'))
        if process in processes and field.get('process'):
            processes[process]['label'] = field['process']
    return processes, exchanges


def detail_row(processes, exchanges, exchange_id, process_id, **data):
    process = processes.get(process_id, {}).get("label")
    return {"exchange_id": exchange_id, "process_id": process_id,
            "process_name": process if process != process_id else None,
            "flow_name": exchanges.get(exchange_id, {}).get("name") or None, **data}


def contributions(rows, expected):
    grouped = defaultdict(float)
    labels = {}
    for row in rows:
        if row["contribution_value"] is not None:
            key = (row["group"], row["process_id"], row["contribution_unit"])
            grouped[key] += float(row["contribution_value"])
            labels[key] = row["process_name"]
    for group, value in expected.items():
        if value is not None and not isclose(sum(v for k, v in grouped.items() if k[0] == group), float(value), rel_tol=1e-9, abs_tol=1e-8):
            raise DomainError(code="REPORT_CONTRIBUTIONS_DO_NOT_RECONCILE", message="Frozen detail contributions differ from the recorded group total", status_code=409)
    return [{"group": k[0], "process_id": k[1], "process_name": labels[k],
             "contribution_value": v, "contribution_unit": k[2]} for k, v in grouped.items()]


def cbam_report(result, graph, workspace):
    processes, exchanges = names(graph, workspace)
    direct = result["attributed_emissions"]["direct"]
    counted = {row["exchange_id"]: row for row in direct.get("exchanges", [])}
    rows = []
    for item in (result.get("coverage") or {}).get("exchanges", []):
        contribution = counted.get(item["exchange_id"])
        rows.append(detail_row(processes, exchanges, item["exchange_id"], item["process_uuid"],
            group="direct", quantity=item.get("amount"), quantity_unit=item.get("unit"),
            contribution_value=contribution["amount"] if contribution else None,
            contribution_unit=contribution["unit"] if contribution else direct.get("source_unit"),
            status=item["disposition"], basis=item.get("basis"), identity=item))
    # Direct row amounts and their total source_value use the same unit; never confuse t and kg.
    projected = contributions(rows, {"direct": direct.get("source_value")})
    indirect = result["attributed_emissions"].get("indirect") or {}
    return {"summary": [{"group": "direct", "value": direct["value"], "unit": direct["unit"], "status": "counted"},
                        {"group": "indirect", "value": (result["attributed_emissions"].get("indirect") or {}).get("value"),
                         "unit": indirect.get("unit"), "status": "counted" if indirect.get("value") is not None else "not_counted"}],
            "complete_total": result["specific_embedded_emissions"].get("value"),
            "details": rows, "process_contributions": projected,
            "gaps": [{"name": row["item"], "status": row["state"], "basis": row.get("effect"), "identity": row}
                     for row in (result.get("coverage") or {}).get("open_items", [])],
            "outside_boundary": [], "uncharacterized": []}


def organization_report(result, snapshot, graph, workspace):
    processes, exchanges = names(graph, workspace)
    source = result.get("climate_source") or {}
    groups = result["groups"]
    scale = result["activity_basis"]["scale_factor"]
    controlled = {node.get("process_uuid") for node in graph.get("nodes", [])
                  if node["id"] in result["organizational_boundary"]["controlled_process_ids"]}
    energy = {row["process_uuid"] for row in source.get("energy_suppliers", source.get("suppliers", []))}
    other = {row["process_uuid"] for row in source.get("category_suppliers", [])}
    receipts = (snapshot.get("lcia_results") or {}).get("indicator_contribution_receipts") or []
    receipt = next((r for r in receipts if r.get("canonical_indicator_key") == source.get("indicator_key")), None)
    unsupported = {row["exchange_id"]: row for row in source.get("uncharacterized_terms", [])}
    rows = []
    for term in (receipt or {}).get("terms", []):
        process = term["process_uuid"]
        group = "on_site_direct" if process in controlled else "purchased_energy_lifecycle" if process in energy else "other_value_chain" if process in other else "unassigned"
        no_cf = term["exchange_id"] in unsupported
        value = None if no_cf or group == "unassigned" else term.get("contribution_value")
        rows.append(detail_row(processes, exchanges, term["exchange_id"], process,
            group=group, quantity=term.get("amount"), quantity_unit=term.get("amount_unit"),
            contribution_value=value * scale if value is not None else None,
            contribution_unit=term.get("contribution_unit"), status="method_has_no_cf" if no_cf else "unassigned" if group == "unassigned" else "explicit_zero_cf" if term.get("cf_presence") == "explicit_zero" else "counted",
            basis=None, identity=term))
    for category in groups["other_value_chain"]["categories"]:
        for activity in category.get("activities", []) + category.get("proxy_activities", []):
            field = next((f for f in workspace.get("fields", []) if f["key"] == activity["consumer_exchange_id"]), {})
            process = next((node.get("process_uuid", node["id"]) for node in graph.get("nodes", []) if node["id"] == field.get("process_id")), field.get("process_id"))
            proxy = activity.get("evidence_role") == "demonstration_proxy"
            rows.append(detail_row(processes, exchanges, activity["consumer_exchange_id"], process,
                group="other_value_chain", quantity=activity["quantity"], quantity_unit=activity["activity_unit"],
                contribution_value=None if proxy else activity["emissions"]["value"], contribution_unit=activity["emissions"]["unit"],
                status="proxy_reference_only" if proxy else "counted", basis=activity.get("factor_source"), identity=activity))
    # Some older native-domain answers lack per-process evidence. Keep their summary, explicitly
    # disclose the unavailable breakdown instead of manufacturing process contributions.
    expected = {key: value["value"] for key, value in groups.items()}
    projected = contributions(rows, expected) if receipt else []
    categories = groups["other_value_chain"]["categories"]
    return {"summary": [{"group": key, "value": value["value"], "unit": value["unit"], "status": value["status"]} for key, value in groups.items()],
            "complete_total": result["combined_total"], "details": rows, "process_contributions": projected,
            "detail_status": "available" if receipt else "frozen_process_contribution_evidence_unavailable",
            "gaps": [{"name": row["name"], "status": row["status"], "identity": row} for row in categories
                     if row["category"] in result["coverage"]["missing_categories"]]
                    + [{"name": exchanges.get(key, {}).get("name"), "status": "missing_energy_path", "identity": {"exchange_id": key}}
                       for key in result["coverage"].get("missing_energy_paths", [])],
            "outside_boundary": [{"name": row["name"], "status": row["status"], "identity": row} for row in categories if row["status"] == "not_in_boundary"],
            "uncharacterized": [row for row in rows if row["status"] == "method_has_no_cf"]}
