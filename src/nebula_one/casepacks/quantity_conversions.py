from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .contracts import IDENTIFIER_PATTERN, SHA256_PATTERN, StrictContract, _non_blank
from .physical_properties import (
    ExactFlowIdentity,
    PhysicalPropertyBasis,
    PhysicalPropertyRecord,
    PhysicalPropertySetDocument,
    PhysicalUnitDefinition,
    validate_physical_property_flow_receipts,
)


class ExactReferenceIdentity(StrictContract):
    source_namespace: str = Field(min_length=1, max_length=255)
    uuid: UUID
    version: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_namespace", "version")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)


class SolvedExchangeQuantity(StrictContract):
    solved_snapshot_id: UUID
    solved_snapshot_content_sha256: str = Field(pattern=SHA256_PATTERN)
    process_uuid: UUID
    exchange_id: str = Field(min_length=1, max_length=255)
    subject_flow: ExactFlowIdentity
    direction: Literal["input", "output"]
    amount: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=128)
    flow_property: ExactReferenceIdentity
    unit_group: ExactReferenceIdentity
    unit_content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("exchange_id", "unit")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)


class PhysicalPropertySetRef(StrictContract):
    id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class ConversionFormula(StrictContract):
    code: Literal["mass_to_energy.heating_value"]
    version: Literal["1.0.0"]
    expression: Literal["energy_MJ = mass_kg * heating_value_MJ_per_kg"]
    source_dimension: Literal["mass"]
    property_dimension: Literal["energy_per_mass"]
    target_dimension: Literal["energy"]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def verify_content_hash(self):
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("conversion formula content_sha256 mismatch")
        return self


class ConvertedQuantity(StrictContract):
    amount: Decimal = Field(gt=0)
    unit: PhysicalUnitDefinition


class QuantityConversionReceipt(StrictContract):
    schema_version: Literal["nebula.quantity-conversion-receipt.v1"]
    conversion_id: str = Field(pattern=IDENTIFIER_PATTERN)
    conversion_type: Literal["mass_to_energy"]
    execution_purpose: Literal["software_verification", "research", "approved"]
    conversion_date: date
    source_quantity: SolvedExchangeQuantity
    property_set_ref: PhysicalPropertySetRef
    property_record: PhysicalPropertyRecord
    requested_basis: PhysicalPropertyBasis
    formula: ConversionFormula
    result: ConvertedQuantity
    warnings: tuple[str, ...]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def verify_content_hash(self):
        if self.property_record.subject_flow != self.source_quantity.subject_flow:
            raise ValueError("conversion subject Flow does not match the property record")
        if self.property_record.basis != self.requested_basis:
            raise ValueError("conversion requested basis does not match the property record")
        if not self.property_record.valid_from <= self.conversion_date <= self.property_record.valid_to:
            raise ValueError("conversion date is outside the property record validity period")
        expected_result = self.source_quantity.amount * Decimal(
            str(self.property_record.value)
        )
        if self.result.amount != expected_result:
            raise ValueError("conversion result does not match the frozen formula inputs")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("quantity conversion content_sha256 mismatch")
        return self


class QuantityConversionError(DomainError):
    pass


def _fail(code: str, message: str, **details: Any) -> None:
    raise QuantityConversionError(
        code=code,
        message=message,
        status_code=422,
        details=details,
    )


def _formula() -> ConversionFormula:
    basis = {
        "code": "mass_to_energy.heating_value",
        "version": "1.0.0",
        "expression": "energy_MJ = mass_kg * heating_value_MJ_per_kg",
        "source_dimension": "mass",
        "property_dimension": "energy_per_mass",
        "target_dimension": "energy",
    }
    return ConversionFormula(**basis, content_sha256=canonical_json_sha256(basis))


def _energy_unit() -> PhysicalUnitDefinition:
    basis = {
        "source_namespace": "nebula-one.units",
        "unit_id": "energy.mj",
        "version": "1.0.0",
        "symbol": "MJ",
        "quantity_dimension": "energy",
    }
    return PhysicalUnitDefinition(
        **basis,
        content_sha256=canonical_json_sha256(basis),
    )


