from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from ..hashing import canonical_json_sha256
from .cbam_trial import (
    _calendar_year,
    _decimal,
    _exact_identity_matches,
    _fail,
    _verified_hash,
)


SCHEMA_VERSION = "nebula_one.cbam.complex-trial.v1"
CAPABILITY_KEY = "cbam.complex-trial.v1"
PACKAGE_KIND = "cbam_complex_trial"
IDENTITY_FIELDS = (
    "source_namespace",
    "flow_uuid",
    "version",
    "flow_property_uuid",
    "flow_property_version",
    "unit_group_uuid",
    "unit_group_version",
    "unit",
)


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _validate_period_and_method(
    *,
    reporting_period: dict[str, Any],
    method_package_kind: str,
    method_package_jurisdiction: str | None,
    method_package_valid_from: date | None,
    method_package_valid_to: date | None,
    manifest: dict[str, Any],
) -> tuple[int, str]:
    if method_package_kind != PACKAGE_KIND:
        _fail(
            "CBAM_COMPLEX_METHOD_KIND_MISMATCH",
            "cbam.complex-trial.v1 requires a cbam_complex_trial method package",
        )
    if method_package_jurisdiction != "EU":
        _fail(
            "CBAM_COMPLEX_JURISDICTION_MISMATCH",
            "cbam.complex-trial.v1 currently accepts an EU method package only",
        )
    if (manifest.get("output_schema") or {}).get("schema_version") != SCHEMA_VERSION:
        _fail(
            "CBAM_COMPLEX_OUTPUT_SCHEMA_MISMATCH",
            "method package does not target cbam.complex-trial.v1",
        )

    year = _calendar_year(reporting_period)
    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    if year < 2026:
        _fail(
            "CBAM_COMPLEX_RULE_PERIOD_UNSUPPORTED",
            "the definitive-period trial does not accept a reporting period before 2026",
        )
    if method_package_valid_from and period_start < method_package_valid_from:
        _fail(
            "CBAM_COMPLEX_METHOD_NOT_EFFECTIVE",
            "method package is not effective at the start of the reporting period",
        )
    if method_package_valid_to and period_end > method_package_valid_to:
        _fail(
            "CBAM_COMPLEX_METHOD_NOT_EFFECTIVE",
            "method package expires before the reporting period ends",
        )

    rule_source = manifest.get("provenance", {}).get("rule_source")
    if not isinstance(rule_source, dict):
        _fail(
            "CBAM_COMPLEX_RULE_SOURCE_REQUIRED",
            "CBAM complex-goods trial requires a rule source",
        )
    return year, _verified_hash(
        rule_source,
        code="CBAM_COMPLEX_RULE_SOURCE_HASH_MISMATCH",
        subject="CBAM complex-goods rule source",
    )


def _validate_formula(manifest: dict[str, Any]) -> None:
    formula = manifest.get("formula_graph")
    if not isinstance(formula, dict) or formula.get("calculation") != (
        "actual_specific_embedded_emissions_complex_goods_direct_component"
    ):
        _fail(
            "CBAM_COMPLEX_FORMULA_UNSUPPORTED",
            "CBAM complex-goods trial supports the one-level direct-component formula only",
        )
    if (
        formula.get("activity_unit") != "t product"
        or formula.get("precursor_unit") != "t precursor"
        or formula.get("result_unit") != "t CO2e/t product"
    ):
        _fail(
            "CBAM_COMPLEX_UNIT_CONTRACT_INVALID",
            "CBAM complex-goods formula units are unsupported",
        )
    if (
        formula.get("rounding") != "ROUND_HALF_EVEN"
        or formula.get("result_decimal_places") != 12
    ):
        _fail(
            "CBAM_COMPLEX_ROUNDING_UNSUPPORTED",
            "CBAM complex-goods trial requires the declared v1 rounding contract",
        )

    boundary = manifest.get("boundary_schema")
    if (
        not isinstance(boundary, dict)
        or boundary.get("goods_complexity") != "complex"
        or boundary.get("emissions_component") != "direct"
        or boundary.get("indirect_emissions") != "not_calculated"
        or boundary.get("greenhouse_gases") != ["CO2"]
    ):
        _fail(
            "CBAM_COMPLEX_BOUNDARY_UNSUPPORTED",
            "the v1 complex-goods trial requires an explicit direct-component-only boundary",
        )
    default_rules = manifest.get("default_value_rules")
    if not isinstance(default_rules, dict) or default_rules.get("allowed") is not False:
        _fail(
            "CBAM_COMPLEX_DEFAULT_VALUES_UNSUPPORTED",
            "the v1 complex-goods trial accepts solved precursor values only",
        )


