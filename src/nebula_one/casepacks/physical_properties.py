from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .contracts import (
    IDENTIFIER_PATTERN,
    SHA256_PATTERN,
    StrictContract,
    VersionedIdentity,
    _non_blank,
)


PropertyCode = Literal[
    "lower_heating_value",
    "higher_heating_value",
    "density",
    "moisture_content",
    "dry_matter_fraction",
    "carbon_content",
    "sulfur_content",
    "recoverable_fraction",
    "specific_enthalpy",
]


class PublishedPropertyQuantity(StrictContract):
    value: Decimal = Field(gt=0)
    unit: Literal["TJ/Gg", "MJ/kg"]


class PublishedPropertySourceDocument(StrictContract):
    document_id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    publisher: str = Field(min_length=1, max_length=255)
    document_url: str = Field(min_length=1, max_length=2048)
    document_sha256: str = Field(pattern=SHA256_PATTERN)
    retrieved_on: date
    locator: str = Field(min_length=1, max_length=512)
    license: str = Field(min_length=1, max_length=255)
    license_url: str = Field(min_length=1, max_length=2048)

    @field_validator(
        "version",
        "title",
        "publisher",
        "document_url",
        "locator",
        "license",
        "license_url",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)


class PublishedPhysicalPropertySourceRecord(StrictContract):
    schema_version: Literal["nebula.published-physical-property-source.v1"]
    source_namespace: str = Field(min_length=1, max_length=255)
    source_record_id: str = Field(pattern=IDENTIFIER_PATTERN)
    source_version: str = Field(min_length=1, max_length=128)
    source_kind: Literal["published_source"]
    source_fuel_type: str = Field(min_length=1, max_length=255)
    property_code: Literal["lower_heating_value", "higher_heating_value"]
    original_quantity: PublishedPropertyQuantity
    normalized_quantity: PublishedPropertyQuantity
    normalization_formula: Literal[
        "energy_per_mass.tj_per_gg_to_mj_per_kg@1.0.0"
    ]
    basis: PhysicalPropertyBasis
    applicability_note: str = Field(min_length=1, max_length=2048)
    source_document: PublishedPropertySourceDocument
    review_status: Literal["reviewed", "approved"]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator(
        "source_namespace",
        "source_version",
        "source_fuel_type",
        "applicability_note",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)

    @model_validator(mode="after")
    def validate_normalization_and_hash(self):
        if self.original_quantity.unit != "TJ/Gg":
            raise ValueError("published heating value source must preserve TJ/Gg")
        if self.normalized_quantity.unit != "MJ/kg":
            raise ValueError("published heating value source must normalize to MJ/kg")
        if self.original_quantity.value != self.normalized_quantity.value:
            raise ValueError("1 TJ/Gg must normalize exactly to 1 MJ/kg")
        if self.basis.energy_convention != self.property_code:
            raise ValueError("published heating value basis must match property_code")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("published physical property source content_sha256 mismatch")
        return self


class ExactFlowIdentity(StrictContract):
    source_namespace: str = Field(min_length=1, max_length=255)
    flow_uuid: UUID
    version: str = Field(min_length=1, max_length=128)
    flow_content_sha256: str = Field(pattern=SHA256_PATTERN)
    flow_snapshot_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_namespace", "version")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)


class PhysicalUnitDefinition(StrictContract):
    source_namespace: str = Field(min_length=1, max_length=255)
    unit_id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=64)
    quantity_dimension: Literal[
        "mass",
        "energy",
        "energy_per_mass",
        "mass_per_volume",
        "mass_fraction",
    ]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_namespace", "version", "symbol")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)

    @model_validator(mode="after")
    def verify_content_hash(self):
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("physical unit definition content_sha256 mismatch")
        return self


