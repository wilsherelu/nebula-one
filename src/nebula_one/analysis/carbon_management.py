from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from ..analysis.energy_carrier import EnergyCarrierSolved
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .dependency_gap import dependency_gap


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _identity(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("source_namespace") or "").strip(),
        str(item.get("flow_uuid") or "").strip(),
        str(item.get("version") or "").strip(),
    )


def _rules(manifest: dict[str, Any], key: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    classification = manifest.get("classification_rules")
    raw = classification.get(key) if isinstance(classification, dict) else None
    if not isinstance(raw, list) or not raw:
        _fail("CARBON_METHOD_PACKAGE_INVALID", f"classification_rules.{key} is required")
    parsed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            _fail("CARBON_METHOD_PACKAGE_INVALID", f"{key}[{index}] must be an object")
        identity = _identity(item)
        category = str(item.get("category") or "").strip()
        if not all(identity) or not category:
            _fail("CARBON_METHOD_PACKAGE_INVALID", f"{key}[{index}] lacks exact identity or category")
        if identity in parsed:
            _fail("CARBON_METHOD_PACKAGE_INVALID", f"{key} contains a duplicate exact Flow identity")
        parsed[identity] = item
    return parsed


def _climate_total(
    lcia_results: dict[str, Any], formula: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    method = str(formula.get("lcia_method") or "").strip()
    indicator_key = str(formula.get("total_indicator_key") or "").strip()
    expected_unit = str(formula.get("result_unit") or "").strip()
    if not all((method, indicator_key, expected_unit)):
        _fail("CARBON_METHOD_PACKAGE_INVALID", "formula_graph lacks the climate indicator contract")
    if not isinstance(lcia_results, dict) or not lcia_results:
        return None, [{
            "code": "CLIMATE_TOTAL_UNAVAILABLE",
            "message": "the frozen solve did not return an LCIA result",
        }]
    actual_method = str(lcia_results.get("method") or "").strip()
    indicators = lcia_results.get("indicator_results")
    if actual_method != method or not isinstance(indicators, list):
        return None, [{
            "code": "CLIMATE_TOTAL_UNAVAILABLE",
            "message": "the frozen solve did not return the method required by the carbon package",
        }]
    matches = [
        item for item in indicators
        if isinstance(item, dict)
        and str(item.get("canonical_indicator_key") or "").strip() == indicator_key
    ]
    if len(matches) != 1:
        _fail(
            "CARBON_TOTAL_INDICATOR_NOT_UNIQUE",
            "carbon management requires exactly one total climate-change indicator",
            indicator_key=indicator_key,
            match_count=len(matches),
        )
    item = matches[0]
    value = item.get("value")
    unit = str(item.get("unit") or item.get("indicator_unit") or "").strip()
    if unit != expected_unit or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _fail("CARBON_TOTAL_INDICATOR_INVALID", "the total climate-change indicator has an invalid value or unit")
    return {
        "indicator_key": indicator_key,
        "value": float(value),
        "unit": unit,
    }, []


def _number(value: Any, *, code: str, message: str, **details: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _fail(code, message, **details)
    return float(value)


def _same_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)


def _contribution_attribution(
    *,
    lcia_results: dict[str, Any],
    climate_total: dict[str, Any] | None,
    scaled_elementary_exchanges: list[dict[str, Any]],
    elementary_receipts: dict[str, dict[str, Any]],
    emission_rules: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, bool]]:
    raw_receipts = lcia_results.get("indicator_contribution_receipts")
    if raw_receipts is None:
        return ({
            "coverage": "total_only" if climate_total is not None else "physical_inventory_only",
            "indicator_receipt": None,
            "categories": [
                {"category": key, "value": None, "unit": None, "reason": "provider contribution receipts unavailable"}
                for key in ("direct", "purchased_energy", "supply_chain")
            ],
            "hotspots": [],
            "scope_1_2_3_statement": False,
        }, [{
            "code": "CARBON_ATTRIBUTION_UNAVAILABLE",
            "message": "the provider snapshot has no per-source LCIA contribution receipts; category CO2e values remain null",
        }], {
            "contribution_receipts_present": False,
            "contribution_receipts_hash_valid": False,
            "climate_contribution_receipt_hash_valid": False,
            "contribution_terms_trace_to_scaled_exchanges": False,
            "contribution_total_reconciled": False,
        })
    if not isinstance(raw_receipts, list):
        _fail("CARBON_CONTRIBUTION_RECEIPTS_INVALID", "indicator contribution receipts must be a list")
    aggregate_hash = str(lcia_results.get("contribution_receipts_hash") or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", aggregate_hash) is None or aggregate_hash != canonical_json_sha256(raw_receipts):
        _fail("CARBON_CONTRIBUTION_RECEIPTS_HASH_MISMATCH", "indicator contribution receipts do not match their provider hash")
    if climate_total is None:
        _fail("CARBON_CONTRIBUTION_TOTAL_UNAVAILABLE", "contribution receipts cannot be consumed without the climate-change total")

    matches = [
        item for item in raw_receipts
        if isinstance(item, dict)
        and str(item.get("canonical_indicator_key") or "").strip() == climate_total["indicator_key"]
    ]
    if len(matches) != 1:
        _fail(
            "CARBON_CONTRIBUTION_RECEIPT_NOT_UNIQUE",
            "carbon management requires exactly one climate-change contribution receipt",
            match_count=len(matches),
        )
    receipt = matches[0]
    receipt_hash = str(receipt.get("content_hash") or "").strip()
    receipt_basis = dict(receipt)
    receipt_basis.pop("content_hash", None)
    if re.fullmatch(r"[0-9a-f]{64}", receipt_hash) is None or receipt_hash != canonical_json_sha256(receipt_basis):
        _fail("CARBON_CONTRIBUTION_RECEIPT_HASH_MISMATCH", "the climate-change contribution receipt hash is invalid")

    method = str(lcia_results.get("method") or "").strip()
    release = str(lcia_results.get("database_release") or "").strip()
    unit = str(receipt.get("indicator_unit") or "").strip()
    indicator_value = _number(receipt.get("indicator_value"), code="CARBON_CONTRIBUTION_RECEIPT_INVALID", message="the climate-change contribution receipt has an invalid indicator value")
    contribution_total = _number(receipt.get("contribution_total"), code="CARBON_CONTRIBUTION_RECEIPT_INVALID", message="the climate-change contribution receipt has an invalid contribution total")
    reconciliation_delta = _number(receipt.get("reconciliation_delta"), code="CARBON_CONTRIBUTION_RECEIPT_INVALID", message="the climate-change contribution receipt has an invalid reconciliation delta")
    if (
        receipt.get("schema_version") != "provider.lcia.indicator-contribution-receipt.v1"
        or str(receipt.get("method") or "").strip() != method
        or str(receipt.get("database_release") or "").strip() != release
        or unit != climate_total["unit"]
        or not _same_number(indicator_value, float(climate_total["value"]))
        or not _same_number(contribution_total, indicator_value)
        or not _same_number(reconciliation_delta, 0.0)
    ):
        _fail("CARBON_CONTRIBUTION_RECEIPT_MISMATCH", "the climate-change contribution receipt does not reconcile with the frozen LCIA total")

    lcia_solve_hash = str(lcia_results.get("solve_hash") or "").strip()
    runtime_assets_hash = str(lcia_results.get("runtime_assets_hash") or "").strip()
    for field, expected in (("solve_hash", lcia_solve_hash), ("runtime_assets_hash", runtime_assets_hash)):
        actual = str(receipt.get(field) or "").strip()
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None or actual != expected:
            _fail("CARBON_CONTRIBUTION_RECEIPT_PROVENANCE_MISMATCH", f"the contribution receipt has an invalid {field}")
    if receipt.get("provider_commit") != lcia_results.get("provider_commit"):
        _fail("CARBON_CONTRIBUTION_RECEIPT_PROVENANCE_MISMATCH", "the contribution receipt provider commit does not match the LCIA result")

    scaled_by_exchange: dict[str, dict[str, Any]] = {}
    for exchange in scaled_elementary_exchanges:
        exchange_id = str(exchange.get("exchange_id") or "").strip()
        if not exchange_id or exchange_id in scaled_by_exchange:
            _fail("CARBON_CONTRIBUTION_EXCHANGE_AMBIGUOUS", "scaled elementary exchanges require unique exact exchange IDs")
        scaled_by_exchange[exchange_id] = exchange
    terms = receipt.get("terms")
    if not isinstance(terms, list):
        _fail("CARBON_CONTRIBUTION_RECEIPT_INVALID", "the climate-change contribution terms must be a list")
    term_ids: set[str] = set()
    hotspots: list[dict[str, Any]] = []
    direct_total = 0.0
    direct_count = 0
    supplied_total = 0.0
    unclassified_count = 0
    for term in terms:
        if not isinstance(term, dict) or term.get("schema_version") != "provider.lcia.contribution-term.v1":
            _fail("CARBON_CONTRIBUTION_TERM_INVALID", "a contribution term has an unsupported schema")
        exchange_id = str(term.get("exchange_id") or "").strip()
        if not exchange_id or exchange_id in term_ids or exchange_id not in scaled_by_exchange:
            _fail("CARBON_CONTRIBUTION_TERM_EXCHANGE_MISMATCH", "a contribution term does not map one-to-one to a scaled elementary exchange", exchange_id=exchange_id)
        term_ids.add(exchange_id)
        exchange = scaled_by_exchange[exchange_id]
        elementary_receipt = elementary_receipts.get(exchange_id)
        if elementary_receipt is None:
            _fail("CARBON_CONTRIBUTION_TERM_RECEIPT_MISSING", "a contribution term lacks an elementary Flow receipt", exchange_id=exchange_id)
        identity = (
            str(term.get("source_namespace") or "").strip(),
            str(term.get("flow_uuid") or "").strip(),
            str(term.get("flow_version") or "").strip(),
        )
        expected_identity = _identity(elementary_receipt)
        amount = _number(term.get("amount"), code="CARBON_CONTRIBUTION_TERM_INVALID", message="a contribution term has an invalid scaled amount", exchange_id=exchange_id)
        expected_amount = _number(exchange.get("amount"), code="CARBON_CONTRIBUTION_TERM_INVALID", message="a scaled elementary exchange has an invalid amount", exchange_id=exchange_id)
        contribution = _number(term.get("contribution_value"), code="CARBON_CONTRIBUTION_TERM_INVALID", message="a contribution term has an invalid contribution value", exchange_id=exchange_id)
        if (
            identity != expected_identity
            or str(term.get("process_uuid") or "").strip() != str(exchange.get("process_id") or "").strip()
            or str(term.get("amount_unit") or "").strip() != str(exchange.get("unit") or "").strip()
            or str(term.get("direction") or "").strip() != str(exchange.get("direction") or "").strip()
            or str(term.get("contribution_unit") or "").strip() != unit
            or str(term.get("cf_method") or "").strip() != method
            or str(term.get("cf_database_release") or "").strip() != release
            or str(term.get("cf_indicator_key") or "").strip() != climate_total["indicator_key"]
            or str(term.get("cf_runtime_assets_hash") or "").strip() != runtime_assets_hash
            or str(term.get("solve_hash") or "").strip() != lcia_solve_hash
            or not _same_number(amount, expected_amount)
        ):
            _fail("CARBON_CONTRIBUTION_TERM_MISMATCH", "a contribution term conflicts with the frozen exchange or LCIA provenance", exchange_id=exchange_id)
        cf_hash = str(term.get("cf_hash") or "").strip()
        if re.fullmatch(r"[0-9a-f]{64}", cf_hash) is None:
            _fail("CARBON_CONTRIBUTION_TERM_INVALID", "a contribution term lacks an exact characterization-factor hash", exchange_id=exchange_id)

        rule = emission_rules.get(identity)
        category = "unclassified"
        source_category = None
        if rule is not None:
            exchange_ids = rule.get("exchange_ids")
            if exchange_ids is None or exchange_id in exchange_ids:
                category = "direct"
                source_category = str(rule["category"])
                direct_total += contribution
                direct_count += 1
        if category == "unclassified":
            unclassified_count += 1
        supplied_total += contribution
        hotspots.append({
            "process_id": str(term.get("process_uuid") or ""),
            "exchange_id": exchange_id,
            "flow_identity": {"source_namespace": identity[0], "flow_uuid": identity[1], "version": identity[2]},
            "amount": amount,
            "amount_unit": str(term.get("amount_unit") or ""),
            "contribution_value": contribution,
            "contribution_unit": unit,
            "classification": category,
            "source_category": source_category,
            "cf_presence": str(term.get("cf_presence") or ""),
            "cf_hash": cf_hash,
            "flow_snapshot_hash": term.get("flow_snapshot_hash"),
        })
    if term_ids != set(scaled_by_exchange):
        _fail("CARBON_CONTRIBUTION_TERM_COVERAGE_MISMATCH", "contribution terms do not cover every scaled elementary exchange")
    if not _same_number(supplied_total, contribution_total):
        _fail("CARBON_CONTRIBUTION_TERM_TOTAL_MISMATCH", "contribution terms do not reconcile with the provider contribution total")

    hotspots.sort(key=lambda item: (-abs(float(item["contribution_value"])), item["exchange_id"]))
    for rank, item in enumerate(hotspots, start=1):
        item["rank"] = rank
    categories = [
        {"category": "direct", "value": direct_total if direct_count else None, "unit": unit if direct_count else None, "reason": None if direct_count else "no contribution term matched an exact direct-emission rule", "term_count": direct_count},
        {"category": "purchased_energy", "value": None, "unit": None, "reason": "no explicit purchased-energy contribution classification rule", "term_count": 0},
        {"category": "supply_chain", "value": None, "unit": None, "reason": "no explicit supply-chain contribution classification rule", "term_count": 0},
    ]
    issues = []
    if unclassified_count:
        issues.append({
            "code": "CARBON_CONTRIBUTIONS_PARTIALLY_CLASSIFIED",
            "message": f"exact contribution hotspots are available, but {unclassified_count} term(s) remain outside an explicit carbon category rule",
        })
    issues.append({
        "code": "CARBON_SCOPE_CLASSIFICATION_UNAVAILABLE",
        "message": "exact contribution receipts do not by themselves establish an organizational Scope 1, 2, or 3 inventory",
    })
    return ({
        "coverage": "partial_exact_contributions" if unclassified_count else "exact_contributions",
        "indicator_receipt": {
            "canonical_indicator_key": climate_total["indicator_key"],
            "unit": unit,
            "content_hash": receipt_hash,
            "contribution_receipts_hash": aggregate_hash,
            "solve_hash": lcia_solve_hash,
            "provider_commit": receipt.get("provider_commit"),
            "runtime_assets_hash": runtime_assets_hash,
            "term_count": len(hotspots),
            "classified_term_count": direct_count,
        },
        "categories": categories,
        "hotspots": hotspots,
        "scope_1_2_3_statement": False,
    }, issues, {
        "contribution_receipts_present": True,
        "contribution_receipts_hash_valid": True,
        "climate_contribution_receipt_hash_valid": True,
        "contribution_terms_trace_to_scaled_exchanges": True,
        "contribution_total_reconciled": True,
    })


def build_carbon_management(
    *,
    solved_snapshot_id: str,
    solved_snapshot_sha256: str,
    scaled_elementary_exchanges: list[dict[str, Any]],
    lcia_results: dict[str, Any],
    provider_receipt: dict[str, Any],
    reporting_period: dict[str, Any],
    energy_result_id: str,
    energy_result_sha256: str,
    energy_result: EnergyCarrierSolved,
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if method_package_kind != "period_carbon_management":
        _fail("CARBON_METHOD_PACKAGE_KIND_MISMATCH", "carbon.management.v1 requires a period_carbon_management method package")
    if energy_result.solved_snapshot_ref.content_sha256 != solved_snapshot_sha256:
        _fail("CARBON_ENERGY_SNAPSHOT_MISMATCH", "energy and carbon inputs bind different solved snapshots")
    required_period_fields = ("id", "version", "content_sha256")
    if any(not str(reporting_period.get(key) or "").strip() for key in required_period_fields):
        _fail("CARBON_REPORTING_PERIOD_REQUIRED", "carbon management requires an exact frozen reporting period")
    if re.fullmatch(r"[0-9a-f]{64}", str(reporting_period["content_sha256"])) is None:
        _fail("CARBON_REPORTING_PERIOD_REQUIRED", "reporting period content_sha256 is not an exact SHA-256 identity")

    energy_rules = _rules(manifest, "energy_flows")
    emission_rules = _rules(manifest, "direct_emission_flows")
    formula = manifest.get("formula_graph")
    if not isinstance(formula, dict):
        _fail("CARBON_METHOD_PACKAGE_INVALID", "formula_graph is required")

    energy_series: list[dict[str, Any]] = []
    energy_issues: list[dict[str, str]] = []
    for series in energy_result.series:
        categories: dict[str, Decimal] = {}
        entries: list[dict[str, Any]] = []
        for entry in series.entries:
            identity = (
                entry.carrier_flow.source_namespace,
                str(entry.carrier_flow.flow_uuid),
                entry.carrier_flow.version,
            )
            rule = energy_rules.get(identity)
            if rule is None:
                category = "unclassified"
                energy_issues.append({
                    "code": "ENERGY_FLOW_UNCLASSIFIED",
                    "message": f"energy Flow {identity[1]}@{identity[2]} has no exact package classification",
                })
            else:
                category = str(rule["category"])
            categories[category] = categories.get(category, Decimal("0")) + entry.amount
            entries.append({
                "entry_id": entry.entry_id,
                "flow_identity": {
                    "source_namespace": identity[0],
                    "flow_uuid": identity[1],
                    "version": identity[2],
                },
                "category": category,
                "amount": str(entry.amount),
                "unit": entry.unit_symbol,
                "source": entry.source.model_dump(mode="json"),
            })
        energy_series.append({
            "series_id": series.series_id,
            "basis": series.basis.model_dump(mode="json"),
            "unit": series.unit_symbol,
            "unit_identity_sha256": series.unit_identity_sha256,
            "categories": [
                {"category": key, "amount": str(value)}
                for key, value in sorted(categories.items())
            ],
            "entries": entries,
            "total_amount": str(series.total_amount),
        })

    receipts = provider_receipt.get("elementary_flow_receipts")
    if not isinstance(receipts, list) or not receipts:
        _fail("CARBON_ELEMENTARY_FLOW_RECEIPTS_REQUIRED", "direct emissions require exact provider elementary Flow receipts")
    receipt_by_exchange: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        exchange_id = str(receipt.get("exchange_id") or "").strip()
        if exchange_id:
            if exchange_id in receipt_by_exchange:
                _fail("CARBON_ELEMENTARY_FLOW_RECEIPT_AMBIGUOUS", "an elementary exchange has multiple provider receipts", exchange_id=exchange_id)
            receipt_by_exchange[exchange_id] = receipt

    direct_inventory: list[dict[str, Any]] = []
    for exchange in scaled_elementary_exchanges:
        exchange_id = str(exchange.get("exchange_id") or "").strip()
        receipt = receipt_by_exchange.get(exchange_id)
        if receipt is None:
            _fail("CARBON_ELEMENTARY_FLOW_RECEIPT_MISSING", "a scaled elementary exchange lacks an exact provider receipt", exchange_id=exchange_id)
        identity = _identity(receipt)
        rule = emission_rules.get(identity)
        if rule is None:
            continue
        exchange_ids = rule.get("exchange_ids")
        if exchange_ids is not None:
            if not isinstance(exchange_ids, list) or any(
                not isinstance(item, str) or not item.strip() for item in exchange_ids
            ):
                _fail("CARBON_METHOD_PACKAGE_INVALID", "direct emission exchange_ids must be a list of exact IDs")
            if exchange_id not in exchange_ids:
                continue
        amount = exchange.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(float(amount)) or float(amount) < 0:
            _fail("CARBON_DIRECT_EMISSION_INVALID", "a direct emission has an invalid solved amount", exchange_id=exchange_id)
        factor_hash = str(receipt.get("factor_hash") or "").strip()
        if re.fullmatch(r"[0-9a-f]{64}", factor_hash) is None:
            _fail("CARBON_ELEMENTARY_FLOW_RECEIPT_INVALID", "a direct emission receipt lacks an exact EF factor hash", exchange_id=exchange_id)
        direct_inventory.append({
            "exchange_id": exchange_id,
            "process_id": exchange.get("process_id"),
            "flow_identity": {
                "source_namespace": identity[0],
                "flow_uuid": identity[1],
                "version": identity[2],
            },
            "category": str(rule["category"]),
            "amount": float(amount),
            "unit": exchange.get("unit"),
            "direction": exchange.get("direction"),
            "factor_hash": factor_hash,
        })
    if not direct_inventory:
        required_emissions = sorted(
            "/".join(part) for part in emission_rules
        )
        observed_emissions = sorted(
            {
                f"{identity[0]}/{identity[1]}/{identity[2]}"
                for identity in (_identity(receipt) for receipt in receipt_by_exchange.values())
            }
        )
        _fail(
            "CARBON_DIRECT_EMISSION_REQUIRED",
            "the solved snapshot contains no direct emission matched by the method package",
            dependency_gap=dependency_gap(
                code="CARBON_DIRECT_EMISSION_REQUIRED",
                kind="direct_emission_exchange",
                step="carbon_management",
                what_missing={
                    "required_identity": {"flow_identities": required_emissions},
                    "observed_identity": {"flow_identities": observed_emissions},
                    "exchange_id_selectors": sorted(
                        str(rule.get("exchange_ids"))
                        for rule in emission_rules.values()
                        if rule.get("exchange_ids") is not None
                    ),
                },
                affects={
                    "downstream_steps": ["organization_ghg_inventory"],
                    "scopes_affected": ["scope_1"],
                },
                how_to_resolve=[
                    {
                        "action": "在该求解快照的模型里让边界内的直接排放端口产出生物圈交换，并重新冻结快照",
                        "owner": "建模与引擎求解",
                        "precondition": "端口的排放流身份与方法包 direct_emission_flows 一致",
                    },
                    {
                        "action": "若排放确属方法包漏报，发布新的方法包版本而不是在此处补数值",
                        "owner": "方法包作者",
                        "precondition": "新包带版本化的 direct_emission_flows 选择器",
                    },
                ],
                evidence={
                    "solved_snapshot_id": solved_snapshot_id,
                    "solved_snapshot_sha256": solved_snapshot_sha256,
                    "method_package_ref": method_package_ref,
                    "content_sha256": method_package_sha256,
                    "reporting_period_id": reporting_period.get("id"),
                },
            ),
        )

    climate_total, climate_issues = _climate_total(lcia_results, formula)
    if climate_total is not None and str(lcia_results.get("database_release") or "").strip() != str(provider_receipt.get("database_release") or "").strip():
        _fail("CARBON_DATABASE_RELEASE_MISMATCH", "LCIA result and provider receipt bind different database releases")
    limitations = manifest.get("validation_rules", {}).get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) or not item.strip() for item in limitations):
        _fail("CARBON_METHOD_PACKAGE_INVALID", "validation_rules.limitations must be a list of statements")
    carbon_attribution, contribution_issues, contribution_checks = _contribution_attribution(
        lcia_results=lcia_results,
        climate_total=climate_total,
        scaled_elementary_exchanges=scaled_elementary_exchanges,
        elementary_receipts=receipt_by_exchange,
        emission_rules=emission_rules,
    )
    issues = energy_issues + climate_issues + contribution_issues
    result: dict[str, Any] = {
        "schema_version": "nebula_one.carbon.management.v1",
        "capability_key": "carbon.management.v1",
        "method_package": {
            "reference": method_package_ref,
            "content_sha256": method_package_sha256,
        },
        "source_snapshot": {
            "id": solved_snapshot_id,
            "content_sha256": solved_snapshot_sha256,
        },
        "reporting_period": reporting_period,
        "energy_result": {
            "id": energy_result_id,
            "content_sha256": energy_result_sha256,
            "series": energy_series,
        },
        "direct_emission_inventory": direct_inventory,
        "climate_change_total": climate_total,
        "carbon_attribution": carbon_attribution,
        "audit": {
            "status": "passed_with_warnings",
            "checks": {
                "snapshot_content_pinned": True,
                "energy_result_same_snapshot": True,
                "reporting_period_pinned": True,
                "method_package_content_pinned": True,
                "direct_emission_receipts_present": True,
                "unit_series_not_merged": True,
                **contribution_checks,
            },
            "issues": issues,
            "limitations": limitations,
        },
    }
    result["content_sha256"] = canonical_json_sha256(result)
    return result
