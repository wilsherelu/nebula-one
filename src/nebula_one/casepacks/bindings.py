from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .contracts import (
    SHA256_PATTERN,
    StrictContract,
    VersionedIdentity,
    canonical_contract_sha256,
)


class ParameterBindingError(DomainError):
    pass


def _fail(code: str, message: str, **details: Any) -> None:
    raise ParameterBindingError(
        code=code,
        message=message,
        status_code=422,
        details=details,
    )


class UnitIdentity(StrictContract):
    unit: str = Field(min_length=1, max_length=128)
    unit_group: str = Field(min_length=1, max_length=255)
    unit_group_uuid: str | None = Field(default=None, max_length=255)
    unit_group_version: str | None = Field(default=None, max_length=128)

    @field_validator("unit", "unit_group", "unit_group_uuid", "unit_group_version")
    @classmethod
    def strip_unit_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("unit identity values cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_complete_versioned_identity(self):
        if (self.unit_group_uuid is None) != (self.unit_group_version is None):
            raise ValueError(
                "unit_group_uuid and unit_group_version must be provided together"
            )
        return self


class ParameterValue(StrictContract):
    value: float = Field(ge=0, allow_inf_nan=False)
    quantity_kind: Literal["amount", "scale_factor"]
    unit_identity: UnitIdentity


class ParameterSetSnapshot(StrictContract):
    schema_version: Literal["nebula.parameter-set.snapshot.v1"]
    parameter_set_id: str = Field(min_length=1, max_length=255)
    status: Literal["frozen"]
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    values: dict[str, ParameterValue] = Field(min_length=1)
    metadata: dict[str, Any]

    @field_validator("parameter_set_id")
    @classmethod
    def strip_parameter_set_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("parameter_set_id cannot be blank")
        return normalized

    @field_validator("values")
    @classmethod
    def validate_parameter_keys(
        cls, values: dict[str, ParameterValue]
    ) -> dict[str, ParameterValue]:
        normalized: dict[str, ParameterValue] = {}
        for key, value in values.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("parameter keys cannot be blank")
            if normalized_key in normalized:
                raise ValueError("parameter keys must be unique after trimming")
            normalized[normalized_key] = value
        return normalized


class CaseParameterSetIdentity(VersionedIdentity):
    lifecycle_status: Literal["frozen"]


class CaseParameterSetDocument(StrictContract):
    schema_version: Literal["nebula.case-parameter-set.v1"]
    parameter_set: CaseParameterSetIdentity
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    values: dict[str, ParameterValue] = Field(min_length=1)
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def verify_content_hash(self):
        actual = canonical_json_sha256(
            {
                "values": {
                    key: value.model_dump(mode="json")
                    for key, value in self.values.items()
                },
                "metadata": self.metadata,
            }
        )
        if self.content_sha256 != actual:
            raise ValueError(
                "Case ParameterSet content hash does not match values and metadata"
            )
        return self


class ParentRevisionSnapshot(StrictContract):
    revision_id: str = Field(min_length=1, max_length=255)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    graph: dict[str, Any]


class ParameterBindingIdentity(VersionedIdentity):
    lifecycle_status: Literal["draft", "frozen"]


class SetExchangeAmountTarget(StrictContract):
    process_id: str = Field(min_length=1, max_length=255)
    port_id: str = Field(min_length=1, max_length=255)
    flow_uuid: str = Field(min_length=1, max_length=255)
    unit_identity: UnitIdentity


class ScaleFlowTarget(StrictContract):
    flow_uuid: str = Field(min_length=1, max_length=255)
    unit_group: str = Field(min_length=1, max_length=255)
    unit_group_uuid: str | None = Field(default=None, max_length=255)
    unit_group_version: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_complete_versioned_identity(self):
        if (self.unit_group_uuid is None) != (self.unit_group_version is None):
            raise ValueError(
                "unit_group_uuid and unit_group_version must be provided together"
            )
        return self


class SetExchangeAmountBinding(StrictContract):
    binding_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=1)
    operation: Literal["set_exchange_amount"]
    parameter_key: str = Field(min_length=1, max_length=255)
    parameter_unit_identity: UnitIdentity
    target: SetExchangeAmountTarget


class ScaleFlowBinding(StrictContract):
    binding_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=1)
    operation: Literal["scale_flow"]
    parameter_key: str = Field(min_length=1, max_length=255)
    parameter_unit_identity: UnitIdentity
    target: ScaleFlowTarget


BindingRule = Annotated[
    SetExchangeAmountBinding | ScaleFlowBinding,
    Field(discriminator="operation"),
]


