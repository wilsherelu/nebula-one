from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SCHEMA_VERSION = "nebula_one.cbam.trial.v1"
CAPABILITY_KEY = "cbam.trial.v1"
PACKAGE_KIND = "cbam_trial"


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _decimal(value: Any, *, field: str, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(
            code="CBAM_TRIAL_NUMBER_INVALID",
            message="CBAM trial input must be numeric",
            status_code=422,
            details={"field": field},
        ) from exc
    if not parsed.is_finite() or (parsed < 0 if allow_zero else parsed <= 0):
        _fail(
            "CBAM_TRIAL_NUMBER_INVALID",
            "CBAM trial input is outside its allowed range",
            field=field,
        )
    return parsed


def _verified_hash(payload: dict[str, Any], *, code: str, subject: str) -> str:
    basis = dict(payload)
    expected = str(basis.pop("content_sha256", "")).strip()
    if not expected or canonical_json_sha256(basis) != expected:
        _fail(code, f"{subject} content hash does not match")
    return expected


def _exact_identity_matches(receipt: dict[str, Any], rule: dict[str, Any]) -> bool:
    return all(
        receipt.get(field) == rule.get(field)
        for field in (
            "source_namespace",
            "flow_uuid",
            "version",
            "flow_property_uuid",
            "flow_property_version",
            "unit_group_uuid",
            "unit_group_version",
            "unit",
        )
    )


def _calendar_year(period: dict[str, Any]) -> int:
    try:
        start = date.fromisoformat(str(period["start_date"]))
        end = date.fromisoformat(str(period["end_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError(
            code="CBAM_TRIAL_REPORTING_PERIOD_INVALID",
            message="CBAM trial requires an exact calendar-year reporting period",
            status_code=422,
        ) from exc
    if (
        start.year != end.year
        or start != date(start.year, 1, 1)
        or end != date(end.year, 12, 31)
        or period.get("resolution") != "year"
    ):
        _fail(
            "CBAM_TRIAL_REPORTING_PERIOD_INVALID",
            "CBAM trial requires a complete calendar-year reporting period",
        )
    return start.year


def build_cbam_trial(
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
) -> dict[str, Any]:
    if method_package_kind != PACKAGE_KIND:
        _fail(
            "CBAM_TRIAL_METHOD_KIND_MISMATCH",
            "cbam.trial.v1 requires a cbam_trial method package",
        )
    if method_package_jurisdiction != "EU":
        _fail(
            "CBAM_TRIAL_JURISDICTION_MISMATCH",
            "cbam.trial.v1 currently accepts an EU method package only",
        )
    if (manifest.get("output_schema") or {}).get("schema_version") != SCHEMA_VERSION:
        _fail(
            "CBAM_TRIAL_OUTPUT_SCHEMA_MISMATCH",
            "method package does not target cbam.trial.v1",
        )

    year = _calendar_year(reporting_period)
    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    if year < 2026:
        _fail(
            "CBAM_TRIAL_RULE_PERIOD_UNSUPPORTED",
            "the definitive-period trial does not accept a reporting period before 2026",
        )
    if method_package_valid_from and period_start < method_package_valid_from:
        _fail(
            "CBAM_TRIAL_METHOD_NOT_EFFECTIVE",
            "method package is not effective at the start of the reporting period",
        )
    if method_package_valid_to and period_end > method_package_valid_to:
        _fail(
            "CBAM_TRIAL_METHOD_NOT_EFFECTIVE",
            "method package expires before the reporting period ends",
        )

    rule_source = manifest.get("provenance", {}).get("rule_source")
    if not isinstance(rule_source, dict):
        _fail("CBAM_TRIAL_RULE_SOURCE_REQUIRED", "CBAM trial requires a rule source")
    rule_source_hash = _verified_hash(
        rule_source,
        code="CBAM_TRIAL_RULE_SOURCE_HASH_MISMATCH",
        subject="CBAM rule source",
    )

    formula = manifest.get("formula_graph")
    if not isinstance(formula, dict) or formula.get("calculation") != (
        "actual_specific_embedded_emissions_simple_goods_direct_only"
    ):
        _fail(
            "CBAM_TRIAL_FORMULA_UNSUPPORTED",
            "CBAM trial supports the direct-only simple-goods formula only",
        )
    if formula.get("activity_unit") != "t product" or formula.get(
        "result_unit"
    ) != "t CO2e/t product":
        _fail(
            "CBAM_TRIAL_UNIT_CONTRACT_INVALID",
            "CBAM trial formula units are unsupported",
        )
    if formula.get("rounding") != "ROUND_HALF_EVEN" or formula.get(
        "result_decimal_places"
    ) != 12:
        _fail(
            "CBAM_TRIAL_ROUNDING_UNSUPPORTED",
            "CBAM trial requires the declared v1 rounding contract",
        )

    boundary = manifest.get("boundary_schema")
    if (
        not isinstance(boundary, dict)
        or boundary.get("annex_ii_direct_only") is not True
        or boundary.get("goods_complexity") != "simple"
    ):
        _fail(
            "CBAM_TRIAL_BOUNDARY_UNSUPPORTED",
            "CBAM trial requires an explicit Annex II direct-only boundary",
        )
    if boundary.get("greenhouse_gases") != ["CO2"]:
        _fail(
            "CBAM_TRIAL_GAS_SCOPE_UNSUPPORTED",
            "CBAM trial currently supports direct CO2 only",
        )
    default_rules = manifest.get("default_value_rules")
    if not isinstance(default_rules, dict) or default_rules.get("allowed") is not False:
        _fail(
            "CBAM_TRIAL_DEFAULT_VALUES_UNSUPPORTED",
            "the v1 CBAM trial accepts actual solved values only",
        )

    rules = manifest.get("classification_rules")
    product_rule = rules.get("product") if isinstance(rules, dict) else None
    emission_rules = rules.get("direct_emissions") if isinstance(rules, dict) else None
    if not isinstance(product_rule, dict) or not isinstance(emission_rules, list):
        _fail(
            "CBAM_TRIAL_CLASSIFICATION_INVALID",
            "CBAM trial requires exact product and direct-emission rules",
        )
    required_identity = (
        "source_namespace",
        "flow_uuid",
        "version",
        "flow_property_uuid",
        "flow_property_version",
        "unit_group_uuid",
        "unit_group_version",
        "unit",
    )
    required_product = (*required_identity, "process_uuid", "reference_exchange_id")
    if any(not str(product_rule.get(field) or "").strip() for field in required_product):
        _fail(
            "CBAM_TRIAL_PRODUCT_RULE_INVALID",
            "CBAM trial product rule lacks exact identity",
        )
    if product_rule.get("unit") != "kg":
        _fail(
            "CBAM_TRIAL_PRODUCT_UNIT_UNSUPPORTED",
            "CBAM trial currently requires a kg product activity",
        )

    process_id = product_rule["process_uuid"]
    activity_matches = [
        item for item in activity_vector if item.get("process_id") == process_id
    ]
    if len(activity_matches) != 1:
        _fail(
            "CBAM_TRIAL_ACTIVITY_NOT_UNIQUE",
            "the product Process must resolve once in the activity vector",
            match_count=len(activity_matches),
        )
    activity = activity_matches[0]
    if activity.get("unit") != "kg":
        _fail(
            "CBAM_TRIAL_ACTIVITY_UNIT_MISMATCH",
            "the product Process activity must use kg",
        )
    activity_kg = _decimal(activity.get("value"), field="activity_vector.value")

    product_exchange_id = product_rule["reference_exchange_id"]
    product_exchanges = [
        item
        for item in scaled_technosphere_exchanges
        if item.get("exchange_id") == product_exchange_id
        and item.get("process_id") == process_id
        and item.get("flow_uuid") == product_rule["flow_uuid"]
        and item.get("direction") == "output"
    ]
    if len(product_exchanges) != 1:
        _fail(
            "CBAM_TRIAL_PRODUCT_EXCHANGE_NOT_UNIQUE",
            "the reference product exchange must resolve once",
            match_count=len(product_exchanges),
        )
    product_exchange = product_exchanges[0]
    if product_exchange.get("unit") != "kg":
        _fail(
            "CBAM_TRIAL_PRODUCT_UNIT_UNSUPPORTED",
            "the reference product exchange must use kg",
        )
    product_kg = _decimal(
        product_exchange.get("amount"), field="scaled_product_exchange.amount"
    )
    if product_kg != activity_kg:
        _fail(
            "CBAM_TRIAL_ACTIVITY_PRODUCT_MISMATCH",
            "Process activity and scaled reference-product output differ",
            activity_kg=str(activity_kg),
            product_kg=str(product_kg),
        )

    technosphere_receipts = provider_receipt.get("technosphere_flow_receipts") or []
    product_receipts = [
        item
        for item in technosphere_receipts
        if item.get("exchange_id") == product_exchange_id
        and item.get("process_uuid") == process_id
        and item.get("resolution") == "tidas_exact_snapshot"
        and _exact_identity_matches(item, product_rule)
    ]
    if len(product_receipts) != 1 or not product_receipts[0].get("content_hash"):
        _fail(
            "CBAM_TRIAL_PRODUCT_RECEIPT_REQUIRED",
            "the product requires one exact TIDAS provider receipt",
        )

    if not emission_rules:
        _fail(
            "CBAM_TRIAL_DIRECT_EMISSION_RULE_REQUIRED",
            "CBAM trial requires at least one direct-emission rule",
        )
    elementary_receipts = provider_receipt.get("elementary_flow_receipts") or []
    direct_rows: list[dict[str, Any]] = []
    seen_exchange_ids: set[str] = set()
    direct_kg = Decimal("0")
    for rule in emission_rules:
        if not isinstance(rule, dict) or any(
            not str(rule.get(field) or "").strip()
            for field in (*required_identity, "exchange_id", "process_uuid")
        ):
            _fail(
                "CBAM_TRIAL_DIRECT_EMISSION_RULE_INVALID",
                "a direct-emission rule lacks exact identity",
            )
        exchange_id = rule["exchange_id"]
        if exchange_id in seen_exchange_ids or rule["process_uuid"] != process_id:
            _fail(
                "CBAM_TRIAL_DIRECT_EMISSION_RULE_INVALID",
                "direct-emission rules must be unique and belong to the product Process",
            )
        seen_exchange_ids.add(exchange_id)
        if rule.get("unit") != "kg" or rule.get("greenhouse_gas") != "CO2":
            _fail(
                "CBAM_TRIAL_DIRECT_EMISSION_RULE_INVALID",
                "CBAM trial direct-emission rules must represent CO2 in kg",
            )
        exchanges = [
            item
            for item in scaled_elementary_exchanges
            if item.get("exchange_id") == exchange_id
            and item.get("process_id") == process_id
            and item.get("flow_uuid") == rule["flow_uuid"]
            and item.get("direction") == "output"
        ]
        receipts = [
            item
            for item in elementary_receipts
            if item.get("exchange_id") == exchange_id
            and _exact_identity_matches(item, rule)
        ]
        if len(exchanges) != 1 or len(receipts) != 1:
            _fail(
                "CBAM_TRIAL_DIRECT_EMISSION_RECEIPT_REQUIRED",
                "each direct emission requires one solved exchange and exact provider receipt",
                exchange_id=exchange_id,
            )
        receipt = receipts[0]
        if not receipt.get("content_hash") or not receipt.get("snapshot_hash"):
            _fail(
                "CBAM_TRIAL_DIRECT_EMISSION_RECEIPT_REQUIRED",
                "direct-emission provider receipt lacks immutable identity",
                exchange_id=exchange_id,
            )
        amount = _decimal(
            exchanges[0].get("amount"),
            field=f"scaled_elementary_exchanges.{exchange_id}.amount",
            allow_zero=True,
        )
        direct_kg += amount
        direct_rows.append(
            {
                "exchange_id": exchange_id,
                "process_uuid": process_id,
                "flow_identity": {
                    field: rule[field] for field in required_identity
                },
                "greenhouse_gas": "CO2",
                "amount": str(amount),
                "unit": "kg CO2e",
                "provider_receipt": {
                    "content_hash": receipt["content_hash"],
                    "snapshot_hash": receipt["snapshot_hash"],
                },
            }
        )

    production_tonnes = activity_kg / Decimal("1000")
    direct_tonnes = direct_kg / Decimal("1000")
    specific = (direct_tonnes / production_tonnes).quantize(
        Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
    )
    limitations = (manifest.get("validation_rules") or {}).get("limitations")
    if not isinstance(limitations, list) or not limitations:
        _fail(
            "CBAM_TRIAL_LIMITATIONS_REQUIRED",
            "CBAM trial method package must declare limitations",
        )
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
                field: product_rule[field] for field in required_identity
            },
            "production_process_uuid": process_id,
            "reference_exchange_id": product_exchange_id,
        },
        "activity_level": {
            "value": str(production_tonnes),
            "unit": "t product",
            "source_value": str(activity_kg),
            "source_unit": "kg",
        },
        "attributed_emissions": {
            "direct": {
                "value": str(direct_tonnes),
                "unit": "t CO2e",
                "source_value": str(direct_kg),
                "source_unit": "kg CO2e",
                "exchanges": direct_rows,
            },
            "indirect": None,
            "precursors": [],
        },
        "specific_embedded_emissions": {
            "value": str(specific),
            "unit": "t CO2e/t product",
            "formula": "attributed_direct_emissions_t_CO2e / activity_level_t_product",
        },
        "status": "trial_passed",
        "audit": {
            "status": "trial_passed",
            "checks": {
                "method_package_content_pinned": True,
                "rule_source_hash_valid": True,
                "calendar_year_2026_or_later": True,
                "annex_ii_direct_only_boundary_declared": True,
                "exact_tidas_product_receipt_present": True,
                "exact_elementary_flow_receipts_present": True,
                "activity_matches_scaled_reference_product": True,
                "no_default_values_used": True,
                "no_lcia_factor_recalculation": True,
            },
            "limitations": limitations,
        },
        "claim_boundary": {
            "trial_only": True,
            "not_a_cbam_declaration": True,
            "not_verified_embedded_emissions": True,
            "certificate_liability_not_calculated": True,
            "carbon_price_deduction_not_calculated": True,
            "free_allocation_adjustment_not_calculated": True,
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