def _required_identity(rule: dict[str, Any], *, code: str) -> None:
    if any(not str(rule.get(field) or "").strip() for field in IDENTITY_FIELDS):
        _fail(code, "CBAM complex-goods rule lacks exact Flow identity")
    if rule.get("unit") != "kg":
        _fail(code, "CBAM complex-goods trial currently requires kg Flow identities")


def _resolve_product(
    *,
    product_rule: dict[str, Any],
    activity_vector: list[dict[str, Any]],
    scaled_technosphere_exchanges: list[dict[str, Any]],
    provider_receipt: dict[str, Any],
) -> tuple[Decimal, dict[str, Any]]:
    _required_identity(product_rule, code="CBAM_COMPLEX_PRODUCT_RULE_INVALID")
    process_id = str(product_rule.get("process_uuid") or "").strip()
    exchange_id = str(product_rule.get("reference_exchange_id") or "").strip()
    if not process_id or not exchange_id:
        _fail(
            "CBAM_COMPLEX_PRODUCT_RULE_INVALID",
            "CBAM complex-goods product rule lacks Process or exchange identity",
        )

    activities = [
        row for row in activity_vector if row.get("process_id") == process_id
    ]
    if len(activities) != 1 or activities[0].get("unit") != "kg":
        _fail(
            "CBAM_COMPLEX_ACTIVITY_NOT_UNIQUE",
            "the complex-goods Process must resolve once in kg",
            match_count=len(activities),
        )
    activity_kg = _decimal(activities[0].get("value"), field="activity_vector.value")
    products = [
        row
        for row in scaled_technosphere_exchanges
        if row.get("exchange_id") == exchange_id
        and row.get("process_id") == process_id
        and row.get("flow_uuid") == product_rule["flow_uuid"]
        and row.get("direction") == "output"
    ]
    if len(products) != 1 or products[0].get("unit") != "kg":
        _fail(
            "CBAM_COMPLEX_PRODUCT_EXCHANGE_NOT_UNIQUE",
            "the complex-goods reference product must resolve once in kg",
            match_count=len(products),
        )
    product_kg = _decimal(products[0].get("amount"), field="product.amount")
    if activity_kg != product_kg:
        _fail(
            "CBAM_COMPLEX_ACTIVITY_PRODUCT_MISMATCH",
            "Process activity and scaled complex-goods output differ",
            activity_kg=str(activity_kg),
            product_kg=str(product_kg),
        )

    receipts = [
        row
        for row in provider_receipt.get("technosphere_flow_receipts") or []
        if row.get("exchange_id") == exchange_id
        and row.get("process_uuid") == process_id
        and row.get("resolution") == "tidas_exact_snapshot"
        and _exact_identity_matches(row, product_rule)
    ]
    if len(receipts) != 1 or not receipts[0].get("content_hash"):
        _fail(
            "CBAM_COMPLEX_PRODUCT_RECEIPT_REQUIRED",
            "the complex good requires one exact TIDAS provider receipt",
        )
    return activity_kg, receipts[0]