def _find_single(items: list[dict[str, Any]], *, key: str, value: str, code: str) -> dict[str, Any]:
    matches = [item for item in items if str(item.get(key) or "") == value]
    if len(matches) != 1:
        _fail(code, "conversion input requires exactly one matching provider item", count=len(matches))
    return matches[0]


def create_mass_to_energy_conversion(
    *,
    solved_snapshot: dict[str, Any],
    property_set: PhysicalPropertySetDocument,
    property_record_id: str,
    exchange_id: str,
    requested_basis: PhysicalPropertyBasis,
    execution_purpose: Literal["software_verification", "research", "approved"],
) -> QuantityConversionReceipt:
    if property_set.physical_property_set.lifecycle_status != "frozen":
        _fail("QUANTITY_CONVERSION_PROPERTY_SET_NOT_FROZEN", "property set must be frozen")
    records = [record for record in property_set.records if record.record_id == property_record_id]
    if len(records) != 1:
        _fail(
            "QUANTITY_CONVERSION_PROPERTY_RECORD_UNRESOLVED",
            "conversion requires exactly one property record",
            count=len(records),
        )
    record = records[0]
    if record.property_code not in {"lower_heating_value", "higher_heating_value"}:
        _fail(
            "QUANTITY_CONVERSION_PROPERTY_UNSUPPORTED",
            "mass-to-energy conversion requires a heating-value property",
        )
    if record.unit.symbol != "MJ/kg" or record.unit.quantity_dimension != "energy_per_mass":
        _fail(
            "QUANTITY_CONVERSION_PROPERTY_UNIT_UNSUPPORTED",
            "mass-to-energy v1 requires a MJ/kg heating value",
        )
    if record.basis != requested_basis:
        _fail(
            "QUANTITY_CONVERSION_BASIS_MISMATCH",
            "requested conversion basis does not match the property record",
        )
    allowed_purposes = {
        "software_verification_only": {"software_verification"},
        "research": {"software_verification", "research"},
        "approved": {"software_verification", "research", "approved"},
    }[record.usage_gate]
    if execution_purpose not in allowed_purposes:
        _fail(
            "QUANTITY_CONVERSION_USAGE_GATE_BLOCKED",
            "physical property usage gate does not allow this conversion purpose",
        )

    provider_receipt = solved_snapshot.get("provider_receipt")
    if not isinstance(provider_receipt, dict):
        _fail("QUANTITY_CONVERSION_PROVIDER_RECEIPT_MISSING", "solved snapshot has no provider receipt")
    flow_receipts = provider_receipt.get("technosphere_flow_receipts")
    if not isinstance(flow_receipts, list):
        _fail("QUANTITY_CONVERSION_FLOW_RECEIPTS_MISSING", "solved snapshot has no Flow receipts")
    validate_physical_property_flow_receipts(property_set, flow_receipts)
    flow_receipt = _find_single(
        flow_receipts,
        key="exchange_id",
        value=exchange_id,
        code="QUANTITY_CONVERSION_FLOW_RECEIPT_UNRESOLVED",
    )
    scaled = solved_snapshot.get("scaled_technosphere_exchanges")
    if not isinstance(scaled, list):
        _fail("QUANTITY_CONVERSION_SCALED_EXCHANGES_MISSING", "solved snapshot has no scaled exchanges")
    exchange = _find_single(
        scaled,
        key="exchange_id",
        value=exchange_id,
        code="QUANTITY_CONVERSION_EXCHANGE_UNRESOLVED",
    )
    expected_exchange = {
        "process_id": str(flow_receipt.get("process_uuid") or ""),
        "flow_uuid": str(record.subject_flow.flow_uuid),
        "unit": str(flow_receipt.get("unit") or ""),
        "unit_group": str(flow_receipt.get("unit_group_uuid") or ""),
    }
    mismatches = {
        field: {"expected": expected, "actual": exchange.get(field)}
        for field, expected in expected_exchange.items()
        if exchange.get(field) != expected
    }
    if mismatches:
        _fail(
            "QUANTITY_CONVERSION_EXCHANGE_MISMATCH",
            "scaled exchange does not match its exact provider receipt",
            mismatches=mismatches,
        )
    if exchange.get("unit") != "kg":
        _fail(
            "QUANTITY_CONVERSION_SOURCE_UNIT_UNSUPPORTED",
            "mass-to-energy v1 requires a kg solved exchange",
        )
    required_receipt_fields = (
        "flow_property_uuid",
        "flow_property_version",
        "flow_property_content_hash",
        "unit_group_uuid",
        "unit_group_version",
        "unit_group_content_hash",
        "unit_content_hash",
    )
    missing = [field for field in required_receipt_fields if not flow_receipt.get(field)]
    if missing:
        _fail(
            "QUANTITY_CONVERSION_UNIT_IDENTITY_INCOMPLETE",
            "provider Flow receipt lacks exact unit identity",
            missing=missing,
        )
    snapshot_id = solved_snapshot.get("id")
    snapshot_hash = solved_snapshot.get("content_sha256")
    if not snapshot_id or not snapshot_hash:
        _fail(
            "QUANTITY_CONVERSION_SNAPSHOT_IDENTITY_MISSING",
            "solved snapshot identity and content hash are required",
        )
    created_at = solved_snapshot.get("created_at")
    try:
        conversion_date = datetime.fromisoformat(str(created_at)).date()
    except (TypeError, ValueError) as exc:
        raise QuantityConversionError(
            code="QUANTITY_CONVERSION_SNAPSHOT_DATE_INVALID",
            message="solved snapshot must provide an ISO created_at timestamp",
            status_code=422,
        ) from exc
    if not record.valid_from <= conversion_date <= record.valid_to:
        _fail(
            "QUANTITY_CONVERSION_PROPERTY_OUTSIDE_VALIDITY",
            "solved snapshot date is outside the property record validity period",
            conversion_date=conversion_date.isoformat(),
        )
    source_quantity = SolvedExchangeQuantity(
        solved_snapshot_id=snapshot_id,
        solved_snapshot_content_sha256=snapshot_hash,
        process_uuid=flow_receipt["process_uuid"],
        exchange_id=exchange_id,
        subject_flow=record.subject_flow,
        direction=exchange["direction"],
        amount=Decimal(str(exchange["amount"])),
        unit=exchange["unit"],
        flow_property=ExactReferenceIdentity(
            source_namespace=record.subject_flow.source_namespace,
            uuid=flow_receipt["flow_property_uuid"],
            version=flow_receipt["flow_property_version"],
            content_sha256=flow_receipt["flow_property_content_hash"],
        ),
        unit_group=ExactReferenceIdentity(
            source_namespace=record.subject_flow.source_namespace,
            uuid=flow_receipt["unit_group_uuid"],
            version=flow_receipt["unit_group_version"],
            content_sha256=flow_receipt["unit_group_content_hash"],
        ),
        unit_content_sha256=flow_receipt["unit_content_hash"],
    )
    property_set_ref = PhysicalPropertySetRef(
        id=property_set.physical_property_set.id,
        version=property_set.physical_property_set.version,
        content_sha256=property_set.content_sha256,
    )
    formula = _formula()
    result = ConvertedQuantity(
        amount=source_quantity.amount * Decimal(str(record.value)),
        unit=_energy_unit(),
    )
    warnings = (
        ("SOFTWARE_VERIFICATION_ONLY",)
        if record.usage_gate == "software_verification_only"
        else ()
    )
    identity_basis = {
        "solved_snapshot_content_sha256": snapshot_hash,
        "exchange_id": exchange_id,
        "property_set_content_sha256": property_set.content_sha256,
        "property_record_sha256": record.record_sha256,
        "formula_content_sha256": formula.content_sha256,
        "execution_purpose": execution_purpose,
        "conversion_date": conversion_date.isoformat(),
    }
    receipt_basis = {
        "schema_version": "nebula.quantity-conversion-receipt.v1",
        "conversion_id": f"mass-to-energy-{canonical_json_sha256(identity_basis)[:24]}",
        "conversion_type": "mass_to_energy",
        "execution_purpose": execution_purpose,
        "conversion_date": conversion_date.isoformat(),
        "source_quantity": source_quantity.model_dump(mode="json"),
        "property_set_ref": property_set_ref.model_dump(mode="json"),
        "property_record": record.model_dump(mode="json"),
        "requested_basis": requested_basis.model_dump(mode="json"),
        "formula": formula.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "warnings": warnings,
    }
    return QuantityConversionReceipt(
        **receipt_basis,
        content_sha256=canonical_json_sha256(receipt_basis),
    )
