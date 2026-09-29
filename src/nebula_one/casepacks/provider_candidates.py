from __future__ import annotations

from datetime import date
import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import SHA256_PATTERN, StrictContract


UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TIDAS_VERSION_PATTERN = r"^[0-9]{2}\.[0-9]{2}\.[0-9]{3}$"


class ExactDatasetRef(StrictContract):
    source_namespace: Literal["tiangong_open_data"]
    dataset_kind: Literal["flow", "process", "lifecycle_model"]
    uuid: str = Field(pattern=UUID_PATTERN)
    version: str = Field(pattern=TIDAS_VERSION_PATTERN)
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class ExactReferenceRef(StrictContract):
    uuid: str = Field(pattern=UUID_PATTERN)
    version: str = Field(pattern=TIDAS_VERSION_PATTERN)


class ReferenceClosureAudit(StrictContract):
    status: Literal["passed", "failed"]
    attempts: int = Field(ge=1)
    missing_unit_group_uuids: tuple[str, ...] = ()

    @field_validator("missing_unit_group_uuids")
    @classmethod
    def validate_unit_group_uuids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("missing Unit group UUIDs must be unique")
        if any(re.fullmatch(UUID_PATTERN, value) is None for value in values):
            raise ValueError("missing Unit group references must be UUIDs")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_status(self):
        if self.status == "passed" and self.missing_unit_group_uuids:
            raise ValueError("passed reference closure cannot contain missing UUIDs")
        if self.status == "failed" and not self.missing_unit_group_uuids:
            raise ValueError("failed reference closure requires missing UUIDs")
        return self


class RecallSnapshot(StrictContract):
    dataset_kind: Literal["flow", "process", "lifecycle_model"]
    query: str = Field(min_length=1, max_length=255)
    state_scope: Literal["open"]
    data_source: Literal["tg"]
    record_count: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query cannot be blank")
        return normalized


class ProviderCandidate(StrictContract):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    intended_role: Literal[
        "crude_oil",
        "distillate",
        "hydrogen",
        "low_sulfur_diesel",
        "other",
    ]
    identity: ExactDatasetRef
    type_of_data_set: str = Field(min_length=1, max_length=128)
    name_en: str = Field(min_length=1, max_length=255)
    name_zh: str | None = Field(default=None, max_length=255)
    flow_property_ref: ExactReferenceRef | None = None
    disposition: Literal["recall_only", "rejected", "accepted"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("type_of_data_set", "name_en", "name_zh", "reason")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("candidate text cannot be blank")
        return normalized


class ProviderCandidateManifest(StrictContract):
    schema_version: Literal["nebula.provider-candidate-manifest.v1"]
    case_pack_id: Literal["petrochemical-refinery-reference"]
    audit_date: date
    raw_payload_committed: Literal[False]
    reference_closure: ReferenceClosureAudit
    recall_snapshots: tuple[RecallSnapshot, ...] = Field(min_length=1)
    candidates: tuple[ProviderCandidate, ...]
    acceptance_gate: Literal["blocked", "ready"]

    @model_validator(mode="after")
    def validate_acceptance_gate(self):
        queries = [
            (item.dataset_kind, item.query.casefold())
            for item in self.recall_snapshots
        ]
        if len(queries) != len(set(queries)):
            raise ValueError("recall snapshot queries must be unique")
        candidate_ids = [item.candidate_id for item in self.candidates]
        identities = [
            (
                item.identity.dataset_kind,
                item.identity.uuid,
                item.identity.version,
            )
            for item in self.candidates
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        if len(identities) != len(set(identities)):
            raise ValueError("candidate dataset identities must be unique")
        has_accepted = any(item.disposition == "accepted" for item in self.candidates)
        if self.reference_closure.status == "failed":
            if has_accepted:
                raise ValueError(
                    "candidates cannot be accepted while reference closure is failed"
                )
            if self.acceptance_gate != "blocked":
                raise ValueError("failed reference closure requires a blocked gate")
        if self.acceptance_gate == "ready" and not has_accepted:
            raise ValueError("ready acceptance gate requires accepted candidates")
        return self


def parse_provider_candidate_manifest(payload: Any) -> ProviderCandidateManifest:
    return ProviderCandidateManifest.model_validate(payload)
