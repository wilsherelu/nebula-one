from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..domain.operations import validate_graph
from ..hashing import canonical_graph_sha256, canonical_json_sha256


COMMERCIAL_EXTENSION_NAMESPACE = "com.nebula-lca.commercial/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _uuid(value: str, label: str) -> str:
    value = value.strip()
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc
    return value


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class CommercialSourcePin(StrictContract):
    product: Literal["nebula-lca-commercial"]
    export_contract_version: Literal["1.0"] = "1.0"
    model_id: str = Field(min_length=1)
    model_version_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    graph_sha256: str

    @field_validator("model_id", "model_version_id")
    @classmethod
    def trim_identity(cls, value: str) -> str:
        return value.strip()

    @field_validator("graph_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA256.fullmatch(value):
            raise ValueError("graph_sha256 must be a lowercase SHA-256 digest")
        return value


class CommercialDemandItem(StrictContract):
    reference_flow_uuid: str
    reference_exchange_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    unit: str = Field(min_length=1)
    unit_group_uuid: str
    unit_group_version: str = Field(min_length=1)

    @field_validator("reference_flow_uuid")
    @classmethod
    def validate_flow_uuid(cls, value: str) -> str:
        return _uuid(value, "reference_flow_uuid")

    @field_validator("unit_group_uuid")
    @classmethod
    def validate_unit_group_uuid(cls, value: str) -> str:
        return _uuid(value, "unit_group_uuid")

    @field_validator("reference_exchange_id", "unit", "unit_group_version")
    @classmethod
    def trim_required(cls, value: str) -> str:
        return value.strip()

    @field_validator("amount")
    @classmethod
    def finite_amount(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        return value


class CommercialExportEnvelope(StrictContract):
    schema_version: Literal["nebula.commercial-model-export.v1"]
    source: CommercialSourcePin
    demand: list[CommercialDemandItem] = Field(min_length=1)
    graph: dict[str, Any]
    extensions: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("extensions")
    @classmethod
    def validate_extension_namespaces(
        cls, value: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        for namespace in value:
            if not re.fullmatch(r"[a-z0-9.-]+/[a-z0-9._-]+", namespace):
                raise ValueError(f"extension key is not a namespace/version: {namespace}")
        return value

    @model_validator(mode="after")
    def validate_graph_hash(self) -> "CommercialExportEnvelope":
        actual = canonical_graph_sha256(self.graph)
        if actual != self.source.graph_sha256:
            raise ValueError("source.graph_sha256 does not match the exported graph")
        return self


@dataclass(frozen=True)
class CommercialImportResult:
    source: CommercialSourcePin
    demand: tuple[CommercialDemandItem, ...]
    canonical_graph: dict[str, Any]
    extensions: dict[str, dict[str, Any]]
    canonical_graph_sha256: str
    extension_sha256: str


_GRAPH_EXTENSION_KEYS = {"node_positions", "canvases", "storage_schema_version"}
_NODE_EXTENSION_KEYS = {
    "position",
    "import_mode",
    "visibility",
    "market_allow_mixed_flows",
    "filtered_exchanges",
    "import_warnings",
}
_PORT_EXTENSION_KEYS = {
    "showOnNode",
    "show_on_node",
    "external_sale_amount",
    "allocation_factor",
    "allocation_basis",
    "unit_group_switch",
    "internal_exposed",
    "exposure_mode",
    "product_key",
    "port_key",
    "nested_source_process_name",
}
_EDGE_EXTENSION_KEYS = {
    "render_source_handle",
    "render_target_handle",
    "handle_mode",
    "handle_anchor",
    "connect_direction",
    "balance_status",
}


def _extract_keys(value: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for key in sorted(keys):
        if key in value:
            extracted[key] = value.pop(key)
    return extracted


def _split_graph(graph: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical = copy.deepcopy(graph)
    extension: dict[str, Any] = {"graph": {}, "nodes": {}, "ports": {}, "exchanges": {}}
    metadata = canonical.get("metadata")
    if isinstance(metadata, dict):
        extension["graph"] = _extract_keys(metadata, _GRAPH_EXTENSION_KEYS)

    for node in canonical.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        extracted = _extract_keys(node, _NODE_EXTENSION_KEYS)
        if extracted:
            extension["nodes"][node_id] = extracted
        for bucket in ("inputs", "outputs", "emissions"):
            for port in node.get(bucket, []):
                if not isinstance(port, dict):
                    continue
                port_id = str(port.get("id") or "").strip()
                port_extracted = _extract_keys(port, _PORT_EXTENSION_KEYS)
                if port_extracted:
                    extension["ports"][f"{node_id}/{port_id}"] = port_extracted

    for exchange in canonical.get("exchanges", []):
        if not isinstance(exchange, dict):
            continue
        exchange_id = str(exchange.get("id") or "").strip()
        extracted = _extract_keys(exchange, _EDGE_EXTENSION_KEYS)
        if extracted:
            extension["exchanges"][exchange_id] = extracted

    extension = {key: value for key, value in extension.items() if value}
    return canonical, extension


def _ports(graph: dict[str, Any]):
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        for bucket in ("inputs", "outputs", "emissions"):
            for port in node.get(bucket, []):
                if isinstance(port, dict):
                    yield node_id, port


def _field(value: dict[str, Any], camel: str, snake: str) -> Any:
    return value.get(camel, value.get(snake))


def _validate_demand(graph: dict[str, Any], demand: tuple[CommercialDemandItem, ...]) -> None:
    ports_by_id = {
        str(port.get("id") or "").strip(): port for _, port in _ports(graph)
    }
    for item in demand:
        port = ports_by_id.get(item.reference_exchange_id)
        if port is None:
            raise ValueError(
                f"demand reference exchange is not present: {item.reference_exchange_id}"
            )
        if str(_field(port, "flowUuid", "flow_uuid") or "") != item.reference_flow_uuid:
            raise ValueError("demand reference flow does not match its graph port")
        if str(port.get("unit") or "") != item.unit:
            raise ValueError("demand unit does not match its graph port")
        if str(_field(port, "unitGroupUuid", "unit_group_uuid") or "") != item.unit_group_uuid:
            raise ValueError("demand unit group UUID does not match its graph port")
        if str(_field(port, "unitGroupVersion", "unit_group_version") or "") != item.unit_group_version:
            raise ValueError("demand unit group version does not match its graph port")
        if not bool(_field(port, "isReferenceProduct", "is_reference_product")):
            raise ValueError("demand must target a reference product port")


def _validate_exact_flow_identities(graph: dict[str, Any]) -> None:
    required = (
        ("flowUuid", "flow_uuid"),
        ("flowSourceNamespace", "flow_source_namespace"),
        ("flowVersion", "flow_version"),
        ("flowPropertyUuid", "flow_property_uuid"),
        ("flowPropertyVersion", "flow_property_version"),
        ("unitGroupUuid", "unit_group_uuid"),
        ("unitGroupVersion", "unit_group_version"),
    )
    for node_id, port in _ports(graph):
        port_id = str(port.get("id") or "").strip()
        missing = [
            camel
            for camel, snake in required
            if not str(_field(port, camel, snake) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"flow port {node_id}/{port_id} lacks exact identity fields: "
                + ", ".join(missing)
            )
        _uuid(str(_field(port, "flowUuid", "flow_uuid")), "flowUuid")
        _uuid(
            str(_field(port, "flowPropertyUuid", "flow_property_uuid")),
            "flowPropertyUuid",
        )
        _uuid(
            str(_field(port, "unitGroupUuid", "unit_group_uuid")),
            "unitGroupUuid",
        )


def import_commercial_model(payload: dict[str, Any]) -> CommercialImportResult:
    envelope = CommercialExportEnvelope.model_validate(payload)
    canonical_graph, extracted = _split_graph(envelope.graph)
    validate_graph(canonical_graph)
    demand = tuple(envelope.demand)
    _validate_exact_flow_identities(canonical_graph)
    _validate_demand(canonical_graph, demand)

    extensions = copy.deepcopy(envelope.extensions)
    existing = extensions.get(COMMERCIAL_EXTENSION_NAMESPACE)
    if existing is not None and extracted:
        raise ValueError(
            "commercial fields must not be duplicated in graph and namespaced extensions"
        )
    if extracted:
        extensions[COMMERCIAL_EXTENSION_NAMESPACE] = extracted
    return CommercialImportResult(
        source=envelope.source,
        demand=demand,
        canonical_graph=canonical_graph,
        extensions=extensions,
        canonical_graph_sha256=canonical_graph_sha256(canonical_graph),
        extension_sha256=canonical_json_sha256(extensions),
    )


def _merge_graph(
    canonical_graph: dict[str, Any], extension: dict[str, Any]
) -> dict[str, Any]:
    graph = copy.deepcopy(canonical_graph)
    metadata = graph.setdefault("metadata", {})
    metadata.update(copy.deepcopy(extension.get("graph") or {}))
    nodes = {str(node.get("id") or ""): node for node in graph.get("nodes", [])}
    for node_id, values in (extension.get("nodes") or {}).items():
        if node_id not in nodes:
            raise ValueError(f"commercial extension references unknown node: {node_id}")
        nodes[node_id].update(copy.deepcopy(values))
    ports = {
        f"{node_id}/{str(port.get('id') or '')}": port
        for node_id, port in _ports(graph)
    }
    for port_key, values in (extension.get("ports") or {}).items():
        if port_key not in ports:
            raise ValueError(f"commercial extension references unknown port: {port_key}")
        ports[port_key].update(copy.deepcopy(values))
    exchanges = {
        str(exchange.get("id") or ""): exchange
        for exchange in graph.get("exchanges", [])
    }
    for exchange_id, values in (extension.get("exchanges") or {}).items():
        if exchange_id not in exchanges:
            raise ValueError(
                f"commercial extension references unknown exchange: {exchange_id}"
            )
        exchanges[exchange_id].update(copy.deepcopy(values))
    return graph


def export_commercial_model(result: CommercialImportResult) -> dict[str, Any]:
    extension = result.extensions.get(COMMERCIAL_EXTENSION_NAMESPACE, {})
    graph = _merge_graph(result.canonical_graph, extension)
    source = result.source.model_copy(
        update={"graph_sha256": canonical_graph_sha256(graph)}
    )
    return CommercialExportEnvelope(
        schema_version="nebula.commercial-model-export.v1",
        source=source,
        demand=list(result.demand),
        graph=graph,
        extensions={
            key: copy.deepcopy(value)
            for key, value in result.extensions.items()
            if key != COMMERCIAL_EXTENSION_NAMESPACE
        },
    ).model_dump(mode="json")