def _resolve_direct_emissions(
    *,
    process_id: str,
    rules: list[dict[str, Any]],
    scaled_elementary_exchanges: list[dict[str, Any]],
    provider_receipt: dict[str, Any],
) -> tuple[Decimal, list[dict[str, Any]]]:
    if not rules:
        _fail(
            "CBAM_COMPLEX_DIRECT_EMISSION_RULE_REQUIRED",
            "the complex-goods method requires at least one direct CO2 rule",
        )
    receipt_rows = provider_receipt.get("elementary_flow_receipts") or []
    total_kg = Decimal("0")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in rules:
        _required_identity(rule, code="CBAM_COMPLEX_DIRECT_EMISSION_RULE_INVALID")
        exchange_id = str(rule.get("exchange_id") or "").strip()
        if (
            not exchange_id
            or exchange_id in seen
            or rule.get("process_uuid") != process_id
            or rule.get("greenhouse_gas") != "CO2"
        ):
            _fail(
                "CBAM_COMPLEX_DIRECT_EMISSION_RULE_INVALID",
                "direct-emission rules must be unique CO2 exchanges on the product Process",
            )
        seen.add(exchange_id)
        exchanges = [
            row
            for row in scaled_elementary_exchanges
            if row.get("exchange_id") == exchange_id
            and row.get("process_id") == process_id
            and row.get("flow_uuid") == rule["flow_uuid"]
            and row.get("direction") == "output"
            and row.get("unit") == "kg"
        ]
        receipts = [
            row
            for row in receipt_rows
            if row.get("exchange_id") == exchange_id
            and _exact_identity_matches(row, rule)
        ]
        if len(exchanges) != 1 or len(receipts) != 1:
            _fail(
                "CBAM_COMPLEX_DIRECT_EMISSION_RECEIPT_REQUIRED",
                "each direct emission requires one solved exchange and exact provider receipt",
                exchange_id=exchange_id,
            )
        receipt = receipts[0]
        if not receipt.get("content_hash") or not receipt.get("snapshot_hash"):
            _fail(
                "CBAM_COMPLEX_DIRECT_EMISSION_RECEIPT_REQUIRED",
                "direct-emission receipt lacks immutable identity",
                exchange_id=exchange_id,
            )
        amount = _decimal(
            exchanges[0].get("amount"),
            field=f"scaled_elementary_exchanges.{exchange_id}.amount",
            allow_zero=True,
        )
        total_kg += amount
        rows.append(
            {
                "exchange_id": exchange_id,
                "flow_identity": {field: rule[field] for field in IDENTITY_FIELDS},
                "amount": str(amount),
                "unit": "kg CO2e",
                "provider_receipt": {
                    "content_hash": receipt["content_hash"],
                    "snapshot_hash": receipt["snapshot_hash"],
                },
            }
        )
    return total_kg, rows


def _verify_precursor_result(
    result: dict[str, Any],
    *,
    rule: dict[str, Any],
    reporting_period: dict[str, Any],
) -> Decimal:
    if result.get("schema_version") != "nebula_one.cbam.trial.v1":
        _fail(
            "CBAM_COMPLEX_PRECURSOR_RESULT_UNSUPPORTED",
            "v1 accepts a solved simple-goods CBAM trial result as precursor evidence",
        )
    basis = {key: value for key, value in result.items() if key != "content_sha256"}
    if canonical_json_sha256(basis) != result.get("content_sha256"):
        _fail(
            "CBAM_COMPLEX_PRECURSOR_RESULT_HASH_MISMATCH",
            "precursor CBAM result content hash does not match",
        )
    if result.get("status") != "trial_passed":
        _fail(
            "CBAM_COMPLEX_PRECURSOR_RESULT_NOT_PASSED",
            "precursor CBAM result did not pass its own audit",
        )
    if (result.get("method_package") or {}).get("ref") != rule.get(
        "method_package_ref"
    ):
        _fail(
            "CBAM_COMPLEX_PRECURSOR_METHOD_MISMATCH",
            "precursor result uses a different method package",
        )
    product_flow = (result.get("goods") or {}).get("product_flow") or {}
    if not _exact_identity_matches(product_flow, rule):
        _fail(
            "CBAM_COMPLEX_PRECURSOR_IDENTITY_MISMATCH",
            "precursor result product Flow does not match the exact precursor rule",
        )
    if (result.get("goods") or {}).get("production_process_uuid") != rule.get(
        "source_process_uuid"
    ):
        _fail(
            "CBAM_COMPLEX_PRECURSOR_PROCESS_MISMATCH",
            "precursor result Process does not match the declared source Process",
        )
    precursor_period = result.get("reporting_period") or {}
    for field in ("start_date", "end_date", "resolution"):
        if precursor_period.get(field) != reporting_period.get(field):
            _fail(
                "CBAM_COMPLEX_PRECURSOR_PERIOD_MISMATCH",
                "precursor and complex good must use the same reporting period",
                field=field,
            )
    specific = result.get("specific_embedded_emissions") or {}
    if specific.get("unit") != "t CO2e/t product":
        _fail(
            "CBAM_COMPLEX_PRECURSOR_UNIT_MISMATCH",
            "precursor specific embedded emissions use an unsupported unit",
        )
    return _decimal(specific.get("value"), field="precursor.specific_emissions")


