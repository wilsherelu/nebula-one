from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from ..casepacks.contracts import SHA256_PATTERN, StrictContract, _non_blank
from ..casepacks.physical_properties import ExactFlowIdentity, PhysicalUnitDefinition
from ..casepacks.quantity_conversions import ExactReferenceIdentity, QuantityConversionReceipt
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .dependency_gap import dependency_gap


class EnergyBasis(StrictContract):
    energy_convention: Literal[
        "declared_energy",
        "lower_heating_value",
        "higher_heating_value",
    ]
    material_condition: Literal["not_applicable", "as_received", "dry", "dry_ash_free"]

    @model_validator(mode="after")
    def validate_combination(self):
        if self.energy_convention == "declared_energy" and self.material_condition != "not_applicable":
            raise ValueError("declared energy cannot declare a material condition")
        if self.energy_convention != "declared_energy" and self.material_condition == "not_applicable":
            raise ValueError("heating-value energy requires a material condition")
        return self


class ProviderEnergyUnitIdentity(StrictContract):
    kind: Literal["provider_exact"]
    source_namespace: str = Field(min_length=1, max_length=255)
    symbol: str = Field(min_length=1, max_length=128)
    flow_property: ExactReferenceIdentity
    unit_group: ExactReferenceIdentity
    unit_content_sha256: str = Field(pattern=SHA256_PATTERN)
    identity_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_namespace", "symbol")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)

    @model_validator(mode="after")
    def verify_hash(self):
        basis = self.model_dump(mode="json", exclude={"identity_sha256"})
        if canonical_json_sha256(basis) != self.identity_sha256:
            raise ValueError("provider energy unit identity_sha256 mismatch")
        return self


class ConvertedEnergyUnitIdentity(StrictContract):
    kind: Literal["conversion_canonical"]
    definition: PhysicalUnitDefinition
    identity_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def verify_hash(self):
        if self.definition.quantity_dimension != "energy":
            raise ValueError("converted energy unit must have the energy dimension")
        basis = self.model_dump(mode="json", exclude={"identity_sha256"})
        if canonical_json_sha256(basis) != self.identity_sha256:
            raise ValueError("converted energy unit identity_sha256 mismatch")
        return self


EnergyUnitIdentity = ProviderEnergyUnitIdentity | ConvertedEnergyUnitIdentity


class DirectEnergySource(StrictContract):
    kind: Literal["direct_solved_exchange"]
    solved_snapshot_content_sha256: str = Field(pattern=SHA256_PATTERN)
    process_uuid: UUID
    exchange_id: str = Field(min_length=1, max_length=255)
    flow_receipt_sha256: str = Field(pattern=SHA256_PATTERN)


class ConvertedEnergySource(StrictContract):
    kind: Literal["quantity_conversion"]
    conversion_id: str = Field(min_length=1, max_length=128)
    conversion_content_sha256: str = Field(pattern=SHA256_PATTERN)
    source_exchange_id: str = Field(min_length=1, max_length=255)


EnergyEntrySource = DirectEnergySource | ConvertedEnergySource


class EnergyCarrierEntry(StrictContract):
    entry_id: str = Field(min_length=1, max_length=128)
    carrier_flow: ExactFlowIdentity
    amount: Decimal = Field(gt=0)
    unit_symbol: str = Field(min_length=1, max_length=128)
    unit_identity: EnergyUnitIdentity
    basis: EnergyBasis
    source: EnergyEntrySource
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_semantics_and_hash(self):
        if self.unit_symbol != "MJ":
            raise ValueError("energy.carrier.solved.v1 only accepts MJ entries")
        if isinstance(self.source, DirectEnergySource):
            if not isinstance(self.unit_identity, ProviderEnergyUnitIdentity):
                raise ValueError("direct energy requires a provider unit identity")
            if self.basis.energy_convention != "declared_energy":
                raise ValueError("direct energy must use declared_energy basis")
        else:
            if not isinstance(self.unit_identity, ConvertedEnergyUnitIdentity):
                raise ValueError("converted energy requires a canonical conversion unit")
            if self.basis.energy_convention == "declared_energy":
                raise ValueError("converted energy must retain its heating-value basis")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("energy carrier entry content_sha256 mismatch")
        return self


