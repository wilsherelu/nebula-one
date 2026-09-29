from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import (
    IDENTIFIER_PATTERN,
    SHA256_PATTERN,
    VERSION_PATTERN,
    StrictContract,
)


LicenseClassification = Literal[
    "open_redistributable",
    "exact_reference_only",
    "private_not_redistributable",
    "demonstration_authored",
]


class LicenseFileEvidence(StrictContract):
    path: str = Field(min_length=1, max_length=512)
    file_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def strip_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("license evidence path cannot be blank")
        return normalized


class LicenseAsset(StrictContract):
    asset_id: str = Field(pattern=IDENTIFIER_PATTERN)
    asset_type: Literal[
        "source_document",
        "data",
        "external_reference",
        "identifier_set",
    ]
    source: str | None = Field(default=None, max_length=1024)
    rights_holder: str | None = Field(default=None, max_length=512)
    license: str | None = Field(default=None, max_length=255)
    redistribution_allowed: bool
    version: str | None = Field(default=None, pattern=VERSION_PATTERN)
    classification: LicenseClassification
    audit_conclusion: Literal[
        "verified",
        "blocked_missing_source",
        "excluded_not_present",
    ]
    files: tuple[LicenseFileEvidence, ...] = ()
    notes: str = Field(min_length=1, max_length=2000)

    @field_validator("source", "rights_holder", "license", "notes")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("license text fields cannot be blank")
        return normalized

    @model_validator(mode="after")
    def enforce_audit_conclusion(self):
        if self.redistribution_allowed and self.classification not in {
            "open_redistributable",
            "demonstration_authored",
        }:
            raise ValueError(
                "redistribution is only allowed for open or authored assets"
            )
        if self.audit_conclusion == "verified":
            required = {
                "source": self.source,
                "rights_holder": self.rights_holder,
                "license": self.license,
                "version": self.version,
            }
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise ValueError(
                    "verified license asset is missing fields: " + ", ".join(missing)
                )
        elif self.redistribution_allowed:
            raise ValueError("unverified assets cannot allow redistribution")
        if self.classification == "private_not_redistributable" and self.redistribution_allowed:
            raise ValueError("private assets cannot allow redistribution")
        file_paths = [item.path for item in self.files]
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("license asset file paths must be unique")
        return self


class LicenseManifestDocument(StrictContract):
    schema_version: Literal["nebula.casepack-licenses.v1"]
    case_pack_id: str = Field(pattern=IDENTIFIER_PATTERN)
    manifest_version: str = Field(pattern=VERSION_PATTERN)
    audit_status: Literal["complete", "complete_with_gaps"]
    publication_gate: Literal["eligible", "blocked"]
    classification_policy: tuple[LicenseClassification, ...]
    assets: tuple[LicenseAsset, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self):
        required_policy = {
            "open_redistributable",
            "exact_reference_only",
            "private_not_redistributable",
            "demonstration_authored",
        }
        if set(self.classification_policy) != required_policy or len(
            self.classification_policy
        ) != len(required_policy):
            raise ValueError("classification_policy must declare each v1 class once")
        asset_ids = [item.asset_id for item in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("license asset IDs must be unique")
        file_paths = [evidence.path for asset in self.assets for evidence in asset.files]
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("license evidence paths must be globally unique")
        has_gaps = any(
            item.audit_conclusion != "verified" for item in self.assets
        )
        expected_status = "complete_with_gaps" if has_gaps else "complete"
        expected_gate = "blocked" if has_gaps else "eligible"
        if self.audit_status != expected_status:
            raise ValueError(f"audit_status must be {expected_status}")
        if self.publication_gate != expected_gate:
            raise ValueError(f"publication_gate must be {expected_gate}")
        return self


def parse_license_manifest(payload: Any) -> LicenseManifestDocument:
    return LicenseManifestDocument.model_validate(payload)