def _resolve_precursors(
    *,
    rules: list[dict[str, Any]],
    precursor_results: list[dict[str, Any]],
    product_process_id: str,
    product_tonnes: Decimal,
    reporting_period: dict[str, Any],
    scaled_technosphere_exchanges: list[dict[str, Any]],
    provider_receipt: dict[str, Any],
) -> tuple[Decimal, list[dict[str, Any]]]:
    if len(rules) != 1:
        _fail(
            "CBAM_COMPLEX_PRECURSOR_RULE_REQUIRED",
            "the v1 gold-standard contract requires exactly one exact precursor rule",
        )
    if len(precursor_results) != len(rules):
        _fail(
            "CBAM_COMPLEX_PRECURSOR_RESULT_COUNT_MISMATCH",
            "each precursor rule requires exactly one solved precursor result",
        )
    by_method: dict[str, dict[str, Any]] = {}
    for result in precursor_results:
        method_ref = str((result.get("method_package") or {}).get("ref") or "")
        if not method_ref or method_ref in by_method:
            _fail(
                "CBAM_COMPLEX_PRECURSOR_RESULT_DUPLICATE",
                "precursor results must use unique method-package references",
            )
        by_method[method_ref] = result

    receipts = provider_receipt.get("technosphere_flow_receipts") or []
    total_tonnes = Decimal("0")
    rows: list[dict[str, Any]] = []
    seen_exchanges: set[str] = set()
    for rule in rules:
        _required_identity(rule, code="CBAM_COMPLEX_PRECURSOR_RULE_INVALID")
        exchange_id = str(rule.get("exchange_id") or "").strip()
        method_ref = str(rule.get("method_package_ref") or "").strip()
        source_process_id = str(rule.get("source_process_uuid") or "").strip()
        if (
            not exchange_id
            or exchange_id in seen_exchanges
            or not method_ref
            or not source_process_id
        ):
            _fail(
                "CBAM_COMPLEX_PRECURSOR_RULE_INVALID",
                "precursor rule lacks unique exchange, Process or method identity",
            )
        seen_exchanges.add(exchange_id)
        exchanges = [
            row
            for row in scaled_technosphere_exchanges
            if row.get("exchange_id") == exchange_id
            and row.get("process_id") == product_process_id
            and row.get("flow_uuid") == rule["flow_uuid"]
            and row.get("direction") == "input"
            and row.get("unit") == "kg"
        ]
        flow_receipts = [
            row
            for row in receipts
            if row.get("exchange_id") == exchange_id
            and row.get("process_uuid") == product_process_id
            and row.get("resolution") == "tidas_exact_snapshot"
            and _exact_identity_matches(row, rule)
        ]
        if len(exchanges) != 1 or len(flow_receipts) != 1:
            _fail(
                "CBAM_COMPLEX_PRECURSOR_RECEIPT_REQUIRED",
                "each precursor requires one solved input and exact TIDAS receipt",
                exchange_id=exchange_id,
            )
        receipt = flow_receipts[0]
        if not receipt.get("content_hash"):
            _fail(
                "CBAM_COMPLEX_PRECURSOR_RECEIPT_REQUIRED",
                "precursor provider receipt lacks immutable identity",
                exchange_id=exchange_id,
            )
        result = by_method.get(method_ref)
        if result is None:
            _fail(
                "CBAM_COMPLEX_PRECURSOR_RESULT_REQUIRED",
                "the declared precursor method has no solved result",
                method_package_ref=method_ref,
            )
        specific = _verify_precursor_result(
            result,
            rule=rule,
            reporting_period=reporting_period,
        )
        mass_kg = _decimal(exchanges[0].get("amount"), field="precursor.amount")
        mass_tonnes = mass_kg / Decimal("1000")
        embedded_tonnes = mass_tonnes * specific
        total_tonnes += embedded_tonnes
        rows.append(
            {
                "exchange_id": exchange_id,
                "source_process_uuid": source_process_id,
                "flow_identity": {field: rule[field] for field in IDENTITY_FIELDS},
                "method_package_ref": method_ref,
                "result_content_sha256": result["content_sha256"],
                "mass": {
                    "value": _plain(mass_tonnes),
                    "unit": "t precursor",
                    "source_value": str(mass_kg),
                    "source_unit": "kg",
                },
                "specific_mass_consumption": {
                    "value": _plain(mass_tonnes / product_tonnes),
                    "unit": "t precursor/t product",
                },
                "specific_embedded_emissions": {
                    "value": str(specific),
                    "unit": "t CO2e/t precursor",
                },
                "embedded_emissions": {
                    "value": _plain(embedded_tonnes),
                    "unit": "t CO2e",
                },
                "provider_receipt": {"content_hash": receipt["content_hash"]},
            }
        )
    return total_tonnes, rows