class ParameterBindingDocument(StrictContract):
    schema_version: Literal["nebula.parameter-binding.v1"]
    parameter_binding: ParameterBindingIdentity
    rule_version: Literal["model-operation.v1"]
    bindings: tuple[BindingRule, ...] = Field(min_length=1, max_length=100)

    @field_validator("bindings")
    @classmethod
    def order_bindings(
        cls, values: tuple[BindingRule, ...]
    ) -> tuple[BindingRule, ...]:
        return tuple(sorted(values, key=lambda item: (item.order, item.binding_id)))

    @model_validator(mode="after")
    def validate_binding_uniqueness(self):
        binding_ids = [item.binding_id for item in self.bindings]
        orders = [item.order for item in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("binding_id values must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("binding order values must be unique")
        target_keys: list[tuple[str, ...]] = []
        scaled_flows: set[str] = set()
        set_flows: set[str] = set()
        for item in self.bindings:
            if item.operation == "set_exchange_amount":
                target_keys.append(("port", item.target.process_id, item.target.port_id))
                set_flows.add(item.target.flow_uuid)
            else:
                target_keys.append(
                    ("flow", item.target.flow_uuid, item.target.unit_group.casefold())
                )
                scaled_flows.add(item.target.flow_uuid)
        if len(target_keys) != len(set(target_keys)):
            raise ValueError("binding targets must be unique")
        overlap = sorted(set_flows.intersection(scaled_flows))
        if overlap:
            raise ValueError(
                f"set_exchange_amount and scale_flow targets overlap: {overlap}"
            )
        return self


class ResolvedModelOperation(StrictContract):
    sequence: int = Field(ge=1)
    binding_id: str
    parameter_key: str
    operation_type: Literal["flow.update_port", "system.scale_flows"]
    target_kind: Literal["flow", "system"]
    target_id: str
    payload: dict[str, Any]


class ResolvedOperationSet(StrictContract):
    schema_version: Literal["nebula.resolved-operation-set.v1"]
    binding_id: str
    binding_version: str
    rule_version: Literal["model-operation.v1"]
    binding_content_sha256: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str
    parameter_set_content_sha256: str = Field(pattern=SHA256_PATTERN)
    parent_revision_id: str
    parent_content_sha256: str = Field(pattern=SHA256_PATTERN)
    operations: tuple[ResolvedModelOperation, ...] = Field(min_length=1)
    operation_set_sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=128)


def parse_parameter_set_snapshot(payload: Any) -> ParameterSetSnapshot:
    if not isinstance(payload, dict):
        _fail("PARAMETER_SET_SNAPSHOT_INVALID", "parameter set snapshot must be an object")
    expected = payload.get("content_sha256")
    values = payload.get("values")
    metadata = payload.get("metadata")
    if not isinstance(values, dict) or not isinstance(metadata, dict):
        _fail(
            "PARAMETER_SET_SNAPSHOT_INVALID",
            "parameter set snapshot requires object values and metadata",
        )
    actual = canonical_json_sha256({"values": values, "metadata": metadata})
    if expected != actual:
        _fail(
            "PARAMETER_SET_HASH_MISMATCH",
            "parameter set content hash does not match values and metadata",
            expected=expected,
            actual=actual,
        )
    try:
        return ParameterSetSnapshot.model_validate(payload)
    except ValidationError as exc:
        raise ParameterBindingError(
            code="PARAMETER_SET_SNAPSHOT_INVALID",
            message="parameter set snapshot contract validation failed",
            status_code=422,
            details={"errors": exc.errors(include_url=False)},
        ) from exc


def parse_case_parameter_set(payload: Any) -> CaseParameterSetDocument:
    return CaseParameterSetDocument.model_validate(payload)


def _port(graph: dict[str, Any], process_id: str, port_id: str) -> dict[str, Any]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        _fail("PARAMETER_BINDING_GRAPH_INVALID", "parent graph nodes must be a list")
    for node in nodes:
        if not isinstance(node, dict) or str(node.get("id") or "").strip() != process_id:
            continue
        for group in ("inputs", "outputs", "emissions"):
            ports = node.get(group, [])
            if not isinstance(ports, list):
                _fail(
                    "PARAMETER_BINDING_GRAPH_INVALID",
                    f"process {process_id} {group} must be a list",
                )
            for port in ports:
                if isinstance(port, dict) and str(port.get("id") or "").strip() == port_id:
                    return port
        _fail(
            "PARAMETER_BINDING_TARGET_NOT_FOUND",
            "target process port was not found",
            process_id=process_id,
            port_id=port_id,
        )
    _fail(
        "PARAMETER_BINDING_TARGET_NOT_FOUND",
        "target process was not found",
        process_id=process_id,
    )


def _graph_value(payload: dict[str, Any], camel: str, snake: str) -> str | None:
    value = payload.get(camel, payload.get(snake))
    normalized = str(value or "").strip()
    return normalized or None


def _validate_unit_against_graph(
    expected: UnitIdentity, graph_item: dict[str, Any]
) -> None:
    actual_unit = _graph_value(graph_item, "unit", "unit")
    actual_group = _graph_value(graph_item, "unitGroup", "unit_group")
    if actual_unit is None or actual_group is None:
        _fail(
            "PARAMETER_BINDING_GRAPH_INVALID",
            "target graph exchange requires unit and unit group identity",
        )
    try:
        actual = UnitIdentity(
            unit=actual_unit,
            unit_group=actual_group,
            unit_group_uuid=_graph_value(
                graph_item, "unitGroupUuid", "unit_group_uuid"
            ),
            unit_group_version=_graph_value(
                graph_item, "unitGroupVersion", "unit_group_version"
            ),
        )
    except ValidationError as exc:
        raise ParameterBindingError(
            code="PARAMETER_BINDING_GRAPH_INVALID",
            message="target graph exchange has an incomplete unit identity",
            status_code=422,
            details={"errors": exc.errors(include_url=False)},
        ) from exc
    if actual != expected:
        _fail(
            "PARAMETER_BINDING_UNIT_MISMATCH",
            "binding unit identity does not match the target graph exchange",
            expected=expected.model_dump(mode="json"),
            actual=actual.model_dump(mode="json"),
        )


def _validate_scale_target(graph: dict[str, Any], target: ScaleFlowTarget) -> None:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        _fail("PARAMETER_BINDING_GRAPH_INVALID", "parent graph nodes must be a list")
    matches: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for group in ("inputs", "outputs", "emissions"):
            ports = node.get(group, [])
            if not isinstance(ports, list):
                _fail(
                    "PARAMETER_BINDING_GRAPH_INVALID",
                    f"graph process {group} must be a list",
                )
            for port in ports:
                if not isinstance(port, dict):
                    continue
                if _graph_value(port, "flowUuid", "flow_uuid") != target.flow_uuid:
                    continue
                if (_graph_value(port, "unitGroup", "unit_group") or "").casefold() != target.unit_group.casefold():
                    continue
                matches.append(port)
    if not matches:
        _fail(
            "PARAMETER_BINDING_TARGET_NOT_FOUND",
            "scale_flow target did not match any graph flow ports",
            flow_uuid=target.flow_uuid,
            unit_group=target.unit_group,
        )
    if target.unit_group_uuid is not None:
        for port in matches:
            if (
                _graph_value(port, "unitGroupUuid", "unit_group_uuid")
                != target.unit_group_uuid
                or _graph_value(port, "unitGroupVersion", "unit_group_version")
                != target.unit_group_version
            ):
                _fail(
                    "PARAMETER_BINDING_UNIT_MISMATCH",
                    "scale_flow versioned unit group does not match the graph",
                    flow_uuid=target.flow_uuid,
                )


def resolve_parameter_binding(
    binding: ParameterBindingDocument,
    parameter_set: ParameterSetSnapshot,
    parent_revision: ParentRevisionSnapshot,
) -> ResolvedOperationSet:
    if binding.parameter_binding.lifecycle_status != "frozen":
        _fail(
            "PARAMETER_BINDING_NOT_FROZEN",
            "only a frozen ParameterBinding can be resolved",
        )
    referenced_keys = {item.parameter_key for item in binding.bindings}
    actual_keys = set(parameter_set.values)
    missing = sorted(referenced_keys.difference(actual_keys))
    unused = sorted(actual_keys.difference(referenced_keys))
    if missing:
        _fail(
            "PARAMETER_BINDING_PARAMETER_MISSING",
            "ParameterSet is missing required binding values",
            parameter_keys=missing,
        )
    if unused:
        _fail(
            "PARAMETER_BINDING_PARAMETER_UNUSED",
            "ParameterSet contains values not consumed by this binding",
            parameter_keys=unused,
        )

    operations: list[ResolvedModelOperation] = []
    for sequence, rule in enumerate(
        sorted(binding.bindings, key=lambda item: item.order), start=1
    ):
        parameter = parameter_set.values[rule.parameter_key]
        if parameter.unit_identity != rule.parameter_unit_identity:
            _fail(
                "PARAMETER_BINDING_UNIT_MISMATCH",
                "parameter unit identity does not match its binding",
                binding_id=rule.binding_id,
                expected=rule.parameter_unit_identity.model_dump(mode="json"),
                actual=parameter.unit_identity.model_dump(mode="json"),
            )
        if rule.operation == "set_exchange_amount":
            if parameter.quantity_kind != "amount":
                _fail(
                    "PARAMETER_BINDING_QUANTITY_KIND_MISMATCH",
                    "set_exchange_amount requires an amount parameter",
                    binding_id=rule.binding_id,
                )
            port = _port(
                parent_revision.graph,
                rule.target.process_id,
                rule.target.port_id,
            )
            if _graph_value(port, "flowUuid", "flow_uuid") != rule.target.flow_uuid:
                _fail(
                    "PARAMETER_BINDING_FLOW_MISMATCH",
                    "target process port has a different Flow identity",
                    binding_id=rule.binding_id,
                )
            if rule.target.unit_identity != rule.parameter_unit_identity:
                _fail(
                    "PARAMETER_BINDING_UNIT_MISMATCH",
                    "target and parameter unit identities differ",
                    binding_id=rule.binding_id,
                )
            _validate_unit_against_graph(rule.target.unit_identity, port)
            operations.append(
                ResolvedModelOperation(
                    sequence=sequence,
                    binding_id=rule.binding_id,
                    parameter_key=rule.parameter_key,
                    operation_type="flow.update_port",
                    target_kind="flow",
                    target_id=f"{rule.target.process_id}/{rule.target.port_id}",
                    payload={
                        "process_id": rule.target.process_id,
                        "port_id": rule.target.port_id,
                        "changes": {"amount": parameter.value},
                    },
                )
            )
        else:
            if parameter.quantity_kind != "scale_factor" or parameter.value <= 0:
                _fail(
                    "PARAMETER_BINDING_QUANTITY_KIND_MISMATCH",
                    "scale_flow requires a strictly positive scale_factor",
                    binding_id=rule.binding_id,
                )
            if parameter.unit_identity.unit != "1":
                _fail(
                    "PARAMETER_BINDING_UNIT_MISMATCH",
                    "scale_flow factor must use the explicit dimensionless unit '1'",
                    binding_id=rule.binding_id,
                )
            _validate_scale_target(parent_revision.graph, rule.target)
            operations.append(
                ResolvedModelOperation(
                    sequence=sequence,
                    binding_id=rule.binding_id,
                    parameter_key=rule.parameter_key,
                    operation_type="system.scale_flows",
                    target_kind="system",
                    target_id=f"{rule.target.flow_uuid}@{rule.target.unit_group}",
                    payload={
                        "factor": parameter.value,
                        "unit_groups": [rule.target.unit_group],
                        "flow_uuids": [rule.target.flow_uuid],
                    },
                )
            )

    binding_hash = canonical_contract_sha256(binding)
    basis = {
        "schema_version": "nebula.resolved-operation-set.v1",
        "binding_id": binding.parameter_binding.id,
        "binding_version": binding.parameter_binding.version,
        "rule_version": binding.rule_version,
        "binding_content_sha256": binding_hash,
        "parameter_set_id": parameter_set.parameter_set_id,
        "parameter_set_content_sha256": parameter_set.content_sha256,
        "parent_revision_id": parent_revision.revision_id,
        "parent_content_sha256": parent_revision.content_sha256,
        "operations": [item.model_dump(mode="json") for item in operations],
    }
    operation_set_hash = canonical_json_sha256(basis)
    return ResolvedOperationSet(
        **basis,
        operation_set_sha256=operation_set_hash,
        idempotency_key=f"parameter-binding:{operation_set_hash}",
    )


def parse_parameter_binding(payload: Any) -> ParameterBindingDocument:
    return ParameterBindingDocument.model_validate(payload)


def to_operation_batch_create(
    resolved: ResolvedOperationSet, *, label: str | None = None
):
    from ..schemas import ModelOperationBatchCreate, ModelOperationItem

    return ModelOperationBatchCreate(
        parent_revision_id=resolved.parent_revision_id,
        expected_parent_content_sha256=resolved.parent_content_sha256,
        idempotency_key=resolved.idempotency_key,
        operations=[
            ModelOperationItem(
                operation_type=item.operation_type,
                payload=item.payload,
            )
            for item in resolved.operations
        ],
        label=label or f"Parameter binding {resolved.binding_id}@{resolved.binding_version}",
    )
