"""Match a reviewed emission selector to a model port without depending on its local port id."""
from __future__ import annotations

from typing import Any


FLOW_FIELDS = {
    "flowSourceNamespace": "source_namespace",
    "flowUuid": "flow_uuid",
    "flowVersion": "version",
    "flowPropertyUuid": "flow_property_uuid",
    "flowPropertyVersion": "flow_property_version",
    "unitGroupUuid": "unit_group_uuid",
    "unitGroupVersion": "unit_group_version",
    "unit": "unit",
    "direction": "direction",
}


def selector_matches(selector: dict[str, Any], node: dict[str, Any], port: dict[str, Any]) -> bool:
    """Every declared identity field must be present and equal on the model side."""
    if node.get("process_uuid") != selector.get("process_uuid") or port.get("type") != "biosphere":
        return False
    return all(
        selector.get(declared) not in (None, "")
        and port.get(actual) == selector[declared]
        for actual, declared in FLOW_FIELDS.items()
    )


def selected_emissions(graph: dict[str, Any], selector: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return [
        (f"{node['id']}::{port['id']}", node, port)
        for node in graph.get("nodes", [])
        for port in node.get("outputs", [])
        if selector_matches(selector, node, port)
    ]