class EnergyCarrierSeries(StrictContract):
    series_id: str = Field(min_length=1, max_length=128)
    unit_symbol: Literal["MJ"]
    unit_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    basis: EnergyBasis
    entries: tuple[EnergyCarrierEntry, ...] = Field(min_length=1)
    total_amount: Decimal = Field(gt=0)
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_entries_and_hash(self):
        if any(entry.unit_identity.identity_sha256 != self.unit_identity_sha256 for entry in self.entries):
            raise ValueError("energy series contains different unit identities")
        if any(entry.basis != self.basis for entry in self.entries):
            raise ValueError("energy series contains different basis identities")
        if sum((entry.amount for entry in self.entries), Decimal("0")) != self.total_amount:
            raise ValueError("energy series total does not equal its entries")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("energy carrier series content_sha256 mismatch")
        return self


class EnergyCarrierIssue(StrictContract):
    code: str = Field(min_length=1, max_length=128)
    severity: Literal["warning"]
    message: str = Field(min_length=1, max_length=1024)


class EnergySolvedSnapshotRef(StrictContract):
    id: UUID
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    solve_hash: str = Field(pattern=SHA256_PATTERN)


class EnergyCarrierSolved(StrictContract):
    schema_version: Literal["nebula.energy.carrier.solved.v1"]
    solved_snapshot_ref: EnergySolvedSnapshotRef
    series: tuple[EnergyCarrierSeries, ...] = Field(min_length=1)
    issues: tuple[EnergyCarrierIssue, ...]
    status: Literal["passed", "passed_with_warnings"]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_status_and_hash(self):
        series_ids = [series.series_id for series in self.series]
        if len(series_ids) != len(set(series_ids)):
            raise ValueError("energy carrier series_id values must be unique")
        expected_status = "passed_with_warnings" if self.issues else "passed"
        if self.status != expected_status:
            raise ValueError("energy carrier status does not match its issues")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("energy carrier result content_sha256 mismatch")
        return self


class EnergyCarrierError(DomainError):
    pass


def _fail(code: str, message: str, **details: Any) -> None:
    raise EnergyCarrierError(code=code, message=message, status_code=422, details=details)


def _single(items: list[dict[str, Any]], *, key: str, value: str, code: str) -> dict[str, Any]:
    matches = [item for item in items if str(item.get(key) or "") == value]
    if len(matches) != 1:
        _fail(code, "energy carrier input requires exactly one matching item", count=len(matches))
    return matches[0]


def _provider_unit(receipt: dict[str, Any]) -> ProviderEnergyUnitIdentity:
    required = (
        "source_namespace",
        "unit",
        "flow_property_uuid",
        "flow_property_version",
        "flow_property_content_hash",
        "unit_group_uuid",
        "unit_group_version",
        "unit_group_content_hash",
        "unit_content_hash",
    )
    missing = [key for key in required if not receipt.get(key)]
    if missing:
        _fail(
            "ENERGY_CARRIER_UNIT_IDENTITY_INCOMPLETE",
            "direct energy Flow receipt lacks exact unit identity",
            missing=missing,
        )
    basis = {
        "kind": "provider_exact",
        "source_namespace": receipt["source_namespace"],
        "symbol": receipt["unit"],
        "flow_property": {
            "source_namespace": receipt["source_namespace"],
            "uuid": receipt["flow_property_uuid"],
            "version": receipt["flow_property_version"],
            "content_sha256": receipt["flow_property_content_hash"],
        },
        "unit_group": {
            "source_namespace": receipt["source_namespace"],
            "uuid": receipt["unit_group_uuid"],
            "version": receipt["unit_group_version"],
            "content_sha256": receipt["unit_group_content_hash"],
        },
        "unit_content_sha256": receipt["unit_content_hash"],
    }
    return ProviderEnergyUnitIdentity(
        **basis,
        identity_sha256=canonical_json_sha256(basis),
    )


