from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..hashing import canonical_json_sha256
from .contracts import IDENTIFIER_PATTERN, VERSION_PATTERN, StrictContract


class SpatialGeometry(StrictContract):
    type: Literal["Point", "Polygon", "MultiPolygon"]
    coordinates: list[Any]
    crs: Literal["EPSG:4326"]


class SpatialUnit(StrictContract):
    schema_version: Literal["nebula.spatial-unit.v1"]
    spatial_unit_id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    spatial_level: Literal["park", "facility"]
    geometry: SpatialGeometry
    claim_level: Literal["demonstration", "measured"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self):
        content = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(content) != self.content_sha256:
            raise ValueError("spatial_unit content_sha256 does not match its content")
        return self


class EntityRegistryIdentity(StrictContract):
    id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    claim_level: Literal["demonstration", "measured"]


class EntityRegistryEntity(StrictContract):
    entity_id: str = Field(pattern=IDENTIFIER_PATTERN)
    entity_type: Literal["park", "facility"]
    name: str = Field(min_length=1, max_length=255)
    parent_entity_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    spatial_unit: SpatialUnit

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("entity name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_level(self):
        if self.spatial_unit.spatial_level != self.entity_type:
            raise ValueError("spatial_unit level must match entity_type")
        if self.entity_type == "park" and self.parent_entity_id is not None:
            raise ValueError("park entity cannot have a parent_entity_id")
        if self.entity_type == "facility" and self.parent_entity_id is None:
            raise ValueError("facility entity requires a parent_entity_id")
        return self


class EntityProcessBinding(StrictContract):
    graph_node_id: str = Field(min_length=1, max_length=255)
    process_uuid: str = Field(min_length=1, max_length=255)
    entity_id: str = Field(pattern=IDENTIFIER_PATTERN)


class ParkBoundaryTemplate(StrictContract):
    boundary_id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    park_entity_id: str = Field(pattern=IDENTIFIER_PATTERN)
    included_entity_ids: tuple[str, ...] = Field(min_length=2)
    reporting_period_id: str = Field(pattern=IDENTIFIER_PATTERN)
    consolidation_policy: dict[str, str]

    @model_validator(mode="after")
    def validate_policy(self):
        required = {
            "intra_facility": "eliminate",
            "inter_facility": "retain_as_internal",
            "external_boundary": "solved_snapshot_boundary_flows",
        }
        if self.consolidation_policy != required:
            raise ValueError("park boundary consolidation policy is unsupported")
        if self.park_entity_id not in self.included_entity_ids:
            raise ValueError("park boundary must include its park entity")
        if len(self.included_entity_ids) != len(set(self.included_entity_ids)):
            raise ValueError("park boundary included entities must be unique")
        return self


class EntityRegistryDocument(StrictContract):
    schema_version: Literal["nebula.entity-registry.v2"]
    registry: EntityRegistryIdentity
    entities: tuple[EntityRegistryEntity, ...] = Field(min_length=2)
    process_bindings: tuple[EntityProcessBinding, ...] = Field(min_length=1)
    park_boundaries: tuple[ParkBoundaryTemplate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self):
        entity_by_id = {item.entity_id: item for item in self.entities}
        if len(entity_by_id) != len(self.entities):
            raise ValueError("entity registry entity IDs must be unique")
        spatial_refs = {
            (item.spatial_unit.spatial_unit_id, item.spatial_unit.version)
            for item in self.entities
        }
        if len(spatial_refs) != len(self.entities):
            raise ValueError("spatial unit identities must be unique")
        for entity in self.entities:
            if entity.parent_entity_id is not None:
                parent = entity_by_id.get(entity.parent_entity_id)
                if parent is None or parent.entity_type != "park":
                    raise ValueError("facility parent must resolve to a park entity")
        binding_keys = [
            (item.graph_node_id, item.process_uuid) for item in self.process_bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("entity registry process bindings must be unique")
        for binding in self.process_bindings:
            entity = entity_by_id.get(binding.entity_id)
            if entity is None or entity.entity_type != "facility":
                raise ValueError("process bindings must target a facility entity")
        boundary_ids = [item.boundary_id for item in self.park_boundaries]
        if len(boundary_ids) != len(set(boundary_ids)):
            raise ValueError("park boundary IDs must be unique")
        for boundary in self.park_boundaries:
            park = entity_by_id.get(boundary.park_entity_id)
            if park is None or park.entity_type != "park":
                raise ValueError("park boundary park_entity_id must resolve to a park")
            if any(item not in entity_by_id for item in boundary.included_entity_ids):
                raise ValueError("park boundary includes an unknown entity")
        return self


def parse_entity_registry(payload: Any) -> EntityRegistryDocument:
    return EntityRegistryDocument.model_validate(payload)