def build_cbam_complex_trial(
    *,
    solved_snapshot_id: str,
    solved_snapshot_sha256: str,
    application_id: str,
    activity_vector: list[dict[str, Any]],
    scaled_technosphere_exchanges: list[dict[str, Any]],
    scaled_elementary_exchanges: list[dict[str, Any]],
    provider_receipt: dict[str, Any],
    reporting_period: dict[str, Any],
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    method_package_jurisdiction: str | None,
    method_package_valid_from: date | None,
    method_package_valid_to: date | None,
    manifest: dict[str, Any],
    precursor_results: list[dict[str, Any]],
) -> dict[str, Any]:
    _, rule_source_hash = _validate_period_and_method(
        reporting_period=reporting_period,
        method_package_kind=method_package_kind,
        method_package_jurisdiction=method_package_jurisdiction,
        method_package_valid_from=method_package_valid_from,
        method_package_valid_to=method_package_valid_to,
        manifest=manifest,
    )
    _validate_formula(manifest)
    rules = manifest.get("classification_rules")
    product_rule = rules.get("product") if isinstance(rules, dict) else None
    emission_rules = rules.get("direct_emissions") if isinstance(rules, dict) else None
    precursor_rules = rules.get("precursors") if isinstance(rules, dict) else None
    if (
        not isinstance(product_rule, dict)
        or not isinstance(emission_rules, list)
        or not isinstance(precursor_rules, list)
    ):
        _fail(
            "CBAM_COMPLEX_CLASSIFICATION_INVALID",
            "method package requires product, direct-emission and precursor rules",
        )

    activity_kg, product_receipt = _resolve_product(
        product_rule=product_rule,
        activity_vector=activity_vector,
        scaled_technosphere_exchanges=scaled_technosphere_exchanges,
        provider_receipt=provider_receipt,
    )
    process_id = product_rule["process_uuid"]
    direct_kg, direct_rows = _resolve_direct_emissions(
        process_id=process_id,
        rules=emission_rules,
        scaled_elementary_exchanges=scaled_elementary_exchanges,
        provider_receipt=provider_receipt,
    )
    product_tonnes = activity_kg / Decimal("1000")
    direct_tonnes = direct_kg / Decimal("1000")
    precursor_tonnes, precursor_rows = _resolve_precursors(
        rules=precursor_rules,
        precursor_results=precursor_results,
        product_process_id=process_id,
        product_tonnes=product_tonnes,
        reporting_period=reporting_period,
        scaled_technosphere_exchanges=scaled_technosphere_exchanges,
        provider_receipt=provider_receipt,
    )
    total_tonnes = direct_tonnes + precursor_tonnes
    specific = (total_tonnes / product_tonnes).quantize(
        Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
    )
    limitations = (manifest.get("validation_rules") or {}).get("limitations")
    if not isinstance(limitations, list) or not limitations:
        _fail(
            "CBAM_COMPLEX_LIMITATIONS_REQUIRED",
            "complex-goods method package must declare limitations",
        )

    boundary = manifest["boundary_schema"]
    content = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "method_package": {
            "ref": method_package_ref,
            "content_sha256": method_package_sha256,
            "jurisdiction": method_package_jurisdiction,
            "rule_source_sha256": rule_source_hash,
        },
        "source_snapshot": {
            "id": solved_snapshot_id,
            "content_sha256": solved_snapshot_sha256,
            "application_id": application_id,
        },
        "reporting_period": reporting_period,
        "goods": {
            "cn_code": boundary.get("cn_code"),
            "aggregated_goods_category": boundary.get(
                "aggregated_goods_category"
            ),
            "product_flow": {
                field: product_rule[field] for field in IDENTITY_FIELDS
            },
            "production_process_uuid": process_id,
            "reference_exchange_id": product_rule["reference_exchange_id"],
            "provider_receipt": {
                "content_hash": product_receipt["content_hash"]
            },
        },
        "activity_level": {
            "value": str(product_tonnes),
            "unit": "t product",
            "source_value": str(activity_kg),
            "source_unit": "kg",
        },
        "attributed_emissions": {
            "final_process_direct": {
                "value": str(direct_tonnes),
                "unit": "t CO2e",
                "source_value": str(direct_kg),
                "source_unit": "kg CO2e",
                "exchanges": direct_rows,
            },
            "precursor_embedded_direct": {
                "value": _plain(precursor_tonnes),
                "unit": "t CO2e",
            },
            "total_direct_component": {
                "value": _plain(total_tonnes),
                "unit": "t CO2e",
            },
            "indirect": None,
        },
        "precursors": precursor_rows,
        "specific_embedded_emissions": {
            "value": str(specific),
            "unit": "t CO2e/t product",
            "component": "direct",
            "formula": "ae_g + sum(m_i * SEE_i)",
            "regulatory_equation": "Equation 62",
        },
        "status": "trial_passed",
        "audit": {
            "status": "trial_passed",
            "checks": {
                "method_package_content_pinned": True,
                "rule_source_hash_valid": True,
                "calendar_year_2026_or_later": True,
                "complex_goods_boundary_declared": True,
                "exact_tidas_product_receipt_present": True,
                "exact_tidas_precursor_receipts_present": True,
                "exact_elementary_flow_receipts_present": True,
                "precursor_result_hashes_valid": True,
                "same_reporting_period": True,
                "no_default_values_used": True,
                "indirect_emissions_not_calculated": True,
            },
            "limitations": limitations,
        },
        "claim_boundary": {
            "trial_only": True,
            "direct_component_only": True,
            "not_total_embedded_emissions": True,
            "not_a_cbam_declaration": True,
            "not_verified_embedded_emissions": True,
            "certificate_liability_not_calculated": True,
            "carbon_price_deduction_not_calculated": True,
            "free_allocation_adjustment_not_calculated": True,
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