def _converted_unit(definition: PhysicalUnitDefinition) -> ConvertedEnergyUnitIdentity:
    basis = {
        "kind": "conversion_canonical",
        "definition": definition.model_dump(mode="json"),
    }
    return ConvertedEnergyUnitIdentity(
        **basis,
        identity_sha256=canonical_json_sha256(basis),
    )


def _entry(payload: dict[str, Any]) -> EnergyCarrierEntry:
    identity = {
        "carrier_flow": payload["carrier_flow"],
        "source": payload["source"],
        "basis": payload["basis"],
    }
    basis = {
        "entry_id": f"energy-entry-{canonical_json_sha256(identity)[:24]}",
        **payload,
    }
    return EnergyCarrierEntry(**basis, content_sha256=canonical_json_sha256(basis))


def build_energy_carrier_solved(
    *,
    solved_snapshot: dict[str, Any],
    direct_exchange_ids: tuple[str, ...],
    conversions: tuple[QuantityConversionReceipt, ...],
) -> EnergyCarrierSolved:
    snapshot_id = solved_snapshot.get("id")
    snapshot_hash = solved_snapshot.get("content_sha256")
    solve_hash = solved_snapshot.get("solve_hash")
    if not snapshot_id or not snapshot_hash or not solve_hash:
        _fail("ENERGY_CARRIER_SNAPSHOT_IDENTITY_MISSING", "solved snapshot identity is incomplete")
    if len(direct_exchange_ids) != len(set(direct_exchange_ids)):
        _fail("ENERGY_CARRIER_DIRECT_EXCHANGE_DUPLICATE", "direct exchange ids must be unique")
    converted_exchange_ids = [
        conversion.source_quantity.exchange_id for conversion in conversions
    ]
    overlap = sorted(set(direct_exchange_ids).intersection(converted_exchange_ids))
    if overlap:
        _fail(
            "ENERGY_CARRIER_SOURCE_DOUBLE_COUNTED",
            "the same solved exchange cannot be both direct and converted energy",
            exchange_ids=overlap,
        )
    provider_receipt = solved_snapshot.get("provider_receipt")
    if not isinstance(provider_receipt, dict):
        _fail("ENERGY_CARRIER_PROVIDER_RECEIPT_MISSING", "solved snapshot has no provider receipt")
    flow_receipts = provider_receipt.get("technosphere_flow_receipts")
    scaled_exchanges = solved_snapshot.get("scaled_technosphere_exchanges")
    if not isinstance(flow_receipts, list) or not isinstance(scaled_exchanges, list):
        _fail("ENERGY_CARRIER_SOLVED_EVIDENCE_MISSING", "solved energy evidence is incomplete")

    entries: list[EnergyCarrierEntry] = []
    issues: list[EnergyCarrierIssue] = []
    for exchange_id in direct_exchange_ids:
        receipt = _single(
            flow_receipts,
            key="exchange_id",
            value=exchange_id,
            code="ENERGY_CARRIER_FLOW_RECEIPT_UNRESOLVED",
        )
        exchange = _single(
            scaled_exchanges,
            key="exchange_id",
            value=exchange_id,
            code="ENERGY_CARRIER_EXCHANGE_UNRESOLVED",
        )
        if receipt.get("resolution") != "tidas_exact_snapshot":
            _fail(
                "ENERGY_CARRIER_FLOW_NOT_EXACT",
                "direct energy requires an exact TIDAS Flow receipt",
                exchange_id=exchange_id,
                dependency_gap=dependency_gap(
                    code="ENERGY_CARRIER_FLOW_NOT_EXACT",
                    kind="tidas_exact_flow_snapshot",
                    step="energy_carrier",
                    what_missing={
                        "identity": {
                            "source_namespace": receipt.get("source_namespace"),
                            "flow_uuid": receipt.get("flow_uuid"),
                            "version": receipt.get("version"),
                        },
                        "required_identity": {
                            "resolution": "tidas_exact_snapshot",
                            "source_namespace": "tiangong_open_data",
                        },
                        "observed_resolution": receipt.get("resolution"),
                        "exchange_id": exchange_id,
                    },
                    affects={
                        "downstream_steps": [
                            "period_energy_total",
                            "carbon_management",
                            "organization_ghg_inventory",
                        ],
                        "scopes_affected": ["scope_1", "scope_2"],
                    },
                    how_to_resolve=[
                        {
                            "action": "为该能量端口配置精确 TIDAS Flow 快照，使求解回执的 resolution 成为 tidas_exact_snapshot",
                            "owner": "上游引擎与目录数据",
                            "precondition": f"端口 {exchange_id} 的流身份可在目录中解析为唯一版本",
                        },
                        {
                            "action": "重新求解并冻结快照后再次运行能量腿",
                            "owner": "本机验收",
                            "precondition": "新 provider 回执携带该端口的精确流身份",
                        },
                    ],
                    evidence={
                        "solved_snapshot_id": snapshot_id,
                        "solved_snapshot_sha256": snapshot_hash,
                        "solve_hash": solve_hash,
                    },
                ),
            )
        flow_identity_fields = (
            "source_namespace",
            "flow_uuid",
            "version",
            "content_hash",
            "snapshot_hash",
        )
        missing_flow_identity = [field for field in flow_identity_fields if not receipt.get(field)]
        if missing_flow_identity:
            _fail(
                "ENERGY_CARRIER_FLOW_IDENTITY_INCOMPLETE",
                "direct energy Flow receipt lacks exact Flow identity",
                missing=missing_flow_identity,
            )
        expected = {
            "process_id": receipt.get("process_uuid"),
            "flow_uuid": receipt.get("flow_uuid"),
            "unit": receipt.get("unit"),
            "unit_group": receipt.get("unit_group_uuid"),
        }
        mismatches = {
            key: {"expected": value, "actual": exchange.get(key)}
            for key, value in expected.items()
            if exchange.get(key) != value
        }
        if mismatches:
            _fail(
                "ENERGY_CARRIER_EXCHANGE_MISMATCH",
                "direct energy exchange does not match its exact Flow receipt",
                mismatches=mismatches,
            )
        if exchange.get("unit") != "MJ":
            _fail("ENERGY_CARRIER_DIRECT_UNIT_UNSUPPORTED", "direct energy v1 requires MJ")
        try:
            amount = Decimal(str(exchange["amount"]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise EnergyCarrierError(
                code="ENERGY_CARRIER_AMOUNT_INVALID",
                message="direct energy amount is invalid",
                status_code=422,
            ) from exc
        if not amount.is_finite() or amount <= 0:
            _fail("ENERGY_CARRIER_AMOUNT_INVALID", "direct energy amount must be finite and positive")
        unit_identity = _provider_unit(receipt)
        carrier_flow = {
            "source_namespace": receipt["source_namespace"],
            "flow_uuid": receipt["flow_uuid"],
            "version": receipt["version"],
            "flow_content_sha256": receipt["content_hash"],
            "flow_snapshot_sha256": receipt["snapshot_hash"],
        }
        entries.append(
            _entry(
                {
                    "carrier_flow": carrier_flow,
                    "amount": str(amount),
                    "unit_symbol": "MJ",
                    "unit_identity": unit_identity.model_dump(mode="json"),
                    "basis": {
                        "energy_convention": "declared_energy",
                        "material_condition": "not_applicable",
                    },
                    "source": {
                        "kind": "direct_solved_exchange",
                        "solved_snapshot_content_sha256": snapshot_hash,
                        "process_uuid": receipt["process_uuid"],
                        "exchange_id": exchange_id,
                        "flow_receipt_sha256": canonical_json_sha256(receipt),
                    },
                }
            )
        )

    for conversion in conversions:
        if conversion.source_quantity.solved_snapshot_content_sha256 != snapshot_hash:
            _fail(
                "ENERGY_CARRIER_CONVERSION_SNAPSHOT_MISMATCH",
                "quantity conversion belongs to a different solved snapshot",
            )
        if conversion.result.unit.symbol != "MJ":
            _fail("ENERGY_CARRIER_CONVERSION_UNIT_UNSUPPORTED", "converted energy v1 requires MJ")
        unit_identity = _converted_unit(conversion.result.unit)
        entries.append(
            _entry(
                {
                    "carrier_flow": conversion.property_record.subject_flow.model_dump(mode="json"),
                    "amount": str(conversion.result.amount),
                    "unit_symbol": "MJ",
                    "unit_identity": unit_identity.model_dump(mode="json"),
                    "basis": {
                        "energy_convention": conversion.property_record.basis.energy_convention,
                        "material_condition": conversion.property_record.basis.material_condition,
                    },
                    "source": {
                        "kind": "quantity_conversion",
                        "conversion_id": conversion.conversion_id,
                        "conversion_content_sha256": conversion.content_sha256,
                        "source_exchange_id": conversion.source_quantity.exchange_id,
                    },
                }
            )
        )
        for warning in conversion.warnings:
            issues.append(
                EnergyCarrierIssue(
                    code=f"CONVERSION_{warning}",
                    severity="warning",
                    message="energy entry retains a warning from its quantity conversion receipt",
                )
            )

    if not entries:
        _fail("ENERGY_CARRIER_INPUT_EMPTY", "at least one direct or converted energy entry is required")
    entry_ids = [entry.entry_id for entry in entries]
    if len(entry_ids) != len(set(entry_ids)):
        _fail("ENERGY_CARRIER_ENTRY_DUPLICATE", "energy carrier entries must be unique")
    if provider_receipt.get("provenance", {}).get("background_claim_scope"):
        issues.append(
            EnergyCarrierIssue(
                code="PARTIAL_BACKGROUND_SCOPE",
                severity="warning",
                message="the solved snapshot contains a partial background leaf, not a complete background system",
            )
        )

    grouped: dict[tuple[str, str], list[EnergyCarrierEntry]] = defaultdict(list)
    for entry in entries:
        basis_hash = canonical_json_sha256(entry.basis.model_dump(mode="json"))
        grouped[(entry.unit_identity.identity_sha256, basis_hash)].append(entry)
    series_items: list[EnergyCarrierSeries] = []
    for (unit_hash, basis_hash), grouped_entries in sorted(grouped.items()):
        ordered = tuple(sorted(grouped_entries, key=lambda item: item.entry_id))
        total = sum((entry.amount for entry in ordered), Decimal("0"))
        series_basis = {
            "series_id": f"energy-series-{canonical_json_sha256({'unit': unit_hash, 'basis': basis_hash})[:24]}",
            "unit_symbol": "MJ",
            "unit_identity_sha256": unit_hash,
            "basis": ordered[0].basis.model_dump(mode="json"),
            "entries": [entry.model_dump(mode="json") for entry in ordered],
            "total_amount": str(total),
        }
        series_items.append(
            EnergyCarrierSeries(
                **series_basis,
                content_sha256=canonical_json_sha256(series_basis),
            )
        )
    deduplicated_issues = tuple(
        sorted(
            {issue.code: issue for issue in issues}.values(),
            key=lambda issue: issue.code,
        )
    )
    result_basis = {
        "schema_version": "nebula.energy.carrier.solved.v1",
        "solved_snapshot_ref": {
            "id": snapshot_id,
            "content_sha256": snapshot_hash,
            "solve_hash": solve_hash,
        },
        "series": [series.model_dump(mode="json") for series in series_items],
        "issues": [issue.model_dump(mode="json") for issue in deduplicated_issues],
        "status": "passed_with_warnings" if deduplicated_issues else "passed",
    }
    return EnergyCarrierSolved(
        **result_basis,
        content_sha256=canonical_json_sha256(result_basis),
    )
