from __future__ import annotations

import math
import re
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("PCF_CONTRIBUTION_RECEIPT_INVALID", f"{field} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        _fail("PCF_CONTRIBUTION_RECEIPT_INVALID", f"{field} must be a finite number")
    return parsed


def _same_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)


def _sha256(value: Any, *, field: str) -> str:
    parsed = str(value or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", parsed) is None:
        _fail("PCF_CONTRIBUTION_PROVENANCE_INVALID", f"{field} must be an exact SHA-256")
    return parsed


def _flow_identity(source: dict[str, Any], *, version_key: str) -> tuple[str, str, str]:
    return (
        str(source.get("source_namespace") or "").strip(),
        str(source.get("flow_uuid") or "").strip(),
        str(source.get(version_key) or "").strip(),
    )


def build_pcf_contribution_analysis(
    *,
    lcia_results: dict[str, Any],
    total_footprint: dict[str, Any],
    scaled_elementary_exchanges: list[dict[str, Any]],
    elementary_flow_receipts: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, bool]]:
    raw_receipts = lcia_results.get("indicator_contribution_receipts")
    if raw_receipts is None:
        return (
            {
                "status": "unavailable",
                "coverage": "total_only",
                "reason": "provider contribution receipts unavailable",
                "indicator_receipt": None,
                "hotspots": [],
            },
            {
                "contribution_receipts_present": False,
                "contribution_receipts_hash_valid": False,
                "contribution_total_reconciled": False,
                "contribution_terms_trace_to_scaled_exchanges": False,
            },
        )
    if not isinstance(raw_receipts, list):
        _fail("PCF_CONTRIBUTION_RECEIPTS_INVALID", "indicator contribution receipts must be a list")
    aggregate_hash = _sha256(
        lcia_results.get("contribution_receipts_hash"),
        field="contribution_receipts_hash",
    )
    if aggregate_hash != canonical_json_sha256(raw_receipts):
        _fail("PCF_CONTRIBUTION_RECEIPTS_HASH_MISMATCH", "provider contribution receipt collection hash is invalid")

    indicator_key = str(total_footprint.get("indicator_key") or "").strip()
    matches = [
        item
        for item in raw_receipts
        if isinstance(item, dict)
        and str(item.get("canonical_indicator_key") or "").strip() == indicator_key
    ]
    if len(matches) != 1:
        _fail(
            "PCF_CONTRIBUTION_RECEIPT_NOT_UNIQUE",
            "PCF requires exactly one contribution receipt for its total indicator",
            match_count=len(matches),
        )
    receipt = matches[0]
    receipt_hash = _sha256(receipt.get("content_hash"), field="contribution receipt content_hash")
    receipt_basis = dict(receipt)
    receipt_basis.pop("content_hash", None)
    if receipt_hash != canonical_json_sha256(receipt_basis):
        _fail("PCF_CONTRIBUTION_RECEIPT_HASH_MISMATCH", "PCF contribution receipt hash is invalid")

    method = str(lcia_results.get("method") or "").strip()
    release = str(lcia_results.get("database_release") or "").strip()
    unit = str(total_footprint.get("unit") or "").strip()
    total_value = _number(total_footprint.get("value"), field="total_footprint.value")
    receipt_value = _number(receipt.get("indicator_value"), field="indicator_value")
    contribution_total = _number(receipt.get("contribution_total"), field="contribution_total")
    reconciliation_delta = _number(receipt.get("reconciliation_delta"), field="reconciliation_delta")
    if (
        receipt.get("schema_version") != "provider.lcia.indicator-contribution-receipt.v1"
        or str(receipt.get("method") or "").strip() != method
        or str(receipt.get("database_release") or "").strip() != release
        or str(receipt.get("indicator_unit") or "").strip() != unit
        or not _same_number(receipt_value, total_value)
        or not _same_number(contribution_total, total_value)
        or not _same_number(reconciliation_delta, 0.0)
    ):
        _fail("PCF_CONTRIBUTION_RECEIPT_MISMATCH", "PCF contribution receipt does not reconcile with the frozen LCIA total")

    solve_hash = _sha256(lcia_results.get("solve_hash"), field="lcia solve_hash")
    runtime_assets_hash = _sha256(
        lcia_results.get("runtime_assets_hash"), field="lcia runtime_assets_hash"
    )
    if (
        str(receipt.get("solve_hash") or "").strip() != solve_hash
        or str(receipt.get("runtime_assets_hash") or "").strip() != runtime_assets_hash
        or receipt.get("provider_commit") != lcia_results.get("provider_commit")
    ):
        _fail("PCF_CONTRIBUTION_PROVENANCE_MISMATCH", "PCF contribution receipt conflicts with LCIA provenance")

    scaled_by_exchange: dict[str, dict[str, Any]] = {}
    for exchange in scaled_elementary_exchanges:
        exchange_id = str(exchange.get("exchange_id") or "").strip()
        if not exchange_id or exchange_id in scaled_by_exchange:
            _fail("PCF_CONTRIBUTION_EXCHANGE_AMBIGUOUS", "scaled elementary exchanges require unique exchange IDs")
        scaled_by_exchange[exchange_id] = exchange
    receipt_by_exchange: dict[str, dict[str, Any]] = {}
    for item in elementary_flow_receipts:
        exchange_id = str(item.get("exchange_id") or "").strip()
        if not exchange_id or exchange_id in receipt_by_exchange:
            _fail("PCF_CONTRIBUTION_FLOW_RECEIPT_AMBIGUOUS", "elementary Flow receipts require unique exchange IDs")
        receipt_by_exchange[exchange_id] = item

    terms = receipt.get("terms")
    if not isinstance(terms, list):
        _fail("PCF_CONTRIBUTION_RECEIPT_INVALID", "PCF contribution terms must be a list")
    term_ids: set[str] = set()
    hotspots: list[dict[str, Any]] = []
    supplied_total = 0.0
    for term in terms:
        if not isinstance(term, dict) or term.get("schema_version") != "provider.lcia.contribution-term.v1":
            _fail("PCF_CONTRIBUTION_TERM_INVALID", "a PCF contribution term has an unsupported schema")
        exchange_id = str(term.get("exchange_id") or "").strip()
        if not exchange_id or exchange_id in term_ids or exchange_id not in scaled_by_exchange:
            _fail("PCF_CONTRIBUTION_TERM_EXCHANGE_MISMATCH", "a PCF contribution term does not map to one scaled elementary exchange", exchange_id=exchange_id)
        term_ids.add(exchange_id)
        exchange = scaled_by_exchange[exchange_id]
        flow_receipt = receipt_by_exchange.get(exchange_id)
        if flow_receipt is None:
            _fail("PCF_CONTRIBUTION_FLOW_RECEIPT_MISSING", "a PCF contribution term lacks an elementary Flow receipt", exchange_id=exchange_id)

        identity = _flow_identity(term, version_key="flow_version")
        expected_identity = _flow_identity(flow_receipt, version_key="version")
        amount = _number(term.get("amount"), field="term.amount")
        expected_amount = _number(exchange.get("amount"), field="scaled exchange amount")
        contribution = _number(term.get("contribution_value"), field="term.contribution_value")
        if (
            identity != expected_identity
            or str(term.get("process_uuid") or "").strip() != str(exchange.get("process_id") or "").strip()
            or str(term.get("amount_unit") or "").strip() != str(exchange.get("unit") or "").strip()
            or str(term.get("direction") or "").strip() != str(exchange.get("direction") or "").strip()
            or str(term.get("contribution_unit") or "").strip() != unit
            or str(term.get("cf_method") or "").strip() != method
            or str(term.get("cf_database_release") or "").strip() != release
            or str(term.get("cf_indicator_key") or "").strip() != indicator_key
            or str(term.get("cf_runtime_assets_hash") or "").strip() != runtime_assets_hash
            or str(term.get("solve_hash") or "").strip() != solve_hash
            or not _same_number(amount, expected_amount)
        ):
            _fail("PCF_CONTRIBUTION_TERM_MISMATCH", "a PCF contribution term conflicts with frozen exchange or LCIA evidence", exchange_id=exchange_id)
        cf_hash = _sha256(term.get("cf_hash"), field="term.cf_hash")
        supplied_total += contribution
        hotspots.append(
            {
                "rank": 0,
                "process_id": str(term.get("process_uuid") or ""),
                "exchange_id": exchange_id,
                "flow_identity": {
                    "source_namespace": identity[0],
                    "flow_uuid": identity[1],
                    "version": identity[2],
                },
                "amount": amount,
                "amount_unit": str(term.get("amount_unit") or ""),
                "contribution_value": contribution,
                "contribution_unit": unit,
                "share_of_total": None if _same_number(total_value, 0.0) else contribution / total_value,
                "cf_hash": cf_hash,
            }
        )
    if term_ids != set(scaled_by_exchange):
        _fail("PCF_CONTRIBUTION_TERM_COVERAGE_MISMATCH", "PCF contribution terms do not cover every scaled elementary exchange")
    if not _same_number(supplied_total, contribution_total):
        _fail("PCF_CONTRIBUTION_TERM_TOTAL_MISMATCH", "PCF contribution terms do not reconcile with the provider total")

    hotspots.sort(key=lambda item: (-abs(float(item["contribution_value"])), item["exchange_id"]))
    for rank, item in enumerate(hotspots, start=1):
        item["rank"] = rank
    return (
        {
            "status": "available",
            "coverage": "exact_exchange_contributions",
            "reason": None,
            "indicator_receipt": {
                "content_hash": receipt_hash,
                "contribution_receipts_hash": aggregate_hash,
                "solve_hash": solve_hash,
                "provider_commit": receipt.get("provider_commit"),
                "runtime_assets_hash": runtime_assets_hash,
                "term_count": len(hotspots),
            },
            "hotspots": hotspots,
        },
        {
            "contribution_receipts_present": True,
            "contribution_receipts_hash_valid": True,
            "contribution_total_reconciled": True,
            "contribution_terms_trace_to_scaled_exchanges": True,
        },
    )