class PhysicalPropertyBasis(StrictContract):
    material_condition: Literal["as_received", "dry", "dry_ash_free", "not_applicable"]
    energy_convention: Literal[
        "lower_heating_value",
        "higher_heating_value",
        "not_applicable",
    ]
    reference_temperature_k: float | None = Field(default=None, gt=0)
    reference_pressure_pa: float | None = Field(default=None, gt=0)

    @field_validator("reference_temperature_k", "reference_pressure_pa")
    @classmethod
    def require_finite_optional(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("physical property basis values must be finite")
        return value


class PhysicalPropertyEvidenceReceipt(StrictContract):
    source_namespace: str = Field(min_length=1, max_length=255)
    source_record_id: str = Field(min_length=1, max_length=255)
    source_version: str = Field(min_length=1, max_length=128)
    source_kind: Literal["published_source", "measured_source", "demonstration_authored"]
    citation: str = Field(min_length=1, max_length=2048)
    license: str = Field(min_length=1, max_length=255)
    source_hash_method: Literal["canonical_json_sha256"]
    source_content_sha256: str = Field(pattern=SHA256_PATTERN)
    review_status: Literal["software_verification_only", "reviewed", "approved"]
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator(
        "source_namespace",
        "source_record_id",
        "source_version",
        "citation",
        "license",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_blank(value)

    @model_validator(mode="after")
    def verify_receipt_hash(self):
        basis = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if canonical_json_sha256(basis) != self.receipt_sha256:
            raise ValueError("physical property evidence receipt_sha256 mismatch")
        return self


class PhysicalPropertyUncertainty(StrictContract):
    kind: Literal["none", "range", "standard_uncertainty"]
    minimum: float | None = None
    maximum: float | None = None
    standard_uncertainty: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_shape(self):
        values = (self.minimum, self.maximum, self.standard_uncertainty)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("physical property uncertainty values must be finite")
        if self.kind == "none" and any(value is not None for value in values):
            raise ValueError("none uncertainty cannot declare uncertainty values")
        if self.kind == "range":
            if self.minimum is None or self.maximum is None:
                raise ValueError("range uncertainty requires minimum and maximum")
            if self.minimum > self.maximum:
                raise ValueError("uncertainty minimum cannot exceed maximum")
            if self.standard_uncertainty is not None:
                raise ValueError("range uncertainty cannot declare standard_uncertainty")
        if self.kind == "standard_uncertainty":
            if self.standard_uncertainty is None:
                raise ValueError("standard_uncertainty value is required")
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("standard_uncertainty cannot declare a range")
        return self


class PhysicalPropertyRecord(StrictContract):
    record_id: str = Field(pattern=IDENTIFIER_PATTERN)
    subject_flow: ExactFlowIdentity
    property_code: PropertyCode
    value: float
    unit: PhysicalUnitDefinition
    basis: PhysicalPropertyBasis
    geography: str = Field(min_length=1, max_length=255)
    valid_from: date
    valid_to: date
    evidence: PhysicalPropertyEvidenceReceipt
    uncertainty: PhysicalPropertyUncertainty
    usage_gate: Literal["software_verification_only", "research", "approved"]
    record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("value")
    @classmethod
    def require_finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("physical property value must be finite")
        return value

    @field_validator("geography")
    @classmethod
    def strip_geography(cls, value: str) -> str:
        return _non_blank(value)

    @model_validator(mode="after")
    def validate_semantics_and_hash(self):
        if self.valid_to < self.valid_from:
            raise ValueError("physical property valid_to cannot precede valid_from")
        expected_dimension = {
            "lower_heating_value": "energy_per_mass",
            "higher_heating_value": "energy_per_mass",
            "specific_enthalpy": "energy_per_mass",
            "density": "mass_per_volume",
            "moisture_content": "mass_fraction",
            "dry_matter_fraction": "mass_fraction",
            "carbon_content": "mass_fraction",
            "sulfur_content": "mass_fraction",
            "recoverable_fraction": "mass_fraction",
        }[self.property_code]
        if self.unit.quantity_dimension != expected_dimension:
            raise ValueError("physical property unit dimension is incompatible")
        if self.property_code in {"lower_heating_value", "higher_heating_value"}:
            if self.basis.energy_convention != self.property_code:
                raise ValueError("heating value energy_convention must match property_code")
        elif self.basis.energy_convention != "not_applicable":
            raise ValueError("energy_convention is not applicable to this property")
        if self.property_code == "density" and (
            self.basis.reference_temperature_k is None
            or self.basis.reference_pressure_pa is None
        ):
            raise ValueError("density requires reference temperature and pressure")
        if expected_dimension == "mass_fraction" and not 0 <= self.value <= 1:
            raise ValueError("mass fraction physical property must be between 0 and 1")
        if expected_dimension != "mass_fraction" and self.value <= 0:
            raise ValueError("physical property value must be greater than zero")
        if (
            self.usage_gate == "approved"
            and self.evidence.review_status != "approved"
        ):
            raise ValueError("approved usage requires approved evidence")
        if (
            self.usage_gate != "software_verification_only"
            and self.evidence.review_status == "software_verification_only"
        ):
            raise ValueError("software verification evidence cannot support broader use")
        basis = self.model_dump(mode="json", exclude={"record_sha256"})
        if canonical_json_sha256(basis) != self.record_sha256:
            raise ValueError("physical property record_sha256 mismatch")
        return self


class PhysicalPropertySetIdentity(VersionedIdentity):
    lifecycle_status: Literal["draft", "frozen"]


class PhysicalPropertySetDocument(StrictContract):
    schema_version: Literal["nebula.physical-property-set.v1"]
    physical_property_set: PhysicalPropertySetIdentity
    case_pack_id: str = Field(pattern=IDENTIFIER_PATTERN)
    records: tuple[PhysicalPropertyRecord, ...] = Field(min_length=1)
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_records_and_hash(self):
        record_ids = [record.record_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("physical property record_id values must be unique")
        semantic_keys = [
            (
                str(record.subject_flow.flow_uuid),
                record.subject_flow.version,
                record.property_code,
                record.basis.model_dump_json(),
                record.geography,
                record.valid_from,
                record.valid_to,
            )
            for record in self.records
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("physical property records contain duplicate applicability")
        if self.physical_property_set.lifecycle_status == "frozen" and any(
            record.evidence.review_status == "software_verification_only"
            and record.usage_gate != "software_verification_only"
            for record in self.records
        ):
            raise ValueError("frozen property set contains unsupported evidence usage")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("physical property set content_sha256 mismatch")
        return self


class PhysicalPropertyValidationError(DomainError):
    pass


def validate_physical_property_flow_receipts(
    document: PhysicalPropertySetDocument,
    receipts: list[dict[str, Any]],
) -> None:
    for record in document.records:
        subject = record.subject_flow
        candidates = [
            receipt
            for receipt in receipts
            if str(receipt.get("source_namespace") or "") == subject.source_namespace
            and str(receipt.get("flow_uuid") or "") == str(subject.flow_uuid)
            and str(receipt.get("version") or "") == subject.version
        ]
        if len(candidates) != 1:
            raise PhysicalPropertyValidationError(
                code="PHYSICAL_PROPERTY_FLOW_RECEIPT_UNRESOLVED",
                message="physical property subject requires exactly one exact Flow receipt",
                status_code=422,
                details={
                    "record_id": record.record_id,
                    "candidate_count": len(candidates),
                },
            )
        receipt = candidates[0]
        if receipt.get("resolution") != "tidas_exact_snapshot":
            raise PhysicalPropertyValidationError(
                code="PHYSICAL_PROPERTY_FLOW_RECEIPT_NOT_EXACT",
                message="physical property subject cannot use a non-exact Flow receipt",
                status_code=422,
                details={"record_id": record.record_id},
            )
        mismatches = {
            field: {"expected": expected, "actual": receipt.get(field)}
            for field, expected in {
                "content_hash": subject.flow_content_sha256,
                "snapshot_hash": subject.flow_snapshot_sha256,
            }.items()
            if receipt.get(field) != expected
        }
        if mismatches:
            raise PhysicalPropertyValidationError(
                code="PHYSICAL_PROPERTY_FLOW_RECEIPT_MISMATCH",
                message="physical property subject Flow receipt does not match its exact pin",
                status_code=422,
                details={"record_id": record.record_id, "mismatches": mismatches},
            )


def parse_physical_property_set(payload: Any) -> PhysicalPropertySetDocument:
    return PhysicalPropertySetDocument.model_validate(payload)


def parse_published_physical_property_source(
    payload: Any,
) -> PublishedPhysicalPropertySourceRecord:
    return PublishedPhysicalPropertySourceRecord.model_validate(payload)


def validate_physical_property_source_records(
    property_sets: list[PhysicalPropertySetDocument]
    | tuple[PhysicalPropertySetDocument, ...],
    source_records: list[PublishedPhysicalPropertySourceRecord]
    | tuple[PublishedPhysicalPropertySourceRecord, ...],
) -> None:
    for property_set in property_sets:
        for record in property_set.records:
            if record.evidence.source_kind != "published_source":
                continue
            matches = [
                source
                for source in source_records
                if source.source_namespace == record.evidence.source_namespace
                and source.source_record_id == record.evidence.source_record_id
                and source.source_version == record.evidence.source_version
            ]
            if len(matches) != 1:
                raise PhysicalPropertyValidationError(
                    code="PHYSICAL_PROPERTY_SOURCE_UNRESOLVED",
                    message=(
                        "published physical property evidence requires exactly one "
                        "registered source record"
                    ),
                    status_code=422,
                    details={
                        "property_set_id": property_set.physical_property_set.id,
                        "record_id": record.record_id,
                        "candidate_count": len(matches),
                    },
                )
            source = matches[0]
            expected = {
                "source_kind": source.source_kind,
                "source_content_sha256": source.content_sha256,
                "review_status": source.review_status,
                "property_code": source.property_code,
                "value": source.normalized_quantity.value,
                "unit": source.normalized_quantity.unit,
                "basis": source.basis.model_dump(mode="json"),
            }
            actual = {
                "source_kind": record.evidence.source_kind,
                "source_content_sha256": record.evidence.source_content_sha256,
                "review_status": record.evidence.review_status,
                "property_code": record.property_code,
                "value": Decimal(str(record.value)),
                "unit": record.unit.symbol,
                "basis": record.basis.model_dump(mode="json"),
            }
            mismatches = {
                field: {"expected": expected[field], "actual": actual[field]}
                for field in expected
                if actual[field] != expected[field]
            }
            if mismatches:
                raise PhysicalPropertyValidationError(
                    code="PHYSICAL_PROPERTY_SOURCE_MISMATCH",
                    message=(
                        "physical property record does not match its published "
                        "source evidence"
                    ),
                    status_code=422,
                    details={
                        "property_set_id": property_set.physical_property_set.id,
                        "record_id": record.record_id,
                        "mismatches": mismatches,
                    },
                )
